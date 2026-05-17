# geedl — Google Earth Engine Downloader

> **Download satellite imagery from Google Earth Engine directly to your local disk.**
> No Google Cloud Storage. No Google Drive. No export tasks.
> Resumable, crash-safe, fully YAML-driven.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`geedl` is a high-throughput, local-first command-line tool for downloading
**Sentinel-1, Sentinel-2, Landsat 7, Landsat 8, and Landsat 9** imagery from
Google Earth Engine. Point it at a shapefile and a date range — it tiles your
ROI, composites scenes, computes spectral indices (NDVI, EVI, NDWI, NBR, RVI…),
and writes **Cloud-Optimized GeoTIFFs** straight to your machine.

---

## Why geedl?

If you've ever tried to download Earth Engine imagery for a large area, you
know the pain: export tasks that take hours, files trapped in Google Drive,
Cloud Storage buckets you have to pay for, and no way to resume when something
fails. **geedl skips all of that.**

| | Traditional EE export | **geedl** |
|---|---|---|
| Destination | Google Drive / GCS bucket | **Local disk** |
| Throughput | Single export task | **Parallel async tiles (default 16)** |
| Resume after crash | Re-export from scratch | **SQLite checkpoint — pick up exactly where you stopped** |
| Tile size tuning | Manual | **Auto-calculated from pixel budget** |
| Output format | GeoTIFF | **Cloud-Optimized GeoTIFF + STAC sidecar + GeoParquet catalog** |
| Configuration | Python script per job | **One YAML file** |

---

## Features

- **Direct download from Earth Engine** via `ee.data.computePixels()` — no GCS, no Drive.
- **Shapefile ROI support** — auto-projects to UTM, simplifies for upload, tiles intelligently.
- **Smart tiling** — classifies tiles as `inside`, `partial`, or `outside`; skips empty space; orders by **Hilbert curve** for cache-warm EE requests.
- **Time-windowed compositing** — fixed-day, calendar-month, calendar-year, full-range, or single-scene modes.
- **Spectral indices** — built-in NDVI, EVI, NDWI, NDMI, NBR, NDSI, SAVI, BSI, RVI, VV/VH ratio. Add your own with one decorated function.
- **Crash-safe & resumable** — every tile is checkpointed; atomic writes (`.tmp` → `os.rename`) guarantee no corrupt files on disk.
- **Cloud masking** built in — Sentinel-2 SCL, Landsat C2 `QA_PIXEL`. Cloud + shadow + snow toggles per job.
- **Landsat 7 SLC-off** handled by multi-temporal compositing — no focal blur, no broken indices.
- **COG output** — natively readable by QGIS, GDAL, stackstac, and STAC browsers.
- **AI-agent friendly** — the YAML config is the single source of truth. Swap datasets, indices, output shapes, or pipeline behavior without touching Python.

---

## Installation

`geedl` uses a **conda** environment for Python + system-level geospatial
libraries (GDAL, PROJ, GEOS) and **uv** for fast Python dependency resolution
inside that environment.

```bash
# 1. Create and activate the conda environment
conda create -n geedl python=3.12 -y
conda activate geedl

# 2. Install uv inside the env
conda install -c conda-forge uv -y

# 3. Install geedl with uv (editable)
uv pip install -e .
```

Or, with development tooling (pytest, ruff, mypy):

```bash
uv pip install -e ".[dev]"
```

You'll also need to authenticate with Earth Engine once:

```bash
earthengine authenticate
```

> Every subsequent shell session needs `conda activate geedl` before running
> the `geedl` CLI.

---

## Quick start

### 1. Write a config

Create `job.yaml`:

```yaml
job_name: tuscany_ndvi_q1_2023

roi:
  path: data/tuscany.shp

dataset:
  name: sentinel-2
  bands:
    select: [B2, B3, B4, B8]
  indices:
    - {name: NDVI}
    - {name: EVI}

date:
  start: "2023-01-01"
  end:   "2023-03-31"

composite:
  strategy: median
  window:
    type: fixed_days
    size: 30
    step: 30
    label_format: "%Y-%m-%d"

output:
  dir: ./output
  format: COG
  dtype: float32

asset:
  project: my-ee-project
  base_path: users/me/geedl_assets
```

