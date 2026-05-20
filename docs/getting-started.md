# Getting started

This page walks you from a clean shell to a downloaded Cloud-Optimized GeoTIFF
in under five minutes.

!!! tip "Skip the YAML — let an agent write it"
    The fastest way to use `geedl` is to **not write the YAML yourself**.
    Drop the [README](https://github.com/amirafshari/geedl#readme) and
    [`CLAUDE.md`](https://github.com/amirafshari/geedl/blob/master/.claude/CLAUDE.md)
    into your coding agent's context — Claude Code, Cursor, Codex, Aider, ChatGPT —
    then describe your job in English ("monthly NDVI over Tuscany for 2023,
    Sentinel-2, drop source bands"). The agent emits a complete, runnable
    `job.yaml`. You run `geedl plan && geedl run` and you're done. The rest of
    this page is the manual path, for when you want to write or tweak configs
    by hand.

## 1. Install

`geedl` uses a **conda** environment for system-level geospatial libraries
(GDAL, PROJ, GEOS) and **uv** for fast Python dependency resolution inside it.

```bash
# Create and activate the conda environment
conda create -n geedl python=3.12 -y
conda activate geedl

# Install uv inside the env
conda install -c conda-forge uv -y

# Install geedl (editable)
git clone https://github.com/amirafshari/geedl.git
cd geedl
uv pip install -e .
```

With development tooling:

```bash
uv pip install -e ".[dev]"
```

!!! tip "New shell, new activation"
    Every new shell session needs `conda activate geedl` before running the
    `geedl` CLI.

## 2. Authenticate with Earth Engine

One-time browser flow:

```bash
earthengine authenticate
```

For headless / CI environments, use a service account — see
[Configuration → Authentication](configuration.md#authentication).

## 3. Write a job

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

## 4. Run it

```bash
geedl validate -c job.yaml   # check config (no EE calls)
geedl plan     -c job.yaml   # preview windows + tile count
geedl run      -c job.yaml   # download to ./output
```

## 5. Resume if interrupted

Just re-run the same command. Completed tiles are skipped automatically.

```bash
geedl run -c job.yaml                  # resume
geedl run -c job.yaml --retry-failed   # also retry tiles that failed
geedl status -c job.yaml               # check progress
```

## Output structure

```
output/
  sentinel-2/
    2023-01-01/
      tile_A00_2023-01-01.tif      # Cloud-Optimized GeoTIFF
      tile_A00_2023-01-01.json     # STAC Item sidecar
      ...
  catalog.parquet                   # GeoParquet spatial index
  job.yaml                          # frozen copy of the config used
  checkpoint.db                     # SQLite resume state
```

Read the catalog back with any GeoParquet-aware tool:

```python
import geopandas as gpd
gdf = gpd.read_parquet("output/catalog.parquet")
gdf[gdf.datetime.str.startswith("2023-01")].plot()
```

## Where to next

- [Configuration reference](configuration.md) — every YAML field, every dataset, every index.
- [Examples](examples.md) — ten ready-to-run YAMLs for common workflows.
