# geedl — Design & Architecture Document

> **geedl** (GEE Downloader) — Local-first, resumable, high-throughput downloader for Google Earth Engine.
> Version: 0.2-design | Status: Pre-implementation

---

## 1. Project goals

- Download satellite imagery from Earth Engine **directly to local disk** — no GCS, no Drive.
- Handle **large, irregular polygon ROIs** from shapefiles transparently.
- Support **Sentinel-1, Sentinel-2, Landsat 7/8/9** and all derived spectral indices.
- Be **as fast as possible** within EE's API constraints.
- Be **crash-safe and fully resumable** — any failure can be recovered and continued exactly.
- Be **modular and YAML-driven** — every structural decision (band order, output shape,
  time windows, compositing) is addressable from the config file without touching Python.
- Be **AI-agent friendly** — the YAML config is the single source of truth; agents can
  refactor jobs, swap datasets, change output shapes, and wire hooks without reading source code.

---

## 2. Repository layout

```
geedl/
  geedl/
    cli.py                    # typer CLI entry point
    config.py                 # pydantic config schema + validation
    datasets/
      registry.yaml           # dataset definitions (collection, bands, resolution, masks)
      registry.py             # YAML loader + dataset resolver
      cloud_masks.py          # per-sensor cloud/shadow mask functions
    indices/
      __init__.py             # @index decorator + global registry
      optical.py              # NDVI, EVI, NDWI, SAVI, NBR, NDSI, BSI, ...
      sar.py                  # RVI, entropy (Sentinel-1)
    roi/
      loader.py               # shapefile → GeoDataFrame, CRS handling
      simplifier.py           # vertex reduction before asset upload
      tiler.py                # grid decomposition + tile classification
      asset_manager.py        # EE asset upload + reuse logic
    pipeline/
      scheduler.py            # async task runner, concurrency control
      downloader.py           # ee.data.computePixels wrapper
      compositor.py           # window generation + mosaic/median strategies
      validator.py            # per-tile integrity checks
    io/
      writer.py               # rasterio GeoTIFF / COG writer (atomic)
      catalog.py              # STAC item sidecar + GeoParquet index
      checkpoint.py           # SQLite resume DB
    utils/
      crs.py                  # auto-UTM detection
      retry.py                # exponential backoff with jitter
      budget.py               # pixel budget calculator
      windows.py              # time window generator
  tests/
    fixtures/                 # small test shapefiles + VCR cassettes
    test_tiler.py
    test_indices.py
    test_checkpoint.py
    test_downloader.py
    test_windows.py
  docs/
  pyproject.toml
  README.md
```

---

## 3. Technology stack

| Concern | Choice | Notes |
|---|---|---|
| EE access | `earthengine-api` (Python SDK) | Official; wraps REST API |
| Direct pixel download | `ee.data.computePixels()` | No GCS/Drive required |
| Shapefile I/O | `geopandas` + `fiona` | Full CRS support |
| Geometry ops | `shapely` | Tiling, intersection, coverage ratio |
| Raster I/O | `rasterio` + `GDAL` | GeoTIFF, COG, reprojection, masking |
| CLI | `typer` | Auto-docs, shell completion |
| Config validation | `pydantic` v2 | Schema enforcement, helpful error messages |
| Async runtime | `asyncio` + `aiohttp` | Non-blocking tile downloads |
| Checkpointing | `sqlite3` (stdlib) | Zero extra dependency |
| Spatial catalog | `geopandas` → GeoParquet | Queryable output index |
| STAC sidecars | `pystac` | Per-tile metadata |
| Testing | `pytest` + `pytest-recording` (VCR) | Replay EE HTTP responses |

---

## 4. Full configuration schema

The YAML config is the **single source of truth** for every decision geedl makes.
An AI agent can read and modify this file to fully refactor a job without touching Python.
All CLI flags mirror config keys and override them.

