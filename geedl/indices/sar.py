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


@index("WATER_S1", datasets=["sentinel-1-rtc"])
def water_s1(img: ee.Image, ds: str) -> ee.Image:
    # Open water is specular at C-band: both VV and VH collapse to low γ⁰.
    # Thresholds from OPERA DSWx-S1: VV < 0.02 (~-17 dB), VH < 0.0063 (~-22 dB).
    return (
        img.select("VV").lt(0.02)
        .And(img.select("VH").lt(0.0063))
        .rename("WATER_S1")
    )


@index("RGB_RATIO", datasets=["sentinel-1-rtc"])
def rgb_ratio(img: ee.Image, ds: str) -> ee.Image:
    # Copernicus Browser "RGB ratio" false-color on γ⁰ (linear): R=VV, G=VH, B=VH/VV.
    vv = img.select("VV")
    vh = img.select("VH")
    return ee.Image.cat([vv, vh, vh.divide(vv)]).rename(
        ["RGB_RATIO_R", "RGB_RATIO_G", "RGB_RATIO_B"]
    )


@index("SAR_URBAN", datasets=["sentinel-1-rtc"])
def sar_urban(img: ee.Image, ds: str) -> ee.Image:
    # Copernicus Browser "SAR Urban" on γ⁰ (linear): R=VV, G=2*VH, B=VV/VH/100.
    vv = img.select("VV")
    vh = img.select("VH")
    return ee.Image.cat(
        [vv, vh.multiply(2), vv.divide(vh).divide(100)]
    ).rename(["SAR_URBAN_R", "SAR_URBAN_G", "SAR_URBAN_B"])
