"""Sanity-check every entry in registry.yaml.

Catches typos, missing fields, or a cloud_mask name that doesn't resolve
to a real profile function.
"""

from __future__ import annotations

import pytest

from geedl.datasets import cloud_masks
from geedl.datasets.registry import get, list_slugs


@pytest.mark.parametrize("slug", list_slugs())
def test_entry_has_required_fields(slug: str) -> None:
    spec = get(slug)
    assert spec.collection, f"{slug} missing collection"
    assert spec.bands, f"{slug} has no bands"
    assert spec.native_res > 0
    assert spec.date_property


@pytest.mark.parametrize("slug", list_slugs())
def test_cloud_mask_resolves_to_real_profile(slug: str) -> None:
    spec = get(slug)
    if spec.cloud_mask is None:
        return
    # If a profile is named, it must exist in cloud_masks.
    fn = cloud_masks.get(spec.cloud_mask)
    assert callable(fn)


def test_sentinel_1_has_mosaic_override() -> None:
    # Regression guard: see CLAUDE.md non-negotiable #7.
    assert get("sentinel-1").composite_strategy_override == "mosaic"


def test_landsat_7_has_slc_off_date() -> None:
    assert get("landsat-7").slc_off_date is not None


@pytest.mark.parametrize("slug", list_slugs())
def test_band_resolutions_positive(slug: str) -> None:
    for band in get(slug).bands.values():
        assert band.res > 0
        assert band.desc
