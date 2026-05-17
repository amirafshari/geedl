"""Window generation + image compositing."""

from __future__ import annotations

import ee

from ..config import DatasetConfig, IndexEntry
from ..datasets import cloud_masks
from ..datasets.registry import DatasetSpec
from ..indices import apply_indices
from ..utils.windows import Window


def build_collection(
    dataset_cfg: DatasetConfig,
    dataset_spec: DatasetSpec,
    window: Window,
    roi_fc: ee.FeatureCollection,
) -> ee.ImageCollection:
    if window.scene_ids:
        # Scene mode with pinned IDs: build from explicit images so we use
        # exactly the scenes the coverage filter approved.
        col = ee.ImageCollection(
            [ee.Image(f"{dataset_spec.collection}/{sid}") for sid in window.scene_ids]
        )
    else:
        col = (
            ee.ImageCollection(dataset_spec.collection)
            .filterDate(window.start.isoformat(), window.end.isoformat())
            .filterBounds(roi_fc.geometry())
        )
        for f in dataset_spec.extra_filters:
            col = col.filter(ee.Filter.eq(f["property"], f["value"]))
    if dataset_cfg.cloud_mask.enabled and dataset_spec.cloud_mask:
        profile_name = (
            dataset_spec.cloud_mask
            if dataset_cfg.cloud_mask.profile == "auto"
            else dataset_cfg.cloud_mask.profile
        )
        mask_fn = cloud_masks.get(
            profile_name,
            {
                "mask_shadow": dataset_cfg.cloud_mask.mask_shadow,
                "mask_snow": dataset_cfg.cloud_mask.mask_snow,
            },
        )
        col = col.map(mask_fn)
    return col


def composite(
    col: ee.ImageCollection,
    strategy: str,
    dataset_spec: DatasetSpec,
) -> ee.Image:
    """Reduce the collection. Sentinel-1 (and any override) always wins."""
    effective = dataset_spec.composite_strategy_override or strategy
    if effective == "median":
        return col.median()
    if effective == "mean":
        return col.mean()
    if effective == "mosaic":
        return col.mosaic()
    if effective == "none":
        return col.first()
    raise ValueError(f"Unknown composite strategy: {effective!r}")


def _resolve_band_order(dataset_cfg: DatasetConfig, default_bands: list[str]) -> list[str]:
    base = list(dataset_cfg.bands.order or dataset_cfg.bands.select or default_bands)
    result = base[:]
    int_offset = 0
    for entry in dataset_cfg.indices:
        name = entry.output_band or entry.name
        if entry.position == "after_bands":
            result.append(name)
        elif entry.position == "before_bands":
            result.insert(0, name)
        elif isinstance(entry.position, int):
            result.insert(entry.position + int_offset, name)
            int_offset += 1
        else:
            raise ValueError(f"unknown index position: {entry.position!r}")
    return result


def apply_bands_and_indices(
    image: ee.Image,
    dataset_cfg: DatasetConfig,
    dataset_spec: DatasetSpec,
) -> tuple[ee.Image, list[str]]:
    """Apply select → scale/offset → indices → reorder → rename.

    Returns the final image and the ordered band list (post-rename).
    """
    selected = list(dataset_cfg.bands.select or dataset_spec.band_names())
    img = image.select(selected)

    scale = dataset_cfg.bands.scale_factor
    if scale is None:
        scale = dataset_spec.scale_factor
    offset = dataset_cfg.bands.offset or dataset_spec.offset

    # Scale/offset apply only to bands flagged scaled=true in the registry.
    # Classification/QA bands (SCL, QA_PIXEL) must keep their integer codes.
    scaled = [b for b in selected if dataset_spec.bands[b].scaled]
    unscaled = [b for b in selected if not dataset_spec.bands[b].scaled]
    needs_scale = scaled and ((scale is not None and scale != 1.0) or offset)
    if needs_scale:
        scaled_img = img.select(scaled)
        if scale is not None and scale != 1.0:
            scaled_img = scaled_img.multiply(scale)
        if offset:
            scaled_img = scaled_img.add(offset)
        if unscaled:
            img = scaled_img.addBands(img.select(unscaled)).select(selected)
        else:
            img = scaled_img.select(selected)

    index_names = [e.name for e in dataset_cfg.indices]
    if index_names:
        img = apply_indices(img, index_names, dataset_cfg.name)
        # Rename index output bands if output_band != name.
        renames_old = [e.name for e in dataset_cfg.indices if e.output_band and e.output_band != e.name]
        renames_new = [e.output_band for e in dataset_cfg.indices if e.output_band and e.output_band != e.name]
        if renames_old:
            current = selected + [e.name for e in dataset_cfg.indices]
            renamed = [
                next((nw for old, nw in zip(renames_old, renames_new) if old == b), b)
                for b in current
            ]
            img = img.select(current, renamed)

    ordered = _resolve_band_order(dataset_cfg, selected)
    img = img.select(ordered)

    if dataset_cfg.bands.rename:
        new = [dataset_cfg.bands.rename.get(b, b) for b in ordered]
        img = img.select(ordered, new)
        ordered = new

    return img, ordered


def build_window_image(
    dataset_cfg: DatasetConfig,
    dataset_spec: DatasetSpec,
    composite_strategy: str,
    window: Window,
    roi_fc: ee.FeatureCollection,
) -> tuple[ee.Image, list[str]]:
    col = build_collection(dataset_cfg, dataset_spec, window, roi_fc)
    composited = composite(col, composite_strategy, dataset_spec)
    return apply_bands_and_indices(composited, dataset_cfg, dataset_spec)


__all__ = [
    "build_collection",
    "composite",
    "apply_bands_and_indices",
    "build_window_image",
    "Window",
    "IndexEntry",
]