```yaml
# ── IDENTITY ─────────────────────────────────────────────────────────────────
job_name: my_sentinel2_ndvi_job   # used in logs and checkpoint DB

# ── ROI ───────────────────────────────────────────────────────────────────────
roi:
  path: parcels.shp
  layer: null                  # optional layer name for multi-layer files
  feature_mode: union          # union  — all features merged into one ROI (default)
                               # split  — one output subfolder per feature
                               # filter — only features matching filter_expr
  filter_expr: null            # e.g. "crop_type == 'wheat'"
  simplify_tolerance: auto     # metres, or "auto" = 10% of resolution

# ── DATASET ───────────────────────────────────────────────────────────────────
dataset:
  name: sentinel-2             # slug from registry.yaml

  bands:
    select: [B4, B3, B2, B8]  # null = all bands from registry
    order: [B2, B3, B4, B8]   # explicit output band order (null = same as select)
    rename:                    # optional rename map applied after download
      B2: blue
      B3: green
      B4: red
      B8: nir
    scale_factor: 0.0001       # multiplied after download (null = registry default)
    offset: 0                  # additive offset applied after scale

  indices:
    - name: NDVI
      output_band: NDVI        # rename output band (null = index name)
      position: after_bands    # after_bands | before_bands | <integer N>
    - name: EVI
      output_band: EVI
      position: after_bands

  cloud_mask:
    enabled: true
    profile: auto              # auto = registry default; or explicit fn name
    mask_shadow: true
    mask_snow: false

  # Landsat 7 SLC-off handling (ignored for all other datasets)
  slc_off:
    strategy: multi_temporal   # only valid strategy in geedl v0.1
                               # relies on QA mask + multi-scene compositing
                               # gaps fill naturally when window has >= 3 scenes
    min_scenes_warning: 3      # warn at validation time if window likely has fewer

# ── DATE & WINDOWING ─────────────────────────────────────────────────────────
date:
  start: "2023-01-15"
  end:   "2023-06-30"

composite:
  strategy: median             # median | mosaic | none
                               # none = one output file per EE scene, no compositing

  window:
    type: fixed_days           # fixed_days      — arbitrary N-day windows
                               # calendar_month  — 1st to last day of each month
                               # calendar_year   — 1st Jan to 31st Dec
                               # full_range      — single window over entire date range
                               # scene           — no compositing; one file per scene
    size: 40                   # days per window (fixed_days only)
    step: 40                   # days between window starts
                               # null = same as size (non-overlapping)
                               # < size = overlapping windows
    anchor: start              # start | end | center
                               # which date within the window is the origin
    min_scenes: 1              # skip window entirely if fewer EE scenes available
    label_format: "%Y-%m-%d"  # strftime pattern used as output folder name
                               # for fixed_days: label = window start date

# ── OUTPUT SHAPE ─────────────────────────────────────────────────────────────
output:
  dir: ./output
  format: COG                  # COG | GeoTIFF
  nodata: -9999
  dtype: float32               # float32 | int16 | uint16 (applied post-scale)
  crs: null                    # null = auto-UTM from ROI centroid; or EPSG:XXXX
  compression: LZW             # LZW | DEFLATE | ZSTD | none

  structure:
    timeseries_mode: false     # false = one file per window per tile (default)
                               # true  = all windows stacked into one multi-band file
                               #         band order: [B_w1, B_w2, NDVI_w1, NDVI_w2, ...]
    band_interleave: BIP       # BIP | BIL | BSQ (meaningful only for timeseries_mode)
    filename_template: "tile_{tile_id}_{window_label}"
                               # available variables:
                               #   tile_id, window_label, dataset,
                               #   date_start, date_end, strategy
    separate_indices: false    # false = indices in same file as spectral bands
                               # true  = one file for bands, one file for indices

# ── TILING ───────────────────────────────────────────────────────────────────
tiling:
  max_tile_bytes: null         # null = auto-calculated from pixel budget
  overlap_px: 2                # pixel overlap buffer added to each tile request
  skip_coverage_threshold: 0.05  # skip tiles with < 5% ROI coverage
  grid_snap_m: 100             # snap grid origin to nearest N metres

# ── PIPELINE ─────────────────────────────────────────────────────────────────
pipeline:
  concurrency: 16              # async semaphore size; tune to your EE quota
  max_retries: 6               # per tile; exponential backoff with jitter
  retry_base_delay: 1.0        # seconds
  timeout_per_tile: 120        # seconds; hard-cancel if EE hangs

# ── EE ASSET ─────────────────────────────────────────────────────────────────
asset:
  project: my-ee-project       # EE project ID or username
  base_path: users/me/geedl_assets
  auto_cleanup: false          # delete ROI asset after job completes

# ── HOOKS (AI agent extensibility) ───────────────────────────────────────────
hooks:
  pre_download: null           # "mymodule:fn" — called before pipeline starts
  post_tile: null              # called after each tile is written to disk
  post_job: null               # called after all tiles complete
```

---

## 5. Dataset registry (`datasets/registry.yaml`)

