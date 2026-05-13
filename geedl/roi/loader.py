"""Shapefile loader. Reads ROI source files into a GeoDataFrame, reprojects to UTM."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from ..utils.crs import utm_epsg_from_lonlat


def load_roi(
    path: str | Path,
    layer: str | None = None,
    feature_mode: str = "union",
    filter_expr: str | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Load the ROI source, optionally filter/split, and reproject to auto-UTM.

    Returns the projected GeoDataFrame and the chosen UTM EPSG.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ROI source not found: {p}")

    read_kwargs: dict[str, object] = {}
    if layer is not None:
        read_kwargs["layer"] = layer
    gdf = gpd.read_file(p, **read_kwargs)

    if gdf.empty:
        raise ValueError(f"ROI source {p} contains no features")

    if gdf.crs is None:
        raise ValueError(f"ROI source {p} has no CRS — please set one explicitly")

    if feature_mode == "filter":
        if not filter_expr:
            raise ValueError("feature_mode='filter' requires filter_expr")
        gdf = gdf.query(filter_expr)
        if gdf.empty:
            raise ValueError(f"filter_expr matched no features: {filter_expr!r}")
    elif feature_mode == "union":
        merged: BaseGeometry = gdf.unary_union
        gdf = gpd.GeoDataFrame({"geometry": [merged]}, crs=gdf.crs)
    elif feature_mode == "split":
        pass  # keep features individually
    else:
        raise ValueError(f"Unknown feature_mode: {feature_mode!r}")

    centroid = gdf.to_crs(4326).geometry.unary_union.centroid
    epsg = utm_epsg_from_lonlat(centroid.x, centroid.y)
    return gdf.to_crs(epsg), epsg
