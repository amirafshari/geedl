"""Scene-mode helpers: enumerate EE scenes and suggest nearby dates.

EE-aware; not pure. Lives alongside compositor.py — windows.py stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import logging

import ee

from ..datasets.registry import DatasetSpec

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scene:
    scene_id: str
    date: date
    time_start_ms: int


class NoScenesAvailableError(Exception):
    """No scenes intersect the ROI in the requested range.

    Carries up to `suggestions` nearest available dates (may be empty if the
    widened search also turned up nothing).
    """

    def __init__(
        self,
        dataset: str,
        requested: tuple[date, date],
        suggestions: list[date],
    ) -> None:
        self.dataset = dataset
        self.requested = requested
        self.suggestions = suggestions
        start, end = requested
        when = start.isoformat() if start == end else f"{start} → {end}"
        if suggestions:
            sug = ", ".join(d.isoformat() for d in suggestions)
            msg = f"No {dataset} scenes over ROI on {when}. Closest available: {sug}"
        else:
            msg = f"No {dataset} scenes over ROI on {when} (or within ±730 days)."
        super().__init__(msg)


def _scenes_in_range(
    dataset_spec: DatasetSpec,
    roi_fc: ee.FeatureCollection,
    start: date,
    end_exclusive: date,
) -> list[Scene]:
    col = (
        ee.ImageCollection(dataset_spec.collection)
        .filterDate(start.isoformat(), end_exclusive.isoformat())
        .filterBounds(roi_fc.geometry())
    )
    for f in dataset_spec.extra_filters:
        col = col.filter(ee.Filter.eq(f["property"], f["value"]))

    info = col.aggregate_array(dataset_spec.date_property).getInfo() or []
    ids = col.aggregate_array("system:index").getInfo() or []
    out: list[Scene] = []
    for sid, t in zip(ids, info):
        try:
            ts = int(t)
        except (TypeError, ValueError):
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
        out.append(Scene(scene_id=str(sid), date=d, time_start_ms=ts))
    out.sort(key=lambda s: s.time_start_ms)
    return out


def enumerate_scenes(
    dataset_spec: DatasetSpec,
    roi_fc: ee.FeatureCollection,
    start: date,
    end: date,
) -> list[Scene]:
    """Scenes intersecting ROI within [start, end] inclusive on both ends."""
    return _scenes_in_range(dataset_spec, roi_fc, start, end + timedelta(days=1))


def suggest_nearest_dates(
    dataset_spec: DatasetSpec,
    roi_fc: ee.FeatureCollection,
    target: date,
    *,
    n: int = 5,
    search_days: int = 365,
) -> list[date]:
    """Return up to `n` distinct dates nearest to `target` with scenes over ROI.

    Searches ±search_days; if empty, widens once to ±(2*search_days), then gives up.
    """
    for radius in (search_days, search_days * 2):
        lo = target - timedelta(days=radius)
        hi = target + timedelta(days=radius + 1)
        scenes = _scenes_in_range(dataset_spec, roi_fc, lo, hi)
        if scenes:
            seen: dict[date, int] = {}
            for s in scenes:
                delta = abs((s.date - target).days)
                if s.date not in seen or delta < seen[s.date]:
                    seen[s.date] = delta
            ranked = sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))
            return [d for d, _ in ranked[:n]]
    return []


def scene_roi_coverage(
    dataset_spec: DatasetSpec,
    scene: Scene,
    roi_fc: ee.FeatureCollection,
    cloud_mask_fn,
) -> float:
    """Fraction of ROI pixels that survive the cloud mask for a single scene.

    Returns a value in [0.0, 1.0]. Uses the first band as a probe; the cloud
    mask is what makes pixels invalid, so any single band reflects it.
    """
    img = ee.Image(f"{dataset_spec.collection}/{scene.scene_id}")
    if cloud_mask_fn is not None:
        img = cloud_mask_fn(img)
    probe_band = dataset_spec.band_names()[0]
    probe = img.select(probe_band)
    valid = probe.mask().rename("valid")
    # Use the native resolution and scale down for cost: at 10x native, a
    # province-sized ROI costs ~O(1M px) which fits in a single reduceRegion.
    scale = dataset_spec.native_res * 10
    stats = valid.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi_fc.geometry(),
        scale=scale,
        maxPixels=1e10,
        bestEffort=True,
    )
    val = stats.get("valid").getInfo()
    return float(val) if val is not None else 0.0


def filter_scenes_by_coverage(
    dataset_spec: DatasetSpec,
    scenes: list[Scene],
    roi_fc: ee.FeatureCollection,
    cloud_mask_fn,
    min_coverage: float,
) -> tuple[list[Scene], dict[str, float]]:
    """Drop scenes whose ROI cloud-free coverage is below `min_coverage`.

    Returns (kept, coverage_map) — coverage_map keyed by scene_id so the caller
    can log/explain why a date was rejected.
    """
    kept: list[Scene] = []
    coverage: dict[str, float] = {}
    for s in scenes:
        c = scene_roi_coverage(dataset_spec, s, roi_fc, cloud_mask_fn)
        coverage[s.scene_id] = c
        if c >= min_coverage:
            kept.append(s)
            log.info("scene %s (%s) coverage=%.1f%% — kept", s.scene_id, s.date, c * 100)
        else:
            log.warning(
                "scene %s (%s) coverage=%.1f%% < %.1f%% — dropped",
                s.scene_id, s.date, c * 100, min_coverage * 100,
            )
    return kept, coverage


def scenes_to_windows(scenes: list[Scene], label_format: str):
    """One Window per date. Each window carries the EE asset IDs of every
    scene kept for that date so the downstream collection is pinned to those
    exact scenes (not re-derived from date+bounds, which would re-include
    rejected scenes alphabetically).
    """
    from ..utils.windows import Window

    by_date: dict[date, list[Scene]] = {}
    for s in scenes:
        by_date.setdefault(s.date, []).append(s)
    out = []
    for d in sorted(by_date):
        same_day = sorted(by_date[d], key=lambda s: s.time_start_ms)
        ids = tuple(s.scene_id for s in same_day)
        out.append(
            Window(d, d + timedelta(days=1), d.strftime(label_format), scene_ids=ids)
        )
    return out


__all__ = [
    "Scene",
    "NoScenesAvailableError",
    "enumerate_scenes",
    "suggest_nearest_dates",
    "scenes_to_windows",
    "scene_roi_coverage",
    "filter_scenes_by_coverage",
]
