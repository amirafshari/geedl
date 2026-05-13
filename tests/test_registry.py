"""Dataset registry loader tests."""

from __future__ import annotations

from datetime import date

import pytest

from geedl.datasets.registry import get, list_slugs


def test_known_slugs_present():
    slugs = list_slugs()
    for expected in ("sentinel-1", "sentinel-2", "landsat-7", "landsat-8", "landsat-9"):
        assert expected in slugs


def test_unknown_slug_raises():
    with pytest.raises(KeyError):
        get("not-a-real-dataset")


def test_sentinel_1_override():
    s1 = get("sentinel-1")
    assert s1.composite_strategy_override == "mosaic"
    assert s1.cloud_mask is None  # SAR is cloud-transparent


def test_landsat_7_slc_off_date_parsed():
    l7 = get("landsat-7")
    assert l7.slc_off_date == date(2003, 5, 31)
    assert l7.slc_off_coverage_loss == pytest.approx(0.22)


def test_sentinel_2_bands_and_res():
    s2 = get("sentinel-2")
    assert s2.native_res == 10
    assert "B2" in s2.bands and s2.bands["B2"].res == 10
    assert s2.scale_factor == pytest.approx(0.0001)
