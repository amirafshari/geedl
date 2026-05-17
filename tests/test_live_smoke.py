"""Opt-in end-to-end smoke tests against real Earth Engine.

Run with: pytest tests/test_live_smoke.py --live

Skipped by default. Each test downloads one tiny tile (~64×64 px) for a single
window over a small, known-good ROI, then asserts the output GeoTIFF exists,
has the right band count, and leaves no .tmp file behind.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import ee
import pytest

import geedl.indices.optical  # noqa: F401
import geedl.indices.sar  # noqa: F401
from geedl.datasets.registry import get as get_dataset
from geedl.io.writer import write_tile
from geedl.pipeline.compositor import build_window_image
from geedl.pipeline.downloader import download_tile
from geedl.utils.windows import Window

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ee_initialized() -> None:
    project = os.environ.get("GEEDL_TEST_EE_PROJECT")
    if not project:
        pytest.skip("Set GEEDL_TEST_EE_PROJECT to run live tests.")
    ee.Initialize(project=project)


# (slug, window) — small ranges chosen for likely scene coverage.
DATASETS = [
    ("sentinel-2", Window(date(2023, 6, 1), date(2023, 6, 30), "2023-06")),
    ("sentinel-1", Window(date(2023, 6, 1), date(2023, 6, 30), "2023-06")),
    ("landsat-8", Window(date(2023, 6, 1), date(2023, 7, 31), "2023-06")),
    ("landsat-9", Window(date(2023, 6, 1), date(2023, 7, 31), "2023-06")),
    ("landsat-7", Window(date(2002, 6, 1), date(2002, 7, 31), "2002-06")),
]


@pytest.mark.parametrize("slug,window", DATASETS)
def test_live_tile_download(
    ee_initialized: None,  # noqa: ARG001
    slug: str,
    window: Window,
    tmp_path: Path,
) -> None:
    from geedl.config import DatasetConfig

    spec = get_dataset(slug)
    band_names = spec.band_names()[:2]  # keep payload small
    dataset_cfg = DatasetConfig.model_validate({
        "name": slug,
        "bands": {"select": band_names},
        "cloud_mask": {"enabled": False},
    })

    # Tiny ROI: ~640 m square in central UK (S2 grid covers this well).
    pt_lon, pt_lat = -1.0, 52.0
    roi = ee.Geometry.Rectangle([pt_lon, pt_lat, pt_lon + 0.01, pt_lat + 0.01])
    roi_fc = ee.FeatureCollection([ee.Feature(roi)])

    image, ordered_bands = build_window_image(
        dataset_cfg, spec, "median", window, roi_fc,
    )

    # 64×64 tile in EPSG:3857 (Web Mercator) at native_res.
    scale = float(spec.native_res)
    # Project the lon/lat to mercator via EE-side hint: use centroid.
    cx_m = pt_lon * 111_320 * pytest.approx(1.0).expected  # rough mercator x
    cy_m = pt_lat * 111_320
    width = height = 64
    affine = (scale, 0.0, cx_m, 0.0, -scale, cy_m + height * scale)

    arr = download_tile(
        image,
        bands=ordered_bands,
        epsg=3857,
        affine=affine,
        width_px=width,
        height_px=height,
    )
    assert arr.shape == (len(ordered_bands), height, width)

    out = tmp_path / f"{slug}.tif"
    from rasterio.transform import Affine

    write_tile(
        arr,
        output_path=out,
        transform=Affine(*affine),
        crs="EPSG:3857",
        band_names=ordered_bands,
        fmt="GeoTIFF",
    )
    assert out.exists()
    assert not out.with_suffix(".tif.tmp").exists()