```yaml
sentinel-2:
  collection: COPERNICUS/S2_SR_HARMONIZED
  bands:
    B1:  {desc: "Coastal aerosol", res: 60}
    B2:  {desc: "Blue",           res: 10}
    B3:  {desc: "Green",          res: 10}
    B4:  {desc: "Red",            res: 10}
    B8:  {desc: "NIR",            res: 10}
    B11: {desc: "SWIR-1",         res: 20}
    B12: {desc: "SWIR-2",         res: 20}
    SCL: {desc: "Scene class",    res: 20}
  native_res: 10
  cloud_mask: s2_scl_mask
  scale_factor: 0.0001
  date_property: system:time_start
  slc_off_date: null

sentinel-1:
  collection: COPERNICUS/S1_GRD
  bands:
    VV:    {desc: "VV polarisation",  res: 10}
    VH:    {desc: "VH polarisation",  res: 10}
    angle: {desc: "Incidence angle",  res: 10}
  native_res: 10
  cloud_mask: null             # SAR is cloud-transparent
  scale_factor: null           # already in dB
  date_property: system:time_start
  extra_filters:
    - {property: instrumentMode,        value: IW}
    - {property: orbitProperties_pass,  value: DESCENDING}
  slc_off_date: null
  composite_strategy_override: mosaic   # median is meaningless for SAR backscatter

landsat-7:
  collection: LANDSAT/LE07/C02/T1_L2
  bands:
    SR_B1:    {desc: "Blue",    res: 30}
    SR_B2:    {desc: "Green",   res: 30}
    SR_B3:    {desc: "Red",     res: 30}
    SR_B4:    {desc: "NIR",     res: 30}
    SR_B5:    {desc: "SWIR-1",  res: 30}
    SR_B7:    {desc: "SWIR-2",  res: 30}
    QA_PIXEL: {desc: "Quality", res: 30}
  native_res: 30
  cloud_mask: landsat_qa_mask
  scale_factor: 0.0000275
  offset: -0.2
  date_property: system:time_start
  slc_off_date: "2003-05-31"   # gaps present in all scenes after this date
  slc_off_coverage_loss: 0.22  # ~22% nodata per scene at full extent

landsat-8:
  collection: LANDSAT/LC08/C02/T1_L2
  bands:
    SR_B2:    {desc: "Blue",    res: 30}
    SR_B3:    {desc: "Green",   res: 30}
    SR_B4:    {desc: "Red",     res: 30}
    SR_B5:    {desc: "NIR",     res: 30}
    SR_B6:    {desc: "SWIR-1",  res: 30}
    SR_B7:    {desc: "SWIR-2",  res: 30}
    QA_PIXEL: {desc: "Quality", res: 30}
  native_res: 30
  cloud_mask: landsat_qa_mask
  scale_factor: 0.0000275
  offset: -0.2
  date_property: system:time_start
  slc_off_date: null

landsat-9:
  collection: LANDSAT/LC09/C02/T1_L2
  bands:
    SR_B2:    {desc: "Blue",    res: 30}
    SR_B3:    {desc: "Green",   res: 30}
    SR_B4:    {desc: "Red",     res: 30}
    SR_B5:    {desc: "NIR",     res: 30}
    SR_B6:    {desc: "SWIR-1",  res: 30}
    SR_B7:    {desc: "SWIR-2",  res: 30}
    QA_PIXEL: {desc: "Quality", res: 30}
  native_res: 30
  cloud_mask: landsat_qa_mask
  scale_factor: 0.0000275
  offset: -0.2
  date_property: system:time_start
  slc_off_date: null
```

---

## 6. Index engine

Indices are pure functions registered with a decorator.
Adding a new index requires no changes to core code — only a new function in
`indices/optical.py` or `indices/sar.py`.

```python
# indices/__init__.py
_REGISTRY: dict[str, dict] = {}

def index(name: str, datasets: list[str] | None = None):
    def decorator(fn):
        _REGISTRY[name] = {"fn": fn, "datasets": datasets}
        return fn
    return decorator

def apply_indices(image: ee.Image, names: list[str], dataset: str) -> ee.Image:
    for name in names:
        entry = _REGISTRY[name]
        if entry["datasets"] and dataset not in entry["datasets"]:
            raise ValueError(f"Index {name} not supported for {dataset}")
        image = image.addBands(entry["fn"](image, dataset))
    return image
```

