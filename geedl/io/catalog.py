"""STAC sidecars + spatial catalog parquet."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import pystac
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def write_stac_sidecar(
    *,
    tile_id: str,
    output_tif: Path,
    geometry: BaseGeometry,
    start: datetime,
    end: datetime,
    platform: str,
    gsd: float,
    bands: list[str],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a STAC Item JSON next to the GeoTIFF."""
    item = pystac.Item(
        id=tile_id,
        geometry=geometry.__geo_interface__,
        bbox=list(geometry.bounds),
        datetime=start,
        properties={
            "start_datetime": start.isoformat() + "Z",
            "end_datetime": end.isoformat() + "Z",
            "platform": platform,
            "gsd": gsd,
            "eo:bands": [{"name": b} for b in bands],
            **{f"geedl:{k}": v for k, v in (extra or {}).items()},
        },
    )
    item.add_asset(
        "data",
        pystac.Asset(
            href=output_tif.name,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
        ),
    )
    sidecar = output_tif.with_suffix(".json")
    sidecar.write_text(json.dumps(item.to_dict(), indent=2))
    return sidecar


def write_catalog_parquet(
    output_root: Path,
    rows: Iterable[dict[str, Any]],
) -> Path:
    """Aggregate all per-tile rows into output_root/catalog.parquet."""
    records = list(rows)
    if not records:
        raise ValueError("no rows to write to catalog.parquet")
    geoms = [shape(r.pop("geometry")) for r in records]
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=records[0].get("_crs", 4326))
    if "_crs" in gdf.columns:
        gdf = gdf.drop(columns=["_crs"])
    out = output_root / "catalog.parquet"
    gdf.to_parquet(out, index=False)
    return out
