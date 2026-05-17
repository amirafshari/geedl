"""Dataset registry loader. Read-only at runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_REGISTRY_PATH = Path(__file__).parent / "registry.yaml"


@dataclass(frozen=True)
class BandSpec:
    name: str
    desc: str
    res: int
    scaled: bool = True
    internal: bool = False


@dataclass(frozen=True)
class DatasetSpec:
    slug: str
    collection: str
    bands: dict[str, BandSpec]
    native_res: int
    cloud_mask: str | None
    scale_factor: float | None
    offset: float
    date_property: str
    slc_off_date: date | None
    slc_off_coverage_loss: float | None = None
    extra_filters: list[dict[str, Any]] = field(default_factory=list)
    composite_strategy_override: str | None = None

    def band_names(self, include_internal: bool = False) -> list[str]:
        return [n for n, b in self.bands.items() if include_internal or not b.internal]


def _parse_entry(slug: str, raw: dict[str, Any]) -> DatasetSpec:
    bands = {
        name: BandSpec(
            name=name,
            desc=spec["desc"],
            res=int(spec["res"]),
            scaled=bool(spec.get("scaled", True)),
            internal=bool(spec.get("internal", False)),
        )
        for name, spec in raw["bands"].items()
    }
    slc_off_raw = raw.get("slc_off_date")
    slc_off = date.fromisoformat(slc_off_raw) if slc_off_raw else None
    return DatasetSpec(
        slug=slug,
        collection=raw["collection"],
        bands=bands,
        native_res=int(raw["native_res"]),
        cloud_mask=raw.get("cloud_mask"),
        scale_factor=raw.get("scale_factor"),
        offset=float(raw.get("offset", 0.0)),
        date_property=raw.get("date_property", "system:time_start"),
        slc_off_date=slc_off,
        slc_off_coverage_loss=raw.get("slc_off_coverage_loss"),
        extra_filters=list(raw.get("extra_filters") or []),
        composite_strategy_override=raw.get("composite_strategy_override"),
    )


@lru_cache(maxsize=1)
def _load() -> dict[str, DatasetSpec]:
    raw = yaml.safe_load(_REGISTRY_PATH.read_text())
    return {slug: _parse_entry(slug, entry) for slug, entry in raw.items()}


def get(slug: str) -> DatasetSpec:
    """Look up a dataset by slug. Raises KeyError if unknown."""
    registry = _load()
    if slug not in registry:
        known = ", ".join(sorted(registry.keys()))
        raise KeyError(f"Unknown dataset {slug!r}. Known: {known}")
    return registry[slug]


def list_slugs() -> list[str]:
    return sorted(_load().keys())