### 2. Run it

```bash
geedl validate -c job.yaml   # check config (no EE calls)
geedl plan     -c job.yaml   # preview windows + tile count
geedl run      -c job.yaml   # download to ./output
```

### 3. Resume if interrupted

Just re-run the same command. Completed tiles are skipped automatically.

```bash
geedl run -c job.yaml                  # resume
geedl run -c job.yaml --retry-failed   # also retry tiles that failed
geedl status -c job.yaml               # check progress
```

---

## Usage

### Authentication

Two methods, selected in YAML:

```yaml
# Browser flow (default) — uses your `earthengine authenticate` credentials.
auth:
  method: browser

# Service account — for headless / CI use.
auth:
  method: service_account
  service_account_email: bot@my-proj.iam.gserviceaccount.com
  key_file: /etc/secrets/ee-key.json
```

### Per-sensor configs

**Sentinel-2 — monthly NDVI/EVI composites**

```yaml
dataset:
  name: sentinel-2
  bands: {select: [B2, B3, B4, B8, B11]}
  indices: [{name: NDVI}, {name: EVI}, {name: NDMI}]
  cloud_mask: {enabled: true, mask_shadow: true, mask_snow: false}
composite:
  strategy: median
  window: {type: calendar_month}
```

**Sentinel-1 — VV/VH backscatter mosaics**

```yaml
dataset:
  name: sentinel-1
  bands: {select: [VV, VH]}
  indices: [{name: RVI}]
composite:
  strategy: median   # ignored — S1 always forces mosaic (see CLAUDE.md §7)
  window: {type: fixed_days, size: 12, step: 12}
```

**Landsat 8/9 — quarterly composites**

```yaml
dataset:
  name: landsat-8
  bands: {select: [SR_B2, SR_B3, SR_B4, SR_B5, SR_B6, SR_B7]}
  indices: [{name: NDVI}, {name: NBR}, {name: SAVI}]
composite:
  strategy: median
  window: {type: fixed_days, size: 90, step: 90, anchor: center}
```

**Landsat 7 — SLC-off recovery via long compositing window**

```yaml
dataset:
  name: landsat-7
  bands: {select: [SR_B3, SR_B4, SR_B5]}
  indices: [{name: NDVI}]
  slc_off: {strategy: multi_temporal, min_scenes_warning: 5}
composite:
  strategy: median
  window: {type: calendar_year}   # wide enough to fill SLC gaps
```

### Tuning concurrency and tile size

```yaml
pipeline:
  concurrency: 16          # parallel async tiles
  max_retries: 6
  retry_base_delay: 1.0
  timeout_per_tile: 120
tiling:
  max_tile_bytes: null     # null = auto, derived from EE's 50 MB request budget
  overlap_px: 2            # request buffer to avoid seam artifacts
  skip_coverage_threshold: 0.05  # tiles <5% inside ROI are skipped
```

### Hooks

Run user code at three lifecycle points (format: `module.path:function_name`):

```yaml
hooks:
  pre_download: my_pkg.hooks:before_tile
  post_tile:    my_pkg.hooks:after_tile
  post_job:     my_pkg.hooks:on_finish
```

### Running tests

```bash
pytest                       # full unit + integration suite (~2s, no EE calls)
pytest --live                # also runs the opt-in EE smoke tests
                             #   requires: export GEEDL_TEST_EE_PROJECT=<your-proj>
pytest tests/test_indices_matrix.py -v   # one module
```

---

## Supported datasets

| Slug | Collection | Native resolution |
|---|---|---|
| `sentinel-2` | `COPERNICUS/S2_SR_HARMONIZED` | 10 m |
| `sentinel-1` | `COPERNICUS/S1_GRD` (IW, DESC) | 10 m |
| `landsat-7` | `LANDSAT/LE07/C02/T1_L2` | 30 m |
| `landsat-8` | `LANDSAT/LC08/C02/T1_L2` | 30 m |
| `landsat-9` | `LANDSAT/LC09/C02/T1_L2` | 30 m |

