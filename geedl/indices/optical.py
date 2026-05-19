"""Optical spectral indices."""

from __future__ import annotations

import ee

from . import index

BAND_MAP: dict[str, dict[str, str]] = {
    "sentinel-2": {
        "nir": "B8", "red": "B4", "green": "B3", "blue": "B2",
        "swir1": "B11", "swir2": "B12",
    },
    "landsat-7": {
        "nir": "SR_B4", "red": "SR_B3", "green": "SR_B2", "blue": "SR_B1",
        "swir1": "SR_B5", "swir2": "SR_B7",
    },
    "landsat-8": {
        "nir": "SR_B5", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2",
        "swir1": "SR_B6", "swir2": "SR_B7",
    },
    "landsat-9": {
        "nir": "SR_B5", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2",
        "swir1": "SR_B6", "swir2": "SR_B7",
    },
}

_OPTICAL = ["sentinel-2", "landsat-7", "landsat-8", "landsat-9"]
_OPTICAL_NO_L7 = ["sentinel-2", "landsat-8", "landsat-9"]


@index("NDVI", datasets=_OPTICAL)
def ndvi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["nir"], b["red"]]).rename("NDVI")


@index("NDWI", datasets=_OPTICAL)
def ndwi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["green"], b["nir"]]).rename("NDWI")


@index("NDMI", datasets=_OPTICAL)
def ndmi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["nir"], b["swir1"]]).rename("NDMI")


@index("NBR", datasets=_OPTICAL)
def nbr(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["nir"], b["swir2"]]).rename("NBR")


@index("NDSI", datasets=_OPTICAL)
def ndsi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["green"], b["swir1"]]).rename("NDSI")


@index("EVI", datasets=_OPTICAL_NO_L7)
def evi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.expression(
        "2.5*(NIR-RED)/(NIR+6*RED-7.5*BLUE+1)",
        {
            "NIR": img.select(b["nir"]),
            "RED": img.select(b["red"]),
            "BLUE": img.select(b["blue"]),
        },
    ).rename("EVI")


@index("SAVI", datasets=_OPTICAL)
def savi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    L = 0.5
    return img.expression(
        "((NIR-RED)/(NIR+RED+L))*(1+L)",
        {"NIR": img.select(b["nir"]), "RED": img.select(b["red"]), "L": L},
    ).rename("SAVI")


@index("OSI", datasets=["sentinel-2"])
def osi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.expression(
        "(GREEN+RED)/BLUE",
        {
            "GREEN": img.select(b["green"]),
            "RED": img.select(b["red"]),
            "BLUE": img.select(b["blue"]),
        },
    ).rename("OSI")


@index("BSI", datasets=_OPTICAL_NO_L7)
def bsi(img: ee.Image, ds: str) -> ee.Image:
    b = BAND_MAP[ds]
    return img.expression(
        "(SWIR1+RED-NIR-BLUE)/(SWIR1+RED+NIR+BLUE)",
        {
            "SWIR1": img.select(b["swir1"]),
            "RED": img.select(b["red"]),
            "NIR": img.select(b["nir"]),
            "BLUE": img.select(b["blue"]),
        },
    ).rename("BSI")