```python
# indices/optical.py  — band name map per dataset
BAND_MAP = {
    "sentinel-2": {"nir":"B8",    "red":"B4",    "green":"B3", "blue":"B2",  "swir1":"B11","swir2":"B12"},
    "landsat-7":  {"nir":"SR_B4", "red":"SR_B3", "green":"SR_B2","blue":"SR_B1","swir1":"SR_B5","swir2":"SR_B7"},
    "landsat-8":  {"nir":"SR_B5", "red":"SR_B4", "green":"SR_B3","blue":"SR_B2","swir1":"SR_B6","swir2":"SR_B7"},
    "landsat-9":  {"nir":"SR_B5", "red":"SR_B4", "green":"SR_B3","blue":"SR_B2","swir1":"SR_B6","swir2":"SR_B7"},
}

@index("NDVI", datasets=["sentinel-2","landsat-7","landsat-8","landsat-9"])
def ndvi(img, ds):
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["nir"], b["red"]]).rename("NDVI")

@index("NDWI", datasets=["sentinel-2","landsat-7","landsat-8","landsat-9"])
def ndwi(img, ds):
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["green"], b["nir"]]).rename("NDWI")

@index("EVI", datasets=["sentinel-2","landsat-8","landsat-9"])
def evi(img, ds):
    b = BAND_MAP[ds]
    return img.expression(
        "2.5*(NIR-RED)/(NIR+6*RED-7.5*BLUE+1)",
        {"NIR":img.select(b["nir"]),"RED":img.select(b["red"]),"BLUE":img.select(b["blue"])}
    ).rename("EVI")

@index("NBR", datasets=["sentinel-2","landsat-7","landsat-8","landsat-9"])
def nbr(img, ds):
    b = BAND_MAP[ds]
    return img.normalizedDifference([b["nir"], b["swir2"]]).rename("NBR")

@index("SAVI", datasets=["sentinel-2","landsat-7","landsat-8","landsat-9"])
def savi(img, ds):
    b = BAND_MAP[ds]; L = 0.5
    return img.expression(
        "((NIR-RED)/(NIR+RED+L))*(1+L)",
        {"NIR":img.select(b["nir"]),"RED":img.select(b["red"]),"L":L}
    ).rename("SAVI")

@index("BSI", datasets=["sentinel-2","landsat-8","landsat-9"])
def bsi(img, ds):
    b = BAND_MAP[ds]
    return img.expression(
        "(SWIR1+RED-NIR-BLUE)/(SWIR1+RED+NIR+BLUE)",
        {"SWIR1":img.select(b["swir1"]),"RED":img.select(b["red"]),
         "NIR":img.select(b["nir"]),"BLUE":img.select(b["blue"])}
    ).rename("BSI")

# indices/sar.py
@index("RVI", datasets=["sentinel-1"])
def rvi(img, ds):
    return img.expression(
        "4*VH/(VV+VH)", {"VV":img.select("VV"),"VH":img.select("VH")}
    ).rename("RVI")
```

---

## 7. Time window system

Window generation is a pure function in `utils/windows.py`.
It takes config and returns an ordered list of `Window` named tuples.
The output folder name is derived from `window.label_format` applied to the
window's anchor date — so folder names are always unambiguous regardless of
window type or size.

```python
Window = namedtuple("Window", ["start", "end", "label"])

def generate_windows(date_cfg, window_cfg) -> list[Window]:
    start, end = date_cfg.start, date_cfg.end

    if window_cfg.type == "full_range":
        return [Window(start, end, "full")]

    if window_cfg.type == "scene":
        return None  # sentinel value — compositor bypassed, one file per EE scene

    if window_cfg.type == "calendar_month":
        windows = []
        cursor = start.replace(day=1)
        while cursor <= end:
            w_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            windows.append(Window(cursor, min(w_end, end), cursor.strftime(window_cfg.label_format)))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        return windows

    if window_cfg.type == "fixed_days":
        size = timedelta(days=window_cfg.size)
        step = timedelta(days=window_cfg.step or window_cfg.size)
        windows, cursor = [], start
        while cursor < end:
            w_end = min(cursor + size, end)
            anchor_date = {"start": cursor, "end": w_end, "center": cursor + (w_end - cursor) / 2}[window_cfg.anchor]
            windows.append(Window(cursor, w_end, anchor_date.strftime(window_cfg.label_format)))
            cursor += step
        return windows
```

**Examples with a 2023-01-15 → 2023-06-30 range:**

| Config | Windows produced |
|---|---|
| `type: fixed_days, size: 40, step: 40` | 2023-01-15, 2023-02-24, 2023-04-05, 2023-05-15, 2023-06-24 |
| `type: fixed_days, size: 30, step: 10` | Overlapping 30-day windows every 10 days |
| `type: calendar_month` | 2023-01, 2023-02, 2023-03, 2023-04, 2023-05, 2023-06 |
| `type: full_range` | Single window: 2023-01-15 → 2023-06-30 |
| `type: fixed_days, size: 16, step: 16` | Landsat revisit cycle |

---

## 8. ROI pipeline

### 8.1 Load + reproject

```
shapefile → GeoDataFrame → union/split/filter per feature_mode → reproject to auto-UTM
```

Auto-UTM is derived from the ROI centroid. All tiling and geometry math works in metres.

### 8.2 Simplify before upload

```python
tolerance_m = resolution_m * 0.1   # 1 m for S2, 3 m for Landsat
roi_simplified = roi.simplify(tolerance=tolerance_m, preserve_topology=True)
```

The original (unsimplified) geometry is used for local tile classification.
The simplified geometry is what gets uploaded as the EE asset.

### 8.3 EE asset upload