Add new datasets by editing `geedl/datasets/registry.yaml` — no Python changes required.

```bash
geedl datasets                       # list available datasets
geedl indices --dataset sentinel-2  # list compatible indices
```

---

## Spectral indices

Out of the box: **NDVI, NDWI, NDMI, NBR, NDSI, EVI, SAVI, BSI** (optical) and **RVI, VV/VH ratio** (SAR).

Adding a new index takes one function:

```python
# geedl/indices/optical.py
from . import index

@index("CIRE", datasets=["sentinel-2"])
def cire(img, ds):
    return img.expression("NIR/RED_EDGE - 1", {
        "NIR": img.select("B8"),
        "RED_EDGE": img.select("B5"),
    }).rename("CIRE")
```

Reference it from any YAML config — no other code changes needed.

---

## Output structure

```
output/
  sentinel-2/
    2023-01-01/
      tile_A00_2023-01-01.tif      # Cloud-Optimized GeoTIFF
      tile_A00_2023-01-01.json     # STAC Item sidecar
      tile_B01_2023-01-01.tif
      ...
    2023-02-01/
      ...
  catalog.parquet                   # GeoParquet spatial index of all tiles
  job.yaml                          # frozen copy of the config used
  checkpoint.db                     # SQLite resume state
```

Read the catalog back with any GeoParquet-aware tool:

```python
import geopandas as gpd
gdf = gpd.read_parquet("output/catalog.parquet")
gdf[gdf.datetime.str.startswith("2023-01")].plot()
```

---

## How it works

1. **ROI prep** — shapefile is loaded, auto-projected to UTM, simplified, and uploaded once as an EE asset (deterministic hash-based ID, so the same ROI is reused across runs).
2. **Tiling** — the bounding box is tiled into fixed-size squares whose dimensions are derived from EE's per-request pixel budget. Tiles outside the ROI are skipped; tiles on the edge are tagged `partial` and get both a server-side `img.clip()` and a local rasterio mask.
3. **Windowing** — the date range is split into compositing windows (fixed days, calendar months, etc.).
4. **Async download** — each (tile × window) is fetched concurrently via `ee.data.computePixels()` in NPY format. Failures are retried with exponential backoff + full jitter.
5. **Validation** — each array is checked for shape, all-nodata, and plausible value range before being written.
6. **Atomic write** — data is written to `{path}.tmp.tif`, internally tiled at 256×256, overviews are built, then `os.rename()` swaps it into place.
7. **Checkpoint** — only after the rename succeeds is the tile marked `done` in the SQLite checkpoint. Crash recovery resets `in_flight` tiles to `pending` and deletes any stragglers on the next launch.

See [`ARCH.md`](ARCH.md) for the full design rationale and decision log.

---

## CLI reference

```bash
geedl run        -c job.yaml [--fresh] [--retry-failed]   # run or resume
geedl validate   -c job.yaml                             # check config
geedl plan       -c job.yaml                             # dry-run preview
geedl status     -c job.yaml                             # tile counts
geedl datasets                                            # list datasets
geedl indices    --dataset sentinel-2                    # list indices
geedl cleanup    -c job.yaml                             # delete EE asset
```

---

## Project status

`geedl` v0.1 is **pre-1.0 software**. Core pipeline works end-to-end on the
listed datasets. Known gaps: single-process only, scene-mode (no compositing)
not yet wired in the runner, no GUI. See [`ARCH.md`](ARCH.md) §17 for the
full caveat list.

---

## Contributing

Issues and PRs welcome. The codebase has a strict layered dependency graph
(`utils → datasets → indices → io/roi → pipeline → cli`) and a plugin-only
index engine — see [`CLAUDE.md`](.claude/CLAUDE.md) for module contracts and
testing conventions before opening a PR.

---

## License

MIT
