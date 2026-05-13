"""Pre-upload geometry simplification."""

from __future__ import annotations

import geopandas as gpd


def simplify_for_upload(
    gdf: gpd.GeoDataFrame,
    resolution_m: float,
    tolerance: float | str = "auto",
) -> gpd.GeoDataFrame:
    """Simplify geometries by 10% of resolution (or an explicit metre value).

    Sub-pixel precision is meaningless and inflates the EE asset.
    """
    if tolerance == "auto":
        tol_m = resolution_m * 0.1
    else:
        tol_m = float(tolerance)
    if tol_m <= 0:
        return gdf
    simplified = gdf.copy()
    simplified["geometry"] = simplified.geometry.simplify(tol_m, preserve_topology=True)
    return simplified
