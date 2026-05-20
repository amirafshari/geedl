# Configuration

!!! info "Coming soon"
    Phase 3 of the docs rollout will auto-generate this page from the pydantic
    `JobConfig` schema, the dataset registry, and the `@index` registry.
    Until then, this is a short hand-written primer; the
    [README](https://github.com/amirafshari/geedl#usage) has the full field list.

A geedl job is one YAML file. The top-level sections are:

| Section | Purpose |
|---|---|
| `job_name` | Human-readable identifier; also used in output paths and the checkpoint DB. |
| `roi` | Where to download — shapefile path, optional layer / feature filter. |
| `dataset` | Which sensor, which bands, which indices, cloud masking. |
| `date` | Start / end (YYYY-MM-DD). |
| `composite` | Compositing strategy + time window definition. |
| `output` | Output directory, format, dtype, structure. |
| `tiling` | Tile size budget, overlap, skip threshold. |
| `pipeline` | Concurrency, retries, timeouts. |
| `asset` | Earth Engine project + asset base path. |
| `auth` | Browser vs service account. |
| `hooks` | Optional user-defined callbacks at lifecycle points. |

## Authentication

Two methods, selected in YAML:

```yaml
# Browser flow (default) — uses your `earthengine authenticate` credentials.
auth:
  method: browser
```

```yaml
# Service account — for headless / CI use.
auth:
  method: service_account
  service_account_email: bot@my-proj.iam.gserviceaccount.com
  key_file: /etc/secrets/ee-key.json
```

## Supported datasets

| Slug | Collection | Native resolution |
|---|---|---|
| `sentinel-2` | `COPERNICUS/S2_SR_HARMONIZED` | 10 m |
| `sentinel-1` | `COPERNICUS/S1_GRD` (IW, DESC) | 10 m |
| `landsat-7` | `LANDSAT/LE07/C02/T1_L2` | 30 m |
| `landsat-8` | `LANDSAT/LC08/C02/T1_L2` | 30 m |
| `landsat-9` | `LANDSAT/LC09/C02/T1_L2` | 30 m |

Add new datasets by editing [`geedl/datasets/registry.yaml`](https://github.com/amirafshari/geedl/blob/master/geedl/datasets/registry.yaml)
— no Python changes required.

```bash
geedl datasets                        # list available datasets
geedl indices --dataset sentinel-2   # list compatible indices
```

## Spectral indices

Out of the box: **NDVI, NDWI, NDMI, NBR, NDSI, EVI, SAVI, BSI** (optical) and
**RVI, VV/VH ratio**, **WATER_S1** (SAR).

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

## Tuning concurrency and tile size

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
