"""Pixel budget calculator tests."""

from __future__ import annotations

import pytest

from geedl.utils.budget import safe_tile_side_m, safe_tile_side_px


def test_more_bands_smaller_tile():
    a = safe_tile_side_px(n_bands=4)
    b = safe_tile_side_px(n_bands=16)
    assert a > b


def test_tile_fits_budget():
    n_bands = 6
    side = safe_tile_side_px(n_bands)
    pixels = side * side
    bytes_used = pixels * n_bands * 4
    # Must be under the budget after headroom.
    assert bytes_used <= 40_000_000


def test_resolution_scales_metres():
    a = safe_tile_side_m(n_bands=4, resolution_m=10)
    b = safe_tile_side_m(n_bands=4, resolution_m=30)
    assert b > a


def test_zero_bands_rejected():
    with pytest.raises(ValueError):
        safe_tile_side_px(n_bands=0)
