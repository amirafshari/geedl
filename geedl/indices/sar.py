"""SAR (Sentinel-1) indices."""

from __future__ import annotations

import ee

from . import index


@index("RVI", datasets=["sentinel-1"])
def rvi(img: ee.Image, ds: str) -> ee.Image:
    return img.expression(
        "4*VH/(VV+VH)",
        {"VV": img.select("VV"), "VH": img.select("VH")},
    ).rename("RVI")


@index("VV_VH_RATIO", datasets=["sentinel-1"])
def vv_vh_ratio(img: ee.Image, ds: str) -> ee.Image:
    return img.select("VV").subtract(img.select("VH")).rename("VV_VH_RATIO")