```
hash(shapefile bytes) → deterministic asset ID
  → check if asset exists in EE
    → if yes: reuse (log reuse)
    → if no:  upload as EE batch task → poll until COMPLETED
→ store asset_id in checkpoint DB
→ return ee.FeatureCollection(asset_id) reference
```

- Asset ID: `{base_path}/roi_{sha1[:10]}`
- Upload blocks the job start — every downstream tile depends on it.
- `auto_cleanup: true` deletes the asset after `post_job` hook completes.
- A resumed job reads `asset_id` from the checkpoint DB and skips re-upload entirely.

### 8.4 Tiling

**Tile size** back-calculated from pixel budget:

```python
BUDGET_BYTES   = 40_000_000          # 40 MB (conservative vs 48 MB EE limit)
HEADROOM       = 0.80                # 20% safety margin
n_bands        = len(select) + len(indices)
safe_pixels    = (BUDGET_BYTES / (n_bands * 4)) * HEADROOM
tile_side_px   = int(safe_pixels ** 0.5)
tile_side_m    = tile_side_px * resolution_m
```

**Grid origin** snapped to nearest `grid_snap_m` multiple north/west of bounding box.
Same ROI + same resolution always produces identical tile boundaries across runs.

**Tile classification:**

| Class | Condition | EE request | Server clip | Local mask |
|---|---|---|---|---|
| `inside` | All 4 corners in ROI | Full tile rect | No | No |
| `partial` | Mixed corners, coverage ≥ 5% | Tile rect + overlap buffer | Yes (`img.clip(roi_fc)`) | Yes (rasterio) |
| `edge` | Mixed corners, coverage < 5% | — | — | — |
| `outside` | All 4 corners outside ROI | — | — | — |

Coverage ratio: `tile.geom.intersection(roi).area / tile.geom.area`

The double-mask on `partial` tiles is intentional: EE clip saves bandwidth;
local rasterio mask catches sub-pixel boundary drift from floating-point CRS transforms.

**Tile ordering:** Hilbert space-filling curve. Spatially adjacent tiles fetched
together → EE internal cache stays warm → measurably lower per-tile latency.

**Overlap buffer:** Each tile's *request geometry* is expanded by
`overlap_px × resolution_m` on all sides. Written tile is cropped to exact boundary.
Prevents seam artefacts when tiles are later mosaicked.

---

## 9. Landsat 7 SLC-off handling

**Strategy: `multi_temporal` (only supported strategy in geedl)**

Post-May 31 2003, Landsat 7's scan-line corrector failure leaves ~22% of each
scene as nodata gaps (wedge-shaped stripes, worst at scene edges, zero at center).

geedl handles this entirely through the standard compositing pipeline:

1. The `landsat_qa_mask` function already flags SLC-off gap pixels as nodata
   (they appear in `QA_PIXEL` as fill values). No special code path needed.
2. The compositor stacks all available scenes within the time window and applies
   `median` (or `mosaic`). With ≥ 3 scenes per window, gap positions differ
   across orbits and the median fills ~97% of pixels naturally.
3. The registry records `slc_off_date: "2003-05-31"`. The config validator
   checks this at startup:

```python
def validate_slc_off(cfg, registry):
    ds = registry[cfg.dataset.name]
    if ds.slc_off_date and cfg.date.start > ds.slc_off_date:
        # Estimate scenes per window from 16-day revisit cycle
        approx_scenes = window_days / 16
        if approx_scenes < cfg.dataset.slc_off.min_scenes_warning:
            warn(
                f"Landsat 7 SLC-off: window of {window_days} days yields "
                f"~{approx_scenes:.1f} scenes. Gap fill needs >= "
                f"{cfg.dataset.slc_off.min_scenes_warning} scenes. "
                f"Consider widening the window or using Landsat 8/9."
            )
        if cfg.composite.window.type == "scene":
            raise ConfigError(
                "Landsat 7 post-2003 with strategy: none will produce heavily "
                "gapped single-scene outputs. Use composite.strategy: median "
                "with a window wide enough for >= 3 scenes."
            )
```

**Implications for window sizing with Landsat 7 post-2003:**

| Window size | Approx. scenes | Gap fill quality |
|---|---|---|
| 16 days | ~1 | Poor — raw gaps visible |
| 32 days | ~2 | Moderate |
| 48 days | ~3 | Good — ~97% coverage |
| 64 days | ~4 | Excellent |

The default `min_scenes_warning: 3` will warn the user if their chosen
`fixed_days` size is too narrow. The fix is always to widen the window — never
to use focal fill, which introduces blur that corrupts index calculations.

---

## 10. Compositing pipeline

