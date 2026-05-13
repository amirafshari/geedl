"""Auto-UTM helper tests."""

from __future__ import annotations

import pytest

from geedl.utils.crs import utm_epsg_from_lonlat


def test_northern_zone():
    # London: ~ 0° E, 51° N → UTM 30N → 32630
    assert utm_epsg_from_lonlat(-0.1, 51.5) == 32630


def test_southern_zone():
    # Sydney: 151° E, -33° S → UTM 56S → 32756
    assert utm_epsg_from_lonlat(151.0, -33.0) == 32756


def test_equator_just_north():
    assert utm_epsg_from_lonlat(0, 0) == 32631


def test_invalid_lat():
    with pytest.raises(ValueError):
        utm_epsg_from_lonlat(0, 200)


def test_invalid_lon():
    with pytest.raises(ValueError):
        utm_epsg_from_lonlat(-500, 0)
