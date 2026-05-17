"""Scene-mode helpers: enumerate EE scenes and suggest nearby dates.

EE-aware; not pure. Lives alongside compositor.py — windows.py stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import ee

from ..datasets.registry import DatasetSpec


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


def scenes_to_windows(scenes: list[Scene], label_format: str):
    """Synthesize one Window per scene so the rest of the pipeline is unchanged.

    Each window spans a single day; tile IDs include the date label, so multiple
    scenes on the same day collapse into one output (composite handles it).
    """
    from ..utils.windows import Window

    by_date: dict[date, Scene] = {}
    for s in scenes:
        if s.date not in by_date or s.time_start_ms < by_date[s.date].time_start_ms:
            by_date[s.date] = s
    return [
        Window(d, d + timedelta(days=1), d.strftime(label_format))
        for d in sorted(by_date)
    ]


__all__ = [
    "Scene",
    "NoScenesAvailableError",
    "enumerate_scenes",
    "suggest_nearest_dates",
    "scenes_to_windows",
]
