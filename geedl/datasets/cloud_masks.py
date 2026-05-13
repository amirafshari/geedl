"""Per-sensor cloud / shadow / snow mask functions.

Each function: (ee.Image) -> ee.Image. Names match `cloud_mask:` in registry.yaml.
The mask_shadow / mask_snow toggles are passed in from the dataset cloud_mask
config; resolution into a profile happens in compositor.py via `get(name, opts)`.
"""

from __future__ import annotations

from collections.abc import Callable

import ee


def s2_scl_mask(opts: dict[str, bool] | None = None) -> Callable[[ee.Image], ee.Image]:
    """Sentinel-2 SCL-based cloud mask.

    SCL classes:
      0 NO_DATA  1 SATURATED  2 DARK_AREA  3 CLOUD_SHADOW  4 VEGETATION
      5 BARE     6 WATER      7 UNCLASSIFIED  8 CLOUD_MED  9 CLOUD_HIGH
      10 CIRRUS  11 SNOW
    """
    opts = opts or {}
    mask_shadow = opts.get("mask_shadow", True)
    mask_snow = opts.get("mask_snow", False)
    bad_classes = [0, 1, 8, 9, 10]
    if mask_shadow:
        bad_classes.append(3)
    if mask_snow:
        bad_classes.append(11)

    def _apply(img: ee.Image) -> ee.Image:
        scl = img.select("SCL")
        valid = scl.remap(bad_classes, [0] * len(bad_classes), 1)
        return img.updateMask(valid)

    return _apply


def landsat_qa_mask(opts: dict[str, bool] | None = None) -> Callable[[ee.Image], ee.Image]:
    """Landsat C2 L2 QA_PIXEL mask.

    QA_PIXEL bit layout (C02):
      0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow, 5 snow, 6 clear, 7 water
    Also flags Landsat-7 SLC-off gaps via the fill bit (0).
    """
    opts = opts or {}
    mask_shadow = opts.get("mask_shadow", True)
    mask_snow = opts.get("mask_snow", False)

    def _apply(img: ee.Image) -> ee.Image:
        qa = img.select("QA_PIXEL")
        fill = qa.bitwiseAnd(1 << 0).neq(0)
        dilated_cloud = qa.bitwiseAnd(1 << 1).neq(0)
        cirrus = qa.bitwiseAnd(1 << 2).neq(0)
        cloud = qa.bitwiseAnd(1 << 3).neq(0)
        bad = fill.Or(dilated_cloud).Or(cirrus).Or(cloud)
        if mask_shadow:
            bad = bad.Or(qa.bitwiseAnd(1 << 4).neq(0))
        if mask_snow:
            bad = bad.Or(qa.bitwiseAnd(1 << 5).neq(0))
        return img.updateMask(bad.Not())

    return _apply


_PROFILES: dict[str, Callable[..., Callable[[ee.Image], ee.Image]]] = {
    "s2_scl_mask": s2_scl_mask,
    "landsat_qa_mask": landsat_qa_mask,
}


def get(name: str, opts: dict[str, bool] | None = None) -> Callable[[ee.Image], ee.Image]:
    if name not in _PROFILES:
        raise KeyError(f"Unknown cloud mask profile: {name!r}")
    return _PROFILES[name](opts)
