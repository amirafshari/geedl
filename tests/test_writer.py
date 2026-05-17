"""Atomic GeoTIFF/COG writer.

Verifies the .tmp.tif → rename atomicity contract and that a crash mid-write
never leaves a corrupt final file at the output path.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
from shapely.geometry import box

from geedl.io import writer


def _array(bands: int = 3, h: int = 32, w: int = 32) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.random((bands, h, w), dtype=np.float32)


def _transform() -> Affine:
    # 10 m pixels, origin (0, 320).
    return Affine(10.0, 0.0, 0.0, 0.0, -10.0, 320.0)


def test_writes_geotiff_with_band_names(tmp_path: Path) -> None:
    out = tmp_path / "tile.tif"
    arr = _array(3)
    writer.write_tile(
        arr,
        output_path=out,
        transform=_transform(),
        crs="EPSG:32630",
        band_names=["B1", "B2", "B3"],
        fmt="GeoTIFF",
    )
    assert out.exists()
    assert not out.with_suffix(".tif.tmp").exists()
    with rasterio.open(out) as src:
        assert src.count == 3
        assert list(src.descriptions) == ["B1", "B2", "B3"]
        assert src.crs.to_string() == "EPSG:32630"


def test_cog_builds_overviews(tmp_path: Path) -> None:
    out = tmp_path / "cog.tif"
    writer.write_tile(
        _array(2, 64, 64),
        output_path=out,
        transform=_transform(),
        crs="EPSG:32630",
        band_names=["B1", "B2"],
        fmt="COG",
    )
    with rasterio.open(out) as src:
        assert src.overviews(1), "COG must have overviews on band 1"


def test_rename_failure_leaves_no_corrupt_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "tile.tif"

    def boom(src, dst):  # noqa: ANN001
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        writer.write_tile(
            _array(2),
            output_path=out,
            transform=_transform(),
            crs="EPSG:32630",
            band_names=["B1", "B2"],
            fmt="GeoTIFF",
        )
    # Final path is empty; only the .tmp may exist.
    assert not out.exists(), "final path must not be created if rename failed"


def test_band_name_count_mismatch_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="band_names length"):
        writer.write_tile(
            _array(2),
            output_path=tmp_path / "x.tif",
            transform=_transform(),
            crs="EPSG:32630",
            band_names=["only_one"],
            fmt="GeoTIFF",
        )


def test_overlap_px_crops_array(tmp_path: Path) -> None:
    out = tmp_path / "tile.tif"
    writer.write_tile(
        _array(1, 32, 32),
        output_path=out,
        transform=_transform(),
        crs="EPSG:32630",
        band_names=["B"],
        fmt="GeoTIFF",
        overlap_px=4,
    )
    with rasterio.open(out) as src:
        assert src.width == 32 - 2 * 4
        assert src.height == 32 - 2 * 4


def test_mask_geom_applies_nodata_outside(tmp_path: Path) -> None:
    out = tmp_path / "tile.tif"
    transform = _transform()
    # Mask to a small box inside the tile — pixels outside become nodata.
    mask = box(50, 50, 150, 150)
    writer.write_tile(
        np.ones((1, 32, 32), dtype=np.float32),
        output_path=out,
        transform=transform,
        crs="EPSG:32630",
        band_names=["B"],
        nodata=-9999.0,
        fmt="GeoTIFF",
        mask_geom=mask,
    )
    with rasterio.open(out) as src:
        data = src.read(1)
        assert (data == -9999.0).any()
        assert (data == 1.0).any()
