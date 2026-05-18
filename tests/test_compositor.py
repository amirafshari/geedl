"""Composite strategies + Sentinel-1 mosaic override.

Mocks ee.ImageCollection; asserts the correct reducer is invoked, and that
DatasetSpec.composite_strategy_override always wins over the config strategy.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from geedl.config import BandsConfig, DatasetConfig, IndexEntry
from geedl.datasets.registry import DatasetSpec, get
from geedl.pipeline.compositor import _resolve_band_order, composite


def _mock_col() -> MagicMock:
    col = MagicMock(name="ee.ImageCollection")
    col.median.return_value = MagicMock(name="median_img")
    col.mean.return_value = MagicMock(name="mean_img")
    col.mosaic.return_value = MagicMock(name="mosaic_img")
    col.first.return_value = MagicMock(name="first_img")
    return col


@pytest.mark.parametrize(
    "strategy,attr",
    [("median", "median"), ("mean", "mean"), ("mosaic", "mosaic"), ("none", "first")],
)
def test_strategies_dispatch_correctly(strategy: str, attr: str) -> None:
    col = _mock_col()
    spec = get("sentinel-2")  # no override
    composite(col, strategy, spec)
    getattr(col, attr).assert_called_once()


def test_sentinel_1_override_forces_mosaic() -> None:
    col = _mock_col()
    spec = get("sentinel-1")
    assert spec.composite_strategy_override == "mosaic"
    # Even if config asks for median, the override wins.
    composite(col, "median", spec)
    col.mosaic.assert_called_once()
    col.median.assert_not_called()


def test_unknown_strategy_raises() -> None:
    col = _mock_col()
    spec = get("sentinel-2")
    with pytest.raises(ValueError, match="Unknown composite strategy"):
        composite(col, "not_a_strategy", spec)


def test_resolve_band_order_select_none_uses_defaults() -> None:
    cfg = DatasetConfig(name="sentinel-2", indices=[IndexEntry(name="NDVI")])
    assert _resolve_band_order(cfg, ["B4", "B8"]) == ["B4", "B8", "NDVI"]


def test_resolve_band_order_select_empty_yields_indices_only() -> None:
    cfg = DatasetConfig(
        name="sentinel-2",
        bands=BandsConfig(select=[]),
        indices=[IndexEntry(name="NDVI")],
    )
    assert _resolve_band_order(cfg, []) == ["NDVI"]


def test_resolve_band_order_explicit_select_keeps_listed_bands() -> None:
    cfg = DatasetConfig(
        name="sentinel-2",
        bands=BandsConfig(select=["B4", "B8"]),
        indices=[IndexEntry(name="NDVI")],
    )
    assert _resolve_band_order(cfg, ["B4", "B8"]) == ["B4", "B8", "NDVI"]


def test_override_wins_for_every_strategy() -> None:
    spec_with_override = DatasetSpec(
        slug="x", collection="c", bands={}, native_res=10,
        cloud_mask=None, scale_factor=None, offset=0.0,
        date_property="t", slc_off_date=None,
        composite_strategy_override="mosaic",
    )
    for cfg_strategy in ("median", "mean", "none"):
        col = _mock_col()
        composite(col, cfg_strategy, spec_with_override)
        col.mosaic.assert_called_once()
