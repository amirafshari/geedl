"""Pixel budget calculator — back-calculates a safe tile size."""

from __future__ import annotations

# EE computePixels caps output at ~48 MB. Large ROIs that span multiple UTM
# zones trigger up to 2.25x internal reprojection oversampling, so the visible
# request size can be ~2.25x what our output grid implies. Budget is sized to
# stay safe under that worst case: 20 MB * 0.8 headroom = 16 MB target,
# x 2.25 = 36 MB << 48 MB cap.
BUDGET_BYTES = 20_000_000
HEADROOM = 0.80


def safe_tile_side_px(n_bands: int, bytes_per_pixel: int = 4) -> int:
    """Side length, in pixels, of a square tile that fits inside the budget."""
    if n_bands <= 0:
        raise ValueError("n_bands must be > 0")
    safe_pixels = (BUDGET_BYTES / (n_bands * bytes_per_pixel)) * HEADROOM
    return int(safe_pixels**0.5)


def safe_tile_side_m(n_bands: int, resolution_m: float, bytes_per_pixel: int = 4) -> float:
    """Side length, in metres, of a square tile that fits inside the budget."""
    return safe_tile_side_px(n_bands, bytes_per_pixel) * resolution_m