```python
# compositor.py

def build_collection(dataset_cfg, window: Window, roi_asset) -> ee.ImageCollection:
    ds = registry[dataset_cfg.name]
    col = (ee.ImageCollection(ds.collection)
           .filterDate(window.start.isoformat(), window.end.isoformat())
           .filterBounds(ee.FeatureCollection(roi_asset).geometry()))

    # Apply any dataset-level extra filters (e.g. Sentinel-1 orbit mode)
    for f in ds.extra_filters or []:
        col = col.filter(ee.Filter.eq(f["property"], f["value"]))

    # Apply cloud/shadow mask if enabled
    if dataset_cfg.cloud_mask.enabled and ds.cloud_mask:
        mask_fn = cloud_masks.get(ds.cloud_mask)
        col = col.map(mask_fn)

    return col

def composite(col: ee.ImageCollection, strategy: str, dataset_name: str) -> ee.Image:
    # Sentinel-1: override median → mosaic regardless of config
    ds = registry[dataset_name]
    effective_strategy = ds.get("composite_strategy_override", strategy)
    if effective_strategy == "median":
        return col.median()
    if effective_strategy == "mosaic":
        return col.mosaic()
    raise ValueError(f"Unknown strategy: {effective_strategy}")

def apply_bands_and_indices(image: ee.Image, dataset_cfg) -> ee.Image:
    # Select bands
    image = image.select(dataset_cfg.bands.select)

    # Apply scale + offset
    scale  = dataset_cfg.bands.scale_factor or registry[dataset_cfg.name].scale_factor
    offset = dataset_cfg.bands.offset or registry[dataset_cfg.name].get("offset", 0)
    image  = image.multiply(scale).add(offset)

    # Compute and append indices
    image = apply_indices(image, [i.name for i in dataset_cfg.indices], dataset_cfg.name)

    # Reorder bands per config (select + indices combined, in declared order)
    ordered_bands = _resolve_band_order(dataset_cfg)
    image = image.select(ordered_bands)

    # Rename
    if dataset_cfg.bands.rename:
        old = list(dataset_cfg.bands.rename.keys())
        new = list(dataset_cfg.bands.rename.values())
        image = image.select(old, new)  # EE select supports rename

    return image

def _resolve_band_order(dataset_cfg) -> list[str]:
    """
    Merge spectral bands and indices into a single ordered list,
    respecting each index's declared position (after_bands | before_bands | int).
    """
    bands = list(dataset_cfg.bands.order or dataset_cfg.bands.select)
    result = bands[:]
    offset = 0
    for idx_cfg in dataset_cfg.indices:
        if idx_cfg.position == "after_bands":
            result.append(idx_cfg.output_band or idx_cfg.name)
        elif idx_cfg.position == "before_bands":
            result.insert(0, idx_cfg.output_band or idx_cfg.name)
        elif isinstance(idx_cfg.position, int):
            result.insert(idx_cfg.position + offset, idx_cfg.output_band or idx_cfg.name)
            offset += 1
    return result
```

---

## 11. Download pipeline

### 11.1 API call

`ee.data.computePixels()` is used exclusively — returns raw bytes directly,
no export task, no bucket, no Drive.

```python
params = {
    "expression": ee.serializer.encode(image),
    "fileFormat": "NPY",          # numpy binary — fastest deserialization
    "bandIds": ordered_band_list,
    "grid": {
        "crsCode": f"EPSG:{tile_epsg}",
        "affineTransform": {
            "scaleX": resolution_m,  "shearX": 0, "translateX": tile_origin_x,
            "shearY": 0, "scaleY": -resolution_m,  "translateY": tile_origin_y,
        },
        "dimensions": {"width": tile_width_px, "height": tile_height_px},
    },
}
raw  = ee.data.computePixels(params)
arr  = np.load(io.BytesIO(raw))   # shape: (height, width) structured array → bands
```

### 11.2 Concurrency model

- `asyncio` event loop; `ee.data.computePixels` (sync) runs in `ThreadPoolExecutor`.
- Global `asyncio.Semaphore(config.pipeline.concurrency)` caps simultaneous requests.
- Default: **16**. Recommended maximum: **32** (EE quota ~40 concurrent).
- Tile manifest is sorted by Hilbert index before being fed to `asyncio.as_completed`.

### 11.3 Retry logic

Exponential backoff with full jitter. Retried on: HTTP 429, 500, 503, `ConnectionError`.
Not retried on: HTTP 400 (bad params), 401/403 (auth) — these mark the tile `failed` immediately.

```
delay = uniform(0, min(base_delay * 2^attempt, 60))   seconds
max_attempts: config.pipeline.max_retries (default 6)
```

---

## 12. Write pipeline

### 12.1 Atomic write

```
download → validate → write to {tile_id}.tmp.tif → rename → checkpoint.mark_done()
```

`os.rename()` is atomic on POSIX. A crashed process never leaves a corrupt file
at the real output path.

### 12.2 Timeseries mode vs per-window mode

