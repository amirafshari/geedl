"""Spectral index registry. Plugin-only — every index is a decorated function."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import ee

IndexFn = Callable[["ee.Image", str], "ee.Image"]

_REGISTRY: dict[str, dict[str, Any]] = {}


def index(name: str, datasets: list[str] | None = None) -> Callable[[IndexFn], IndexFn]:
    """Register a spectral index function under `name`.

    If `datasets` is None the index is considered universally applicable.
    """

    def decorator(fn: IndexFn) -> IndexFn:
        if name in _REGISTRY:
            raise ValueError(f"index {name!r} already registered")
        _REGISTRY[name] = {"fn": fn, "datasets": datasets}
        return fn

    return decorator


def apply_indices(image: ee.Image, names: list[str], dataset: str) -> ee.Image:
    """Append each requested index as a new band on `image`. Order preserved."""
    for name in names:
        if name not in _REGISTRY:
            known = ", ".join(sorted(_REGISTRY.keys())) or "(none registered)"
            raise ValueError(f"Index {name!r} not registered. Known: {known}")
        entry = _REGISTRY[name]
        if entry["datasets"] is not None and dataset not in entry["datasets"]:
            raise ValueError(f"Index {name!r} not supported for dataset {dataset!r}")
        image = image.addBands(entry["fn"](image, dataset))
    return image


def supports(name: str, dataset: str) -> bool:
    if name not in _REGISTRY:
        return False
    ds = _REGISTRY[name]["datasets"]
    return ds is None or dataset in ds


def list_indices(dataset: str | None = None) -> list[str]:
    if dataset is None:
        return sorted(_REGISTRY.keys())
    return sorted(n for n in _REGISTRY if supports(n, dataset))
