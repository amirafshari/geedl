"""Earth Engine asset upload lifecycle."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import ee
import geopandas as gpd

log = logging.getLogger(__name__)


class AssetUploadError(RuntimeError):
    pass


def shapefile_hash(source_path: str | Path) -> str:
    """SHA1 of the raw bytes of the ROI source file."""
    return hashlib.sha1(Path(source_path).read_bytes()).hexdigest()


def asset_id_for(base_path: str, source_path: str | Path) -> str:
    return f"{base_path}/roi_{shapefile_hash(source_path)[:10]}"


def asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def _gdf_to_feature_collection(gdf: gpd.GeoDataFrame) -> ee.FeatureCollection:
    features: list[ee.Feature] = []
    gdf_wgs = gdf.to_crs(4326)
    for idx, row in gdf_wgs.iterrows():
        geom = ee.Geometry(row.geometry.__geo_interface__)
        props = {k: v for k, v in row.items() if k != "geometry"}
        features.append(ee.Feature(geom, props).set("_fid", int(idx) if isinstance(idx, int) else str(idx)))
    return ee.FeatureCollection(features)


def upload_roi_asset(
    gdf: gpd.GeoDataFrame,
    asset_id: str,
    *,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
) -> str:
    """Upload `gdf` as an EE FeatureCollection asset. Blocks until COMPLETED.

    If the asset already exists this is a no-op that returns `asset_id`.
    """
    if asset_exists(asset_id):
        log.info("Reusing existing ROI asset: %s", asset_id)
        return asset_id

    fc = _gdf_to_feature_collection(gdf)
    task = ee.batch.Export.table.toAsset(
        collection=fc,
        description=f"geedl_roi_{asset_id.rsplit('/', 1)[-1]}",
        assetId=asset_id,
    )
    task.start()

    deadline = time.monotonic() + timeout
    while True:
        status = task.status()
        state = status.get("state")
        if state == "COMPLETED":
            log.info("ROI asset uploaded: %s", asset_id)
            return asset_id
        if state == "FAILED":
            raise AssetUploadError(f"asset upload failed: {status.get('error_message')}")
        if state == "CANCELLED":
            raise AssetUploadError(f"asset upload cancelled: {asset_id}")
        if time.monotonic() > deadline:
            raise AssetUploadError(f"asset upload timed out after {timeout:.0f}s")
        time.sleep(poll_interval)


def delete_asset(asset_id: str) -> None:
    try:
        ee.data.deleteAsset(asset_id)
    except ee.EEException as exc:
        log.warning("Failed to delete asset %s: %s", asset_id, exc)
