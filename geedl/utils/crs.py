"""CRS helpers — auto-UTM from centroid."""

from __future__ import annotations


def utm_epsg_from_lonlat(lon: float, lat: float) -> int:
    """Return the EPSG code of the UTM zone containing (lon, lat).

    Northern hemisphere: 32601–32660. Southern: 32701–32760.
    """
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude out of range: {lon}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude out of range: {lat}")
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone
