"""Cloud mask profiles. Mocks ee.Image — verifies the right bits/classes are referenced."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from geedl.datasets import cloud_masks


def _mock_image_for_bits() -> tuple[MagicMock, MagicMock]:
    """Return (image, band) where band tracks bitwiseAnd / remap calls."""
    band = MagicMock(name="band")
    band.bitwiseAnd.return_value = band
    band.neq.return_value = band
    band.Or.return_value = band
    band.Not.return_value = band
    band.remap.return_value = band
    img = MagicMock(name="ee.Image")
    img.select.return_value = band
    img.updateMask.return_value = img
    return img, band


def test_get_unknown_profile_raises() -> None:
    with pytest.raises(KeyError):
        cloud_masks.get("not_a_profile")


def test_s2_scl_default_masks_cloud_and_shadow() -> None:
    img, band = _mock_image_for_bits()
    fn = cloud_masks.get("s2_scl_mask")
    fn(img)
    img.select.assert_called_once_with("SCL")
    # remap should have been called once, with bad-class list including shadow(3).
    args = band.remap.call_args[0]
    bad_classes = args[0]
    assert 3 in bad_classes  # cloud shadow masked by default
    assert 8 in bad_classes and 9 in bad_classes  # cloud med + cloud high
    assert 11 not in bad_classes  # snow NOT masked by default
    img.updateMask.assert_called_once()


def test_s2_scl_optional_snow_mask() -> None:
    img, band = _mock_image_for_bits()
    fn = cloud_masks.get("s2_scl_mask", {"mask_snow": True})
    fn(img)
    bad_classes = band.remap.call_args[0][0]
    assert 11 in bad_classes


def test_s2_scl_disable_shadow() -> None:
    img, band = _mock_image_for_bits()
    fn = cloud_masks.get("s2_scl_mask", {"mask_shadow": False})
    fn(img)
    bad_classes = band.remap.call_args[0][0]
    assert 3 not in bad_classes


def test_landsat_qa_mask_default() -> None:
    img, band = _mock_image_for_bits()
    fn = cloud_masks.get("landsat_qa_mask")
    fn(img)
    img.select.assert_called_once_with("QA_PIXEL")
    # We expect bitwiseAnd called with masks for fill(0), dilated(1), cirrus(2),
    # cloud(3), shadow(4) — five bits by default. Snow(5) excluded.
    called_masks = [c[0][0] for c in band.bitwiseAnd.call_args_list]
    assert 1 << 0 in called_masks  # fill (SLC-off coverage)
    assert 1 << 3 in called_masks  # cloud
    assert 1 << 4 in called_masks  # shadow (default on)
    assert 1 << 5 not in called_masks  # snow (default off)


def test_landsat_qa_snow_when_enabled() -> None:
    img, band = _mock_image_for_bits()
    fn = cloud_masks.get("landsat_qa_mask", {"mask_snow": True})
    fn(img)
    called_masks = [c[0][0] for c in band.bitwiseAnd.call_args_list]
    assert 1 << 5 in called_masks
