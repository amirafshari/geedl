"""Per-tile integrity checks. Raise on hard failures, log on soft ones."""

from __future__ import annotations

import logging

import numpy as np

from .downloader import EmptyTileError, TileShapeError

log = logging.getLogger(__name__)


def validate_tile(
    array: np.ndarray,
    *,
    expected_shape: tuple[int, int, int],
    nodata: float,
    value_range: tuple[float, float] | None = None,
    tile_id: str = "?",
) -> None:
    if array.shape != expected_shape:
        raise TileShapeError(
            f"tile {tile_id}: shape {array.shape} != expected {expected_shape}"
        )
    is_nodata = np.isnan(array) | (array == nodata)
    if is_nodata.all():
        raise EmptyTileError(f"tile {tile_id}: all-nodata array")
    if value_range is not None:
        valid = array[~is_nodata]
        lo, hi = value_range
        if valid.size and (valid.min() < lo or valid.max() > hi):
            log.warning(
                "tile %s: values [%.3f, %.3f] outside expected range [%.3f, %.3f]",
                tile_id,
                float(valid.min()),
                float(valid.max()),
                lo,
                hi,
            )
