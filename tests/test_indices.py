"""Indices registry contract tests. Use a mock ee.Image — no live EE calls."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import geedl.indices.optical  # noqa: F401 — register
import geedl.indices.sar  # noqa: F401 — register
from geedl.indices import _REGISTRY, apply_indices, list_indices, supports


def _mock_image() -> MagicMock:
    img = MagicMock(name="ee.Image")
    img.select.return_value = img
    img.normalizedDifference.return_value = img
    img.expression.return_value = img
    img.rename.return_value = img
    img.addBands.return_value = img
    img.multiply.return_value = img
    img.subtract.return_value = img
    img.add.return_value = img
    return img


def test_ndvi_registered_for_optical():
    for ds in ("sentinel-2", "landsat-7", "landsat-8", "landsat-9"):
        assert supports("NDVI", ds)
    assert not supports("NDVI", "sentinel-1")


def test_rvi_only_sentinel1():
    assert supports("RVI", "sentinel-1")
    assert not supports("RVI", "sentinel-2")


def test_apply_unknown_index_raises():
    with pytest.raises(ValueError, match="not registered"):
        apply_indices(_mock_image(), ["NOT_A_REAL_INDEX"], "sentinel-2")


def test_apply_wrong_dataset_raises():
    with pytest.raises(ValueError, match="not supported"):
        apply_indices(_mock_image(), ["RVI"], "sentinel-2")


def test_apply_chains_addbands():
    img = _mock_image()
    out = apply_indices(img, ["NDVI", "NDWI"], "sentinel-2")
    assert out is img
    assert img.addBands.call_count == 2


def test_list_indices_filtering():
    s2 = set(list_indices("sentinel-2"))
    s1 = set(list_indices("sentinel-1"))
    l7 = set(list_indices("landsat-7"))
    assert "NDVI" in s2 and "EVI" in s2 and "RVI" not in s2
    assert "RVI" in s1 and "NDVI" not in s1
    # EVI / BSI excluded for landsat-7 (uses SR_B1 blue with different rescaling intent)
    assert "EVI" not in l7
    assert "NDVI" in l7


def test_duplicate_registration_blocked():
    from geedl.indices import index
    existing = next(iter(_REGISTRY))
    with pytest.raises(ValueError, match="already registered"):
        @index(existing)
        def _dup(img, ds):  # pragma: no cover
            return img
