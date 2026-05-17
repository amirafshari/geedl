"""Per-tile array validation: hard fails for shape/empty, soft warning for range."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from geedl.pipeline.downloader import EmptyTileError, TileShapeError
from geedl.pipeline.validator import validate_tile


def _ok_array() -> np.ndarray:
    return np.full((2, 4, 4), 0.5, dtype=np.float32)


def test_passes_when_shape_and_data_ok() -> None:
    validate_tile(_ok_array(), expected_shape=(2, 4, 4), nodata=-9999.0)


def test_shape_mismatch_raises() -> None:
    arr = np.zeros((2, 4, 4), dtype=np.float32)
    with pytest.raises(TileShapeError):
        validate_tile(arr, expected_shape=(2, 4, 5), nodata=-9999.0, tile_id="A01")


def test_all_nodata_raises() -> None:
    arr = np.full((2, 4, 4), -9999.0, dtype=np.float32)
    with pytest.raises(EmptyTileError):
        validate_tile(arr, expected_shape=(2, 4, 4), nodata=-9999.0)


def test_all_nan_treated_as_nodata() -> None:
    arr = np.full((2, 4, 4), np.nan, dtype=np.float32)
    with pytest.raises(EmptyTileError):
        validate_tile(arr, expected_shape=(2, 4, 4), nodata=-9999.0)


def test_value_range_warning_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    arr = _ok_array()
    arr[0, 0, 0] = 10.0  # outside [-1, 1]
    with caplog.at_level(logging.WARNING, logger="geedl.pipeline.validator"):
        validate_tile(
            arr, expected_shape=(2, 4, 4), nodata=-9999.0,
            value_range=(-1.0, 1.0), tile_id="A01",
        )
    assert any("outside expected range" in r.message for r in caplog.records)
