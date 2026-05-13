"""Atomic GeoTIFF / COG writer with optional local rasterio mask."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Sequence

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)

_DTYPE_MAP = {"float32": "float32", "int16": "int16", "uint16": "uint16"}
_COG_BLOCK = 256


def _compression_kwargs(compression: str) -> dict[str, str]:
    if compression == "none":
        return {}
    return {"compress": compression}


def write_tile(
    array: np.ndarray,
    *,
    output_path: str | Path,
    transform: Affine,
    crs: str,
    band_names: Sequence[str],
    dtype: str = "float32",
    nodata: float = -9999.0,
    compression: str = "LZW",
    fmt: str = "COG",
    mask_geom: BaseGeometry | None = None,
    overlap_px: int = 0,
) -> Path:
    """Write a (bands, h, w) array atomically to `output_path`.

    Steps:
      1. write to {path}.tmp
      2. (COG) build overviews
      3. close handle
      4. os.rename(tmp, final)

    A crashed process leaves at most a `.tmp` file — never a corrupt final file.
    """
    final = Path(output_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + ".tmp")

    if array.ndim != 3:
        raise ValueError(f"expected (bands, h, w), got shape {array.shape}")
    n_bands, height, width = array.shape
    if len(band_names) != n_bands:
        raise ValueError(
            f"band_names length {len(band_names)} != n_bands {n_bands}"
        )

    out_array = array.astype(_DTYPE_MAP[dtype], copy=False)

    if overlap_px > 0:
        out_array = out_array[
            :, overlap_px : height - overlap_px, overlap_px : width - overlap_px
        ]
        transform = transform * Affine.translation(overlap_px, overlap_px)
        _, height, width = out_array.shape

    if mask_geom is not None:
        mask = geometry_mask(
            [mask_geom.__geo_interface__],
            out_shape=(height, width),
            transform=transform,
            invert=True,
        )
        out_array = np.where(mask, out_array, np.array(nodata, dtype=out_array.dtype))

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": n_bands,
        "dtype": _DTYPE_MAP[dtype],
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": _COG_BLOCK,
        "blockysize": _COG_BLOCK,
        "interleave": "pixel",
        **_compression_kwargs(compression),
    }

    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(out_array)
        for i, name in enumerate(band_names, start=1):
            dst.set_band_description(i, name)
        if fmt == "COG":
            factors = [2, 4, 8]
            dst.build_overviews(factors, Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")

    os.rename(tmp, final)
    return final
