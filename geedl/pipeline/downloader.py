"""Wrapper around ee.data.computePixels — direct pixels, no GCS/Drive."""

from __future__ import annotations

import io
import logging
from typing import Any

import ee
import numpy as np

log = logging.getLogger(__name__)


class EmptyTileError(RuntimeError):
    pass


class TileShapeError(RuntimeError):
    pass


def _structured_to_3d(arr: np.ndarray, bands: list[str]) -> np.ndarray:
    """Convert ee.data NPY (a structured array with one field per band) into (B, H, W)."""
    if arr.dtype.names is None:
        if arr.ndim == 2:
            return arr[np.newaxis, ...]
        if arr.ndim == 3:
            return arr
        raise TileShapeError(f"unexpected ndarray ndim {arr.ndim}")
    out = np.stack([arr[name] for name in bands], axis=0)
    return out


def download_tile(
    image: ee.Image,
    *,
    bands: list[str],
    epsg: int,
    affine: tuple[float, float, float, float, float, float],
    width_px: int,
    height_px: int,
) -> np.ndarray:
    """Synchronous EE pixel download.

    `affine` is (scaleX, shearX, translateX, shearY, scaleY, translateY).
    Returns array of shape (n_bands, height, width).
    """
    sx, shx, tx, shy, sy, ty = affine
    params: dict[str, Any] = {
        "expression": image,
        "fileFormat": "NPY",
        "bandIds": bands,
        "grid": {
            "crsCode": f"EPSG:{epsg}",
            "affineTransform": {
                "scaleX": sx,
                "shearX": shx,
                "translateX": tx,
                "shearY": shy,
                "scaleY": sy,
                "translateY": ty,
            },
            "dimensions": {"width": width_px, "height": height_px},
        },
    }
    raw = ee.data.computePixels(params)
    arr = np.load(io.BytesIO(raw))
    arr3d = _structured_to_3d(arr, bands)
    if arr3d.shape[1:] != (height_px, width_px):
        raise TileShapeError(
            f"got shape {arr3d.shape}, expected (*, {height_px}, {width_px})"
        )
    return arr3d
