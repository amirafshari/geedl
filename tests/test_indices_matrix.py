"""Indices × datasets compatibility matrix.

For every (index, dataset) advertised in the @index decorator, assert:
  - apply_indices succeeds and calls addBands once.
  - For datasets not in the index's whitelist, apply_indices raises.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import geedl.indices.optical  # noqa: F401 — register
import geedl.indices.sar  # noqa: F401 — register
from geedl.indices import _REGISTRY, apply_indices
from geedl.indices.optical import BAND_MAP
from geedl.datasets.registry import list_slugs


def _mock_image() -> MagicMock:
    img = MagicMock(name="ee.Image")
    for attr in (
        "select", "normalizedDifference", "expression", "rename",
        "addBands", "multiply", "subtract", "add",
    ):
        getattr(img, attr).return_value = img
    return img


_all_datasets = list_slugs()
_supported_pairs = [
    (name, ds)
    for name, entry in _REGISTRY.items()
    for ds in (entry["datasets"] or _all_datasets)
]
_unsupported_pairs = [
    (name, ds)
    for name, entry in _REGISTRY.items()
    if entry["datasets"] is not None
    for ds in _all_datasets
    if ds not in entry["datasets"]
]


@pytest.mark.parametrize("index_name,dataset", _supported_pairs)
def test_index_applies_to_advertised_dataset(index_name: str, dataset: str) -> None:
    img = _mock_image()
    out = apply_indices(img, [index_name], dataset)
    assert out is img
    img.addBands.assert_called_once()


@pytest.mark.parametrize("index_name,dataset", _unsupported_pairs)
def test_index_rejects_unsupported_dataset(index_name: str, dataset: str) -> None:
    with pytest.raises(ValueError, match="not supported"):
        apply_indices(_mock_image(), [index_name], dataset)


def test_band_map_covers_every_optical_dataset() -> None:
    # Every optical dataset in the registry must have a BAND_MAP entry,
    # otherwise indices referring to it would silently KeyError at runtime.
    optical = [d for d in _all_datasets if d.startswith(("sentinel-2", "landsat-"))]
    for ds in optical:
        assert ds in BAND_MAP, f"{ds!r} missing from BAND_MAP"
        # Required generic aliases for the indices we ship.
        for alias in ("nir", "red", "green", "blue", "swir1", "swir2"):
            assert alias in BAND_MAP[ds]