**`timeseries_mode: false` (default)**

```
output/{dataset}/{window_label}/tile_{tile_id}.tif
```

One COG per tile per window. Bands are `[B2, B3, B4, B8, NDVI, EVI]` (as declared).

**`timeseries_mode: true`**

```
output/{dataset}/tile_{tile_id}.tif   (one file, all windows stacked)
```

Band order: all bands for window 1, then window 2, etc., then all indices for
window 1, window 2, etc. — controlled by `band_interleave` setting.
Band names embedded in the GeoTIFF metadata as `{band}_{window_label}`.

**`separate_indices: true`**

Produces sibling files:
```
tile_{tile_id}_{window_label}_bands.tif
tile_{tile_id}_{window_label}_indices.tif
```

### 12.3 Per-tile validation before write

1. Array shape matches expected `(bands, height, width)`.
2. Array is not all-nodata (EE returned empty — retry, don't write).
3. Value range plausible for dataset (configurable soft check — warns, not fatal).

### 12.4 Output format

COG default: internally tiled at 256×256 blocks, LZW compression, overviews at 2×/4×/8×.
Readable by QGIS, GDAL, stackstac, and any STAC browser without conversion.

---

## 13. Output folder structure

```
output/
  {dataset}/
    {window_label}/            # e.g. "2023-01-15" or "2023-01" or "full"
      tile_A01.tif
      tile_A01.json            # STAC Item sidecar
      tile_B02.tif
      tile_B02.json
  catalog.parquet              # spatial index of all completed tiles
  job.yaml                     # verbatim copy of config used for this run
  checkpoint.db                # SQLite resume state
```

With `timeseries_mode: true`, the `{window_label}` level is absent —
one file per tile at the dataset level.

---

## 14. Checkpoint & resume system

### 14.1 Schema

```sql
CREATE TABLE job (
  config_hash   TEXT PRIMARY KEY,
  asset_id      TEXT NOT NULL,
  started_at    REAL NOT NULL,
  completed_at  REAL
);

CREATE TABLE tiles (
  id            TEXT PRIMARY KEY,   -- "{tile_grid_id}_{window_label}"
  status        TEXT NOT NULL,      -- pending | in_flight | done | failed
  attempts      INTEGER DEFAULT 0,
  last_error    TEXT,
  output_path   TEXT,
  completed_at  REAL
);
```

### 14.2 Tile ID

Tile IDs encode both the grid position and the time window:
`{col_letter}{row_number}_{window_label}` → e.g. `A01_2023-01-15`, `B03_full`.

This means a job with 50 spatial tiles and 5 windows has 250 checkpointable units.
Each unit is independently resumable.

### 14.3 State machine

```
pending → in_flight → done
                    ↘ failed   (after max_retries; re-queued with --retry-failed)
```

On startup:
- `in_flight` → reset to `pending`, delete output file if it exists.
- `done` → skipped.
- `failed` → skipped unless `--retry-failed`.

Config hash mismatch → warning + confirmation prompt before proceeding.

### 14.4 CLI resume interface

```bash
geedl run    --config job.yaml                # run or resume
geedl run    --config job.yaml --retry-failed # also retry failed tiles
geedl run    --config job.yaml --fresh        # ignore checkpoint, start over
geedl status --config job.yaml               # show done/pending/failed counts
geedl plan   --config job.yaml               # dry run: print tile manifest
geedl validate --config job.yaml             # validate config only
geedl datasets                               # list available dataset slugs
geedl indices --dataset sentinel-2           # list available indices
geedl cleanup --config job.yaml              # delete EE asset for this job
```

---

## 15. STAC catalog

Each tile gets a JSON sidecar (STAC Item 1.0):

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "tile_A01_2023-01-15",
  "geometry": {"type": "Polygon", "coordinates": [...]},
  "bbox": [minx, miny, maxx, maxy],
  "properties": {
    "datetime": "2023-01-15T00:00:00Z",
    "start_datetime": "2023-01-15T00:00:00Z",
    "end_datetime": "2023-02-24T00:00:00Z",
    "platform": "sentinel-2",
    "gsd": 10,
    "eo:bands": [...],
    "geedl:tile_class": "inside",
    "geedl:attempts": 1,
    "geedl:window_type": "fixed_days",
    "geedl:window_size_days": 40
  },
  "assets": {
    "data": {
      "href": "./tile_A01_2023-01-15.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized"
    }
  }
}
```

After the job completes, `catalog.parquet` aggregates all tile footprints:

```python
gdf = gpd.read_parquet("output/catalog.parquet")
gdf[gdf.window_label == "2023-01-15"].plot()
```

---

## 16. Key design decisions — consolidated

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Project name | `geedl` | Short, memorable, unambiguous |
| 2 | ROI delivery to EE | Upload as EE asset once per job | Eliminates repeated JSON payload per tile; enables server-side clip by reference |
| 3 | Asset ID strategy | SHA1 of shapefile bytes → deterministic path | Same file reuses existing asset; different files never collide |
| 4 | Geometry simplification | 10% of resolution before upload | Sub-pixel precision is meaningless; reduces asset size and parse time |
| 5 | Tile size derivation | Back-calculated from pixel budget | Always safe; auto-adapts to band count and resolution |
| 6 | Tile classification | inside / partial / edge / outside | Eliminates EE requests for empty space; largest single speed win |
| 7 | Coverage threshold | Skip tiles < 5% ROI coverage | Not worth EE compute cost for nearly-empty border tiles |
| 8 | Server-side clip | Only for `partial` tiles | `inside` tiles waste EE compute; `edge`/`outside` are skipped |
| 9 | Local mask | Always applied to `partial` tiles | Safety net for sub-pixel CRS boundary drift after EE clip |
| 10 | Tile ordering | Hilbert space-filling curve | Spatial locality → EE cache warmth → measurably lower per-tile latency |
| 11 | Concurrency | Async semaphore, default 16 | Stays well under EE quota (~40); tune per project |
| 12 | Retry strategy | Exponential backoff + full jitter | Prevents thundering herd on rate-limit bursts |
| 13 | Write safety | Write-to-tmp, then atomic `os.rename` | Crash never leaves corrupt file at real output path |
| 14 | Resume model | SQLite; reset `in_flight` on startup | Full idempotency; safe to kill at any point |
| 15 | Download API | `computePixels` exclusively | Local-first; no GCS/Drive dependency whatsoever |
| 16 | Wire format | NPY (numpy binary) | Fastest deserialization; skips image codec entirely |
| 17 | Output format | COG by default | QGIS/GDAL/stackstac native; spatially queryable without full read |
| 18 | Time windows | Flexible `window` block in config | Supports fixed-day, calendar-month, overlapping, and scene modes |
| 19 | Window label | `label_format` strftime on anchor date | Unambiguous folder names regardless of window shape or size |
| 20 | Timeseries mode | `structure.timeseries_mode` flag | Stack-all vs per-window is a YAML decision, not a code path |
| 21 | Band order | Explicit `bands.order` key in config | Agent-addressable without touching Python |
| 22 | Band rename | `bands.rename` map in config | Cross-dataset normalization via YAML |
| 23 | Index position | `position` per index entry | Band ordering fully declarative |
| 24 | Index extensibility | `@index` decorator, no core changes | Community additions are single-function additions |
| 25 | Sentinel-1 compositing | Registry-level `composite_strategy_override: mosaic` | Median is meaningless for SAR backscatter; enforced automatically |
| 26 | Landsat 7 SLC-off | Strategy `multi_temporal` only | QA mask + median compositor fills gaps naturally at ≥ 3 scenes; no blur, no special code path |
| 27 | SLC-off guard | Config validator warns if window too narrow | User gets actionable feedback at startup, not corrupt output at the end |
| 28 | Config identity | SHA1 hash gates checkpoint reuse | Prevents silently resuming the wrong job after config change |
| 29 | Checkpoint granularity | `{tile_grid_id}_{window_label}` | Each spatial × temporal unit is independently resumable |
| 30 | AI agent interface | YAML is complete job spec; hooks for custom callables | Agents can refactor jobs, swap datasets, change output shapes without reading Python |

---

## 17. Known limitations & future work

**v0.1 scope limits (by design):**

- **Single machine only.** Async pipeline is single-process. A Celery/Ray backend
  is architecturally compatible (tile manifest + checkpoint DB are the right
  abstraction) but out of scope for v0.1.
- **Landsat 7 SLC-off:** Only `multi_temporal` strategy supported. `focal_fill`
  is explicitly excluded — it introduces blur that corrupts index calculations.
- **No per-feature output in `feature_mode: union`.** Multiple shapefile features
  are merged. Feature-level subfolders planned for v0.2.
- **No GUI.** CLI only. A FastAPI + htmx progress dashboard is a natural v0.3 addition.

**Known data quality caveats (documented, not fixed):**

- Very narrow windows with Landsat 7 post-2003 will have residual gaps even after
  compositing. The validator warns; the user must widen the window or switch to L8/L9.
- Sentinel-1 `mosaic` composite takes the first-valid pixel; for backscatter analysis
  users may prefer to handle multi-temporal averaging themselves via the `post_tile` hook.
- Landsat Collection 2 scaling (`× 0.0000275 − 0.2`) is applied by default.
  If the user selects `dtype: int16`, values will be rounded post-scaling — warn
  in validator if `scale_factor != null` and `dtype` is integer.