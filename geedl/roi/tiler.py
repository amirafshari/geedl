"""Grid generation, tile classification, Hilbert ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry

from ..utils.budget import safe_tile_side_m

TileClass = Literal["inside", "partial", "edge", "outside"]


@dataclass(frozen=True)
class Tile:
    tile_id: str
    col: int
    row: int
    geom: Polygon
    request_geom: Polygon
    tile_class: TileClass
    coverage: float
    hilbert: int

    @property
    def grid_label(self) -> str:
        return f"{_col_label(self.col)}{self.row:02d}"


def _col_label(col: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA', etc."""
    out = ""
    n = col
    while True:
        out = chr(ord("A") + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            break
    return out


def _snap_down(x: float, step: float) -> float:
    return (x // step) * step


def _hilbert_d2xy_inverse(x: int, y: int, order: int) -> int:
    """Convert (x, y) to a 1-D Hilbert distance for a 2^order × 2^order grid."""
    rx = ry = 0
    d = 0
    s = 1 << (order - 1)
    while s > 0:
        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        s //= 2
    return d


def _classify(tile_geom: Polygon, roi: BaseGeometry, skip_threshold: float) -> tuple[TileClass, float]:
    corners = [Point(c) for c in tile_geom.exterior.coords[:4]]
    inside_corners = sum(roi.contains(c) for c in corners)
    centroid_inside = roi.contains(tile_geom.centroid)

    if inside_corners == 4:
        return "inside", 1.0
    if inside_corners == 0 and not centroid_inside and not tile_geom.intersects(roi):
        return "outside", 0.0

    inter = tile_geom.intersection(roi)
    coverage = inter.area / tile_geom.area if tile_geom.area > 0 else 0.0
    if coverage < skip_threshold:
        return "edge", coverage
    return "partial", coverage


def generate_tiles(
    roi: BaseGeometry,
    resolution_m: float,
    n_bands: int,
    *,
    overlap_px: int = 2,
    skip_coverage_threshold: float = 0.05,
    grid_snap_m: int = 100,
    max_tile_bytes: int | None = None,
) -> list[Tile]:
    """Generate the tile manifest for an ROI in a projected CRS (metres).

    All input geometries must be in the same projected CRS (auto-UTM).
    """
    if max_tile_bytes is not None:
        side_m = safe_tile_side_m(n_bands) * (max_tile_bytes / 40_000_000) ** 0.5
    else:
        side_m = safe_tile_side_m(n_bands, resolution_m)
    side_m = max(side_m, resolution_m * 32)  # never go below 32 px square

    side_px = int(round(side_m / resolution_m))
    side_m = side_px * resolution_m  # re-align to whole pixels

    minx, miny, maxx, maxy = roi.bounds
    minx = _snap_down(minx, grid_snap_m)
    miny = _snap_down(miny, grid_snap_m)

    cols = int(((maxx - minx) // side_m)) + 1
    rows = int(((maxy - miny) // side_m)) + 1

    overlap_m = overlap_px * resolution_m
    order = max(1, (max(cols, rows) - 1).bit_length())

    tiles: list[Tile] = []
    candidate_count = 0
    for r in range(rows):
        for c in range(cols):
            x0 = minx + c * side_m
            y0 = miny + r * side_m
            x1 = x0 + side_m
            y1 = y0 + side_m
            tile_geom = box(x0, y0, x1, y1)
            cls, cov = _classify(tile_geom, roi, skip_coverage_threshold)
            candidate_count += 1
            if cls in ("outside", "edge"):
                continue
            request_geom = box(
                x0 - overlap_m, y0 - overlap_m, x1 + overlap_m, y1 + overlap_m
            )
            h = _hilbert_d2xy_inverse(c, r, order)
            tiles.append(
                Tile(
                    tile_id=f"{_col_label(c)}{r:02d}",
                    col=c,
                    row=r,
                    geom=tile_geom,
                    request_geom=request_geom,
                    tile_class=cls,
                    coverage=cov,
                    hilbert=h,
                )
            )

    tiles.sort(key=lambda t: t.hilbert)
    return tiles
