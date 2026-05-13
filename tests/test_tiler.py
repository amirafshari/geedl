"""Tests for tile classification and Hilbert ordering."""

from __future__ import annotations

from shapely.geometry import Polygon

from geedl.roi.tiler import _col_label, generate_tiles


def _square(side_m: float) -> Polygon:
    return Polygon([(0, 0), (side_m, 0), (side_m, side_m), (0, side_m)])


def test_inside_only_for_full_square():
    # 80 km square — large enough to contain multiple ~14 km tiles for 4 bands @ 10 m.
    roi = _square(80_000)
    tiles = generate_tiles(roi, resolution_m=10, n_bands=4, grid_snap_m=10)
    assert all(t.tile_class in ("inside", "partial") for t in tiles)
    assert any(t.tile_class == "inside" for t in tiles)


def test_partial_for_diagonal():
    diag = Polygon([(0, 0), (80_000, 0), (0, 80_000)])
    tiles = generate_tiles(diag, resolution_m=10, n_bands=4, grid_snap_m=10)
    classes = {t.tile_class for t in tiles}
    assert "partial" in classes
    assert all(c in ("inside", "partial") for c in classes)


def test_col_label_pattern():
    assert _col_label(0) == "A"
    assert _col_label(25) == "Z"
    assert _col_label(26) == "AA"
    assert _col_label(51) == "AZ"


def test_hilbert_order_is_total():
    roi = _square(80_000)
    tiles = generate_tiles(roi, resolution_m=10, n_bands=4, grid_snap_m=10)
    hs = [t.hilbert for t in tiles]
    assert hs == sorted(hs)


def test_skip_edge_tiles():
    # Thin sliver — boundary tiles should be classified as edge and skipped.
    sliver = Polygon([(0, 0), (200_000, 0), (200_000, 100), (0, 100)])
    tiles = generate_tiles(
        sliver, resolution_m=10, n_bands=4,
        grid_snap_m=10, skip_coverage_threshold=0.5,
    )
    assert all(t.coverage >= 0.5 for t in tiles)
