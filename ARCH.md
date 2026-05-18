# geedl — Design & Architecture

> **geedl** (GEE Downloader) — local-first, resumable, high-throughput downloader for
> Google Earth Engine. Source of truth for what the system is and how the pieces fit.
> [CLAUDE.md](.claude/CLAUDE.md) is the rule sheet for agents touching the code; this
> document is the narrative behind those rules.

Version: 0.2 | Status: Implemented

---

## 1. Project goals

- Download satellite imagery from Earth Engine **directly to local disk** — no GCS, no Drive.
- Handle **large, irregular polygon ROIs** from shapefiles transparently.
- Support **Sentinel-1, Sentinel-2, Landsat 7/8/9** and all derived spectral indices.
- Be **as fast as possible** within EE's API constraints.
- Be **crash-safe and fully resumable** — any failure can be recovered and continued exactly.
- Be **modular and YAML-driven** — every structural decision (band order, output shape,
  time windows, compositing, authentication) is addressable from the config file
  without touching Python.
- Be **AI-agent friendly** — the YAML config is the single source of truth; agents can
  refactor jobs, swap datasets, change output shapes, and wire hooks without reading source code.

---

## 2. Repository layout

```
geedl/
  geedl/
    cli.py                    # typer CLI entry point (run / validate / status / plan / datasets / indices / cleanup)
    config.py                 # pydantic v2 schema; canonical config hash
    datasets/
      registry.yaml           # dataset definitions (collection, bands, resolution, masks, overrides)
      registry.py             # YAML loader + DatasetSpec / BandSpec dataclasses
      cloud_masks.py          # per-sensor cloud/shadow mask functions (s2_scl_mask, landsat_qa_mask, ...)
    indices/
      __init__.py             # @index decorator + apply_indices() + supports() + list_indices()
      optical.py              # NDVI, NDWI, NDMI, NBR, NDSI, EVI, SAVI, BSI
      sar.py                  # RVI, VV_VH_RATIO
    roi/
      loader.py               # shapefile → GeoDataFrame, feature_mode handling, auto-UTM reproject
      simplifier.py           # vertex reduction before EE asset upload
      tiler.py                # grid generation + tile classification + Hilbert ordering
      asset_manager.py        # EE asset upload + reuse + delete (by sha1 of shapefile bytes)
    pipeline/
      runner.py               # job orchestration: ROI → tiles × windows → temp tiles → merge → catalog
      scheduler.py            # asyncio + bounded semaphore + ThreadPoolExecutor
      downloader.py           # ee.data.computePixels wrapper (NPY wire format)
      compositor.py           # build_window_image: collection → composite → bands → indices → order
      scenes.py               # EE-aware scene-mode helpers + NoScenesAvailableError
      validator.py            # per-tile array integrity checks (shape, all-nodata, range)
    io/
      writer.py               # atomic COG/GeoTIFF write + local rasterio mask + overlap crop
      catalog.py              # STAC Item sidecars + GeoParquet index
      checkpoint.py           # SQLite resume DB (WAL); crash recovery
    utils/
      auth.py                 # initialize_ee(cfg) — single ee.Initialize call site
      crs.py                  # auto-UTM EPSG from ROI centroid
      retry.py                # exponential backoff with full jitter (RetryableError)
      budget.py               # safe tile size from pixel budget (20 MB cap)
      windows.py              # pure Window generator (no EE, no I/O)
  tests/
    fixtures/                 # small test shapefiles + VCR cassettes
  examples/
    full-band-only.yaml       # documented job templates
    ndvi-only.yaml
    rgb-only.yaml
    sentinel1-scene.yaml
  ARCH.md                     # this file
  .claude/CLAUDE.md           # agent rules / non-negotiables / contracts
  README.md
  pyproject.toml
```

---

## 3. Technology stack

| Concern | Choice | Notes |
|---|---|---|
| EE access | `earthengine-api` | Official Python SDK |
| Direct pixel download | `ee.data.computePixels()` | No GCS/Drive |
| Shapefile I/O | `geopandas` + `fiona` / `pyogrio` | Full CRS support |
| Geometry ops | `shapely` | Tiling, intersection, coverage ratio |
| Raster I/O | `rasterio` + `GDAL` | COG, merge, mask, reprojection |
| CLI | `typer` | Auto-docs, no-args-is-help |
| Config validation | `pydantic` v2 (`extra=forbid`) | Schema enforcement |
| Async runtime | `asyncio` + `ThreadPoolExecutor` | EE sync calls offloaded to threads |
| Checkpointing | `sqlite3` (stdlib, WAL) | Zero extra dependency |
| Spatial catalog | `geopandas` → GeoParquet | Queryable output index |
| STAC sidecars | `pystac` | Per-tile + per-mosaic metadata |
| Progress UI | `tqdm` | Overall + per-window stacked bars |
| Testing | `pytest` + `pytest-recording` (VCR) | Replay EE HTTP responses |

---

## 4. Configuration schema

The YAML config is the **single source of truth** for every decision geedl makes.
The pydantic schema in `geedl/config.py` accepts no unknown keys (`extra="forbid"`).
The full annotated job template lives in [examples/full-band-only.yaml](examples/full-band-only.yaml);
sketched here with current defaults:

```yaml
job_name: my_sentinel2_ndvi_job

roi:
  path: parcels.shp
  layer: null
  feature_mode: union           # union | split | filter
  filter_expr: null
  simplify_tolerance: auto      # metres, or "auto" = 10% of native resolution

dataset:
  name: sentinel-2
  bands:
    select: [B4, B3, B2, B8]    # null = all registry bands; [] = indices only; list = those bands
    order: null
    rename: null
    scale_factor: null          # null = registry default
    offset: 0.0                 # null = registry default
  indices:
    - {name: NDVI, output_band: NDVI, position: after_bands}
  cloud_mask:
    enabled: true
    profile: auto
    mask_shadow: true
    mask_snow: false
  slc_off:
    strategy: multi_temporal
    min_scenes_warning: 3

date:
  start: "2023-01-15"
  end:   "2023-06-30"

composite:
  strategy: median              # median | mean | mosaic | none
  window:
    type: full_range            # fixed_days | calendar_month | calendar_year | full_range | scene
    size: null                  # days (fixed_days only)
    step: null                  # null = same as size
    anchor: start               # start | end | center
    min_scenes: 1
    label_format: "%Y-%m-%d"
    min_valid_coverage: 0.5     # scene mode only — drop scenes below this ROI cloud-free fraction

output:
  dir: ./output
  format: COG                   # COG | GeoTIFF
  nodata: -9999
  dtype: float32                # float32 | int16 | uint16
  crs: null                     # null = auto-UTM
  compression: LZW              # LZW | DEFLATE | ZSTD | none
  structure:
    timeseries_mode: false
    band_interleave: BIP        # BIP | BIL | BSQ
    filename_template: "tile_{tile_id}_{window_label}"
    separate_indices: true      # default true — indices written to sibling files

tiling:
  max_tile_bytes: null          # null = auto from pixel budget
  overlap_px: 2
  skip_coverage_threshold: 0.05
  grid_snap_m: 100

pipeline:
  concurrency: 16
  max_retries: 6
  retry_base_delay: 1.0
  timeout_per_tile: 120

asset:
  project: my-ee-project        # required
  base_path: users/me/geedl_assets
  auto_cleanup: false

auth:                           # NEW — picks the EE init path
  method: browser               # browser | service_account
  service_account_email: null   # required when method == service_account
  key_file: null                # required when method == service_account

hooks:
  pre_download: null            # "module.path:fn"
  post_tile: null
  post_job: null
```

The full field index (with types) lives at the bottom of [.claude/CLAUDE.md](.claude/CLAUDE.md).

---

## 5. Dataset registry (`datasets/registry.yaml`)

Five datasets ship today. Each entry is a flat dict — adding a dataset means
adding one YAML entry, optionally one cloud-mask function, and optionally
extending `BAND_MAP` in `indices/optical.py`.

```yaml
sentinel-2:
  collection: COPERNICUS/S2_SR_HARMONIZED
  bands:
    B1: {...}  B2: {...}  ...  B12: {...}
    SCL: {desc: "Scene class", res: 20, scaled: false, internal: true}
  native_res: 10
  cloud_mask: s2_scl_mask
  scale_factor: 0.0001
  offset: 0.0
  date_property: system:time_start
  slc_off_date: null

sentinel-1:
  collection: COPERNICUS/S1_GRD
  bands: {VV, VH, angle}
  cloud_mask: null
  scale_factor: null
  extra_filters:
    - {property: instrumentMode,       value: IW}
    - {property: orbitProperties_pass, value: DESCENDING}
  composite_strategy_override: mosaic   # median is meaningless for SAR backscatter

landsat-7:  # SR_B1..SR_B5, SR_B7, QA_PIXEL — slc_off_date: 2003-05-31, loss ~22%
landsat-8:  # SR_B2..SR_B7, QA_PIXEL
landsat-9:  # SR_B2..SR_B7, QA_PIXEL
```

Per-band flags:

- `scaled: false` — skip scale/offset multiplication (kept as integer codes; SCL, QA_PIXEL).
- `internal: true` — excluded from `select=null` default expansion; available if explicitly listed.

---

## 6. Index engine

Indices are pure functions registered with the `@index` decorator. Adding a new
index touches **one file**: `indices/optical.py` or `indices/sar.py`.

```python
# indices/__init__.py
_REGISTRY: dict[str, dict] = {}

def index(name, datasets=None):
    def deco(fn):
        if name in _REGISTRY:
            raise ValueError(f"index {name!r} already registered")
        _REGISTRY[name] = {"fn": fn, "datasets": datasets}
        return fn
    return deco

def apply_indices(image, names, dataset) -> ee.Image:
    for name in names:
        entry = _REGISTRY[name]                 # KeyError if unknown
        if entry["datasets"] and dataset not in entry["datasets"]:
            raise ValueError(...)
        image = image.addBands(entry["fn"](image, dataset))
    return image
```

Helpers: `supports(name, dataset)` and `list_indices(dataset=None)` back the
`geedl indices` / `geedl validate` CLI commands.

`cli.py` imports `geedl.indices.optical` and `geedl.indices.sar` at startup so
their decorators register before any job runs. **No other module imports specific
index modules.**

Currently registered:

| Index | Optical | SAR |
|---|---|---|
| NDVI, NDWI, NDMI, NBR, NDSI, SAVI | S2 + L7 + L8 + L9 | — |
| EVI, BSI | S2 + L8 + L9 (no L7 — no blue/SWIR in same scaling family) | — |
| RVI, VV_VH_RATIO | — | S1 |

---

## 7. Time window system

Window generation lives in `utils/windows.py` and is a **pure function** — no EE,
no I/O, no logging. Tests run without credentials.

```python
@dataclass(frozen=True)
class Window:
    start: date
    end: date
    label: str
    scene_ids: tuple[str, ...] | None = None   # scene-mode pinning
```

`generate_windows(start, end, type, size, step, anchor, label_format)` returns
`list[Window]` for every type **except** `scene`, where it returns `None` — the
sentinel value that tells the runner to call into `pipeline/scenes.py` instead.

Window types:

| Type | Notes |
|---|---|
| `full_range` | One window covering `[start, end]` |
| `calendar_year` | Jan 1 → Dec 31 per year, clipped to range |
| `calendar_month` | 1st → last day of month, clipped to range |
| `fixed_days` | `size` days per window, stepped by `step` (default = size). Windows are **whole** — a partial trailing window is dropped (`full_end > end → break`). |
| `scene` | One window **per scene date**, populated from EE; carries `scene_ids` |

Window labels come from `label_format` (strftime) applied to the anchor date.
**No other module constructs folder/file names from dates.**

---

## 8. Scene mode (`pipeline/scenes.py`)

EE-aware; not pure. Lives next to `compositor.py` so `windows.py` stays clean.

Workflow when `composite.window.type: scene`:

1. `enumerate_scenes(dataset_spec, roi_fc, start, end)` — fetches scene IDs and
   acquisition timestamps from EE.
2. If empty → `suggest_nearest_dates(...)` searches ±365 days, then ±730. Raises
   `NoScenesAvailableError(dataset, requested, suggestions)` — the CLI catches it
   and prints the suggestions as `date.start` / `date.end` candidates.
3. If `cloud_mask.enabled` and `min_valid_coverage > 0`,
   `scene_roi_coverage(...)` computes per-scene ROI cloud-free fraction via
   `reduceRegion` at 10× native resolution. `filter_scenes_by_coverage(...)`
   drops scenes below the threshold and logs each kept/dropped scene.
4. If everything is dropped → `_suggest_cleaner_dates` (in `runner.py`) probes
   nearby dates to find ones whose best scene clears the coverage bar (capped at
   12 EE coverage calls), re-raises `NoScenesAvailableError` with that filtered
   list.
5. `scenes_to_windows(scenes, label_format)` groups scenes per date and emits
   `Window(..., scene_ids=(...))`. `compositor.build_collection` sees `scene_ids`
   and builds the collection from those exact assets (not date+bounds, which
   would silently re-include rejected scenes).
6. The runner forces `cfg.composite.strategy = "mosaic"` — single-scene days
   "mosaic" to themselves; multi-scene days combine tile footprints across the
   ROI (single S2 swaths rarely cover a province-sized AOI).

Landsat 7 post-2003 with `type: scene` is rejected at validation time (single
SLC-off scenes are heavily gapped — see §10).

---

## 9. ROI pipeline

### 9.1 Load + reproject

```
shapefile → GeoDataFrame → feature_mode (union | split | filter) → reproject to auto-UTM
```

`feature_mode: split` and `filter` are accepted in the schema; current
implementation runs `union` semantics end-to-end (everything fuses into one ROI
geometry before tiling). Per-feature output remains a v0.2 item — see §17.

Auto-UTM is derived from the ROI centroid. All tiling and geometry math works in metres.

### 9.2 Simplify before upload

```python
tolerance_m = resolution_m * 0.1   # 1 m for S2, 3 m for Landsat
simplified  = roi.simplify(tolerance=tolerance_m, preserve_topology=True)
```

The original (unsimplified) geometry is used for local tile classification.
The simplified geometry is what gets uploaded as the EE asset.

### 9.3 EE asset upload

```
sha1(shapefile bytes)[:10] → deterministic asset path
  → check ee.data.getAsset(asset_id)
    → yes: reuse, log reuse
    → no:  upload + block until COMPLETED (raise on FAILED)
→ persist asset_id in checkpoint DB
→ return ee.FeatureCollection(asset_id)
```

- Asset ID: `{cfg.asset.base_path}/roi_{sha1[:10]}`.
- Asset upload blocks job start.
- `auto_cleanup: true` deletes the asset after `post_job` finishes.
- On resume: asset_id is read from the checkpoint DB; re-upload skipped entirely.

### 9.4 Tiling (`roi/tiler.py` + `utils/budget.py`)

Tile size is back-calculated from a **pixel budget** sized for EE's
`computePixels` cap:

```python
# utils/budget.py
BUDGET_BYTES = 20_000_000   # 20 MB — sized to survive EE's worst-case 2.25×
HEADROOM     = 0.80         # internal reprojection oversampling on multi-zone ROIs.
                            # 20 MB * 0.8 * 2.25 ≈ 36 MB << 48 MB EE cap.

def safe_tile_side_px(n_bands, bytes_per_pixel=4):
    return int(((BUDGET_BYTES / (n_bands * bytes_per_pixel)) * HEADROOM) ** 0.5)
```

`n_bands` is `len(bands.select) + len(indices)` — both contribute to the
returned array's depth.

`generate_tiles(...)` then:

1. Computes `side_m = safe_tile_side_m(n_bands, resolution_m)`. If
   `cfg.tiling.max_tile_bytes` is set, scales by `sqrt(max_tile_bytes / 40e6)`
   (factor against the legacy 40 MB reference; not against the active 20 MB
   budget — kept for backward CLI behaviour, never the default path).
2. Floors at `resolution_m * 32` (no degenerate tiny tiles).
3. Re-aligns to whole pixels.
4. Snaps grid origin down to the nearest `grid_snap_m` multiple → same ROI +
   same resolution always produces identical tile boundaries across runs.
5. Walks cells, classifies, attaches Hilbert distance, sorts by it.

**Tile classification (`_classify`):**

| Class | Condition | EE request | Server clip (`img.clip`) | Local rasterio mask |
|---|---|---|---|---|
| `inside` | All 4 corners in ROI | full tile rect + overlap | no | no |
| `partial` | Mixed corners, coverage ≥ `skip_coverage_threshold` | full tile rect + overlap | yes | yes (to `tile.geom`, not the ROI — see writer) |
| `edge` | Mixed corners, coverage < threshold | — | — | skipped (returned tile list omits this) |
| `outside` | All 4 corners out **and** centroid out **and** no intersection | — | — | skipped |

Coverage ratio: `tile.geom.intersection(roi).area / tile.geom.area`.

**Why double-mask `partial`?** The EE clip saves bandwidth and trims the result
to ROI bounds; the local rasterio pass catches sub-pixel boundary drift from
floating-point CRS transforms. Local mask uses the **unbuffered** `tile.geom`
(not the ROI) — the ROI lives server-side and the EE clip has already trimmed
to the ROI boundary.

**Overlap buffer:** Each tile's *request geometry* is expanded by
`overlap_px × resolution_m` on all sides. The writer crops the buffer off before
emitting the final tile so seams disappear at merge time without duplicating pixels.

**Tile ordering:** Hilbert space-filling curve. Spatially adjacent tiles
download together → EE internal cache stays warm → lower per-tile latency.

**Masked-pixel materialisation:** Before `computePixels`, the runner calls
`image = image.unmask(cfg.output.nodata)`. Without it, EE would return `0` for
cloud-masked / out-of-ROI / native-gap pixels regardless of the GeoTIFF nodata tag.

---

## 10. Landsat 7 SLC-off handling

**Strategy: `multi_temporal` only.** No focal fill — it introduces blur that
corrupts index calculations.

Mechanism:

1. `landsat_qa_mask` already flags SLC-off gap pixels as nodata via `QA_PIXEL`
   fill bits. No special code path.
2. The compositor stacks all in-window scenes and reduces them with `median`
   (or `mosaic`). With ≥ 3 scenes per window, gap positions differ across orbits
   and the median fills ~97% of pixels naturally.
3. The registry records `slc_off_date: 2003-05-31` and
   `slc_off_coverage_loss: 0.22`. `geedl validate` warns at job start:

```python
if ds.slc_off_date and cfg.date.start > ds.slc_off_date:
    if cfg.composite.window.type == "scene":
        raise BadParameter("L7 post-2003 with type=scene produces gapped output.")
    if cfg.composite.window.type == "fixed_days":
        approx = cfg.composite.window.size / 16
        if approx < cfg.dataset.slc_off.min_scenes_warning:
            warn(f"~{approx:.1f} scenes per window; widen or use L8/L9.")
```

| Window size | Approx. scenes | Gap fill |
|---|---|---|
| 16 days | ~1 | Poor — raw gaps visible |
| 32 days | ~2 | Moderate |
| 48 days | ~3 | Good — ~97% coverage |
| 64 days | ~4 | Excellent |

---

## 11. Compositing pipeline (`pipeline/compositor.py`)

```python
def build_window_image(dataset_cfg, dataset_spec, strategy, window, roi_fc):
    col = build_collection(dataset_cfg, dataset_spec, window, roi_fc)
    composited = composite(col, strategy, dataset_spec)
    return apply_bands_and_indices(composited, dataset_cfg, dataset_spec)
```

`build_collection`:
- If `window.scene_ids` is set → build from `ee.Image(f"{collection}/{sid}")` for each ID.
- Else → `ImageCollection(...).filterDate(...).filterBounds(...)` then apply
  every `extra_filter` from the registry (S1 orbit mode etc.).
- Then `.map(mask_fn)` if cloud masking is enabled.

`composite(col, strategy, spec)`:
- `dataset_spec.composite_strategy_override` **wins** over the requested
  strategy. Sentinel-1 always gets `mosaic` — no way to configure otherwise.
- Supported: `median | mean | mosaic | none` (`none` returns `col.first()`).

`apply_bands_and_indices`:
- Select declared bands.
- Apply `scale_factor` + `offset` only to bands flagged `scaled: true`. SCL /
  QA_PIXEL keep integer codes.
- Compute indices via `apply_indices` (declaration order).
- Rename index output bands if `output_band != name`.
- Reorder per `bands.order` + index `position` (`after_bands` | `before_bands` | int).
- Apply `bands.rename` map last.
- Returns `(image, ordered_band_names)`.

---

## 12. Download pipeline (`pipeline/downloader.py` + `scheduler.py`)

### 12.1 API call

`ee.data.computePixels()` — returns raw bytes; no export task, no bucket, no Drive.

```python
params = {
    "expression": ee.serializer.encode(image),
    "fileFormat": "NPY",
    "bandIds":   ordered_band_list,
    "grid": {
        "crsCode": f"EPSG:{tile_epsg}",
        "affineTransform": {
            "scaleX":  resolution_m,  "shearX": 0, "translateX": tile_origin_x,
            "shearY":  0, "scaleY":  -resolution_m, "translateY": tile_origin_y,
        },
        "dimensions": {"width": tile_width_px, "height": tile_height_px},
    },
}
raw = ee.data.computePixels(params)
arr = np.load(io.BytesIO(raw))           # (height, width) structured → (bands, h, w)
```

### 12.2 Concurrency model

- `asyncio` event loop coordinates work; `pipeline/scheduler.Scheduler` exposes:
  - `run(items, worker)` — bounded by `asyncio.Semaphore(concurrency)`, fan-out via `asyncio.as_completed`.
  - `run_blocking(fn, ...)` — dispatches sync EE calls to a `ThreadPoolExecutor(max_workers=concurrency)`.
- Sync `computePixels` is **always** offloaded via `run_blocking` — never called inline.
- Default concurrency: 16. EE quota guidance: ≤ 32 simultaneous.
- A failing worker logs and swallows its exception so sibling tiles keep running;
  the checkpoint records the failure.

### 12.3 Retry logic (`utils/retry.py`)

Exponential backoff + full jitter, wrapped via `with_retry(coro, max_attempts, base_delay, retryable, label)`.

| Error | Retried? |
|---|---|
| EE messages containing `rate limit / 429 / quota / too many` | yes (`RetryableError`) |
| EE messages containing `500 / 502 / 503 / internal / timeout / deadline` | yes (`RetryableError`) |
| `EmptyTileError` from validator | yes — empty array from EE may transiently happen |
| `TileShapeError` | no — mark `failed`, log full params |
| HTTP 400 / 401 / 403 / `ConfigError` / `AssetUploadError` | no — fail loud |

All retries flow through `utils/retry.py` — never `time.sleep` or `asyncio.sleep` inline.

---

## 13. Write pipeline

### 13.1 Two-stage output

Downloaded tiles are **staged** under `output/.tmp/{dataset}/{window_label}/`
(plus per-index sibling dirs `_NDVI/`, `_EVI/`, etc. when
`separate_indices: true`). After every tile completes, the runner calls
`_finalize_outputs` which uses `rasterio.merge` to mosaic each window's tiles
into one COG per ROI/window:

```
output/
  {dataset}/
    {job_name}_{window_label}.tif         # merged main bands
    {job_name}_{window_label}.json        # STAC sidecar (4326 footprint)
    {job_name}_{window_label}_NDVI.tif    # one per separated index
    {job_name}_{window_label}_NDVI.json
  job.yaml                                # verbatim resolved config (after pydantic validation)
  checkpoint.db
  catalog.parquet                         # written once at end, never incrementally
```

Merge step (`_merge_window`):

1. `rasterio.merge` on all `.tif` in the window dir → in-memory mosaic.
2. If `clip_geom` is given (always the ROI in the runner) → re-mask via
   `MemoryFile` + `rasterio.mask` to crop tightly to the ROI boundary.
3. Apply compression / COG profile, write to `{final}.tmp`, build overviews,
   `os.rename` to final path.
4. `_finalize_outputs` removes the `.tmp` staging tree on success.

STAC sidecars for the **merged** outputs are written from `_finalize_outputs`
in EPSG:4326 (via `pyproj.Transformer`); the per-tile sidecars written by
`_process_tile` describe each staging tile (kept in `.tmp` and discarded along
with it). The catalog parquet is built from the final sidecars only.

### 13.2 Atomic write (`io/writer.py`)

```
download → validate → write to {path}.tmp → (COG) build_overviews → close → os.rename(tmp, final)
```

`os.rename()` is atomic on POSIX. A crashed process leaves at most a `.tmp` file
— never a corrupt final file.

The writer also:
- Crops the `overlap_px` buffer off the array and shifts the transform.
- Applies `mask_geom` (when given) with `rasterio.features.geometry_mask`.
- Casts to the target `dtype` and applies `nodata`.
- Embeds per-band names as GeoTIFF band descriptions.

### 13.3 Per-tile validation (`pipeline/validator.py`)

1. Array shape matches `(bands, height, width)` — else `TileShapeError`.
2. Array is not all-nodata — else `EmptyTileError` (retried).
3. Value range plausible — log-only soft check.

### 13.4 Output structure flags

| Flag | Effect |
|---|---|
| `separate_indices: true` (default) | Spectral bands and each index go to sibling files: `..._{window}.tif`, `..._{window}_{IDX}.tif` |
| `separate_indices: false` | All bands + indices in one file per window |
| `timeseries_mode: true` | Reserved in schema; not part of the current finalize path |
| `band_interleave` | Carried in schema; writer always sets `interleave="pixel"` (BIP) |

### 13.5 Output format

COG by default: 256×256 internal tiles, LZW compression, overviews `2×/4×/8×`
with average resampling. Readable by QGIS, GDAL, stackstac, and any STAC client.

---

## 14. Checkpoint & resume (`io/checkpoint.py`)

### 14.1 Schema (SQLite + WAL)

```sql
CREATE TABLE job (
  config_hash   TEXT PRIMARY KEY,
  asset_id      TEXT NOT NULL,
  started_at    REAL NOT NULL,
  completed_at  REAL
);

CREATE TABLE tiles (
  id            TEXT PRIMARY KEY,    -- "{tile_grid_label}_{window_label}"
  status        TEXT NOT NULL,       -- pending | in_flight | done | failed
  attempts      INTEGER DEFAULT 0,
  last_error    TEXT,
  output_path   TEXT,
  completed_at  REAL
);
CREATE INDEX ix_tiles_status ON tiles(status);
```

### 14.2 Tile ID

`{col_letter}{row:02d}_{window_label}` → e.g. `A01_2023-01-15`, `B03_full`.
A job with 50 spatial tiles × 5 windows has 250 independently resumable units.

### 14.3 State machine

```
pending → in_flight → done
                    ↘ failed   (after max_retries; --retry-failed re-queues)
```

`claim(id)` atomically moves `pending|failed → in_flight` and bumps `attempts`.
`mark_done()` may be called **only after** `os.rename` to the final path
returns successfully.

### 14.4 Crash recovery

On startup, `recover_from_crash`:
- Lists every `in_flight` row.
- Deletes both `output_path` and `{output_path}.tmp` if they exist.
- Resets all `in_flight → pending`.

### 14.5 Config hash

`JobConfig.config_hash()` = `sha1` of the **canonical** YAML serialisation of
the resolved, validated config (`yaml.safe_dump(self.model_dump(mode="json"), sort_keys=True)`).
A mismatch against the stored hash means the job's intent has changed; treat as
a new job (the CLI offers `--fresh`).

### 14.6 CLI

```bash
geedl run      --config job.yaml                # run or resume
geedl run      --config job.yaml --retry-failed # also retry tiles in 'failed'
geedl run      --config job.yaml --fresh        # ignore checkpoint, start over
geedl validate --config job.yaml                # validate config + SLC-off / index guards
geedl status   --config job.yaml                # show done/pending/failed counts
geedl plan     --config job.yaml                # dry run; print windows + dataset info
geedl datasets                                  # list registry slugs
geedl indices  --dataset sentinel-2             # list indices supported for a dataset
geedl cleanup  --config job.yaml                # delete the EE ROI asset for this job
```

---

## 15. Progress reporting

`runner.py` owns the tqdm bars; nothing else touches them.

- One **overall** bar at `position=0` with total `len(pending_units)`.
- One **per-window** bar at `position=i` (sorted by window label), `leave=False`.
- `_bump_progress(progress, window_label, *, failed)` is the **only** entry point
  for updates. Called from every tile-terminal path in `_process_tile`:
  success, EmptyTileError (giving up after retries), TileShapeError, retry
  exhaustion. Failed-tile count is tracked outside tqdm and surfaced via
  `set_postfix_str("failed=N")` on the overall bar.
- All bars are closed in a `finally` block around `scheduler.run`.

This keeps progress out of the scheduler (which stays generic) and out of every
other module (which stays unaware of UI).

---

## 16. Authentication (`utils/auth.py`)

`ee.Initialize` is called from **exactly one place**:

```python
def initialize_ee(cfg: JobConfig) -> None:
    if cfg.auth.method == "service_account":
        creds = ee.ServiceAccountCredentials(cfg.auth.service_account_email, cfg.auth.key_file)
        ee.Initialize(credentials=creds, project=cfg.asset.project)
    else:
        ee.Initialize(project=cfg.asset.project)
```

Callers: `pipeline/runner._run` at job start; `cli.cleanup` before deleting the
asset. The pydantic `AuthConfig` validator rejects
`method: service_account` without both `service_account_email` and `key_file`,
so missing credentials surface at config-parse time, never inside EE code.

---

## 17. Output folder structure (current)

```
output/
  {dataset}/
    {job_name}_{window_label}.tif
    {job_name}_{window_label}.json
    {job_name}_{window_label}_{INDEX}.tif    # one per index when separate_indices=true
    {job_name}_{window_label}_{INDEX}.json
  job.yaml
  checkpoint.db
  catalog.parquet                            # at job completion only
```

Per-tile staging happens under `output/.tmp/{dataset}/{window_label}/` and is
removed once `_finalize_outputs` succeeds for that job.

---

## 18. STAC catalog

`io/catalog.py` writes STAC Item 1.0 JSON sidecars (one per merged GeoTIFF).
Custom fields use the `geedl:` prefix (`geedl:tile_class`, `geedl:coverage`,
`geedl:window_type`, `geedl:derived`, …).

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "{job_name}_{window_label}",
  "geometry": { ... ROI footprint in EPSG:4326 ... },
  "bbox": [...],
  "properties": {
    "datetime": "2023-01-15T00:00:00Z",
    "start_datetime": "...",
    "end_datetime": "...",
    "platform": "sentinel-2",
    "gsd": 10,
    "eo:bands": [{"name": "B2"}, {"name": "B3"}, ...],
    "geedl:window_type": "fixed_days"
  },
  "assets": { "data": { "href": "...", "type": "image/tiff; ... profile=cloud-optimized" } }
}
```

`catalog.parquet` aggregates all final sidecars. Sample:

```python
gdf = gpd.read_parquet("output/catalog.parquet")
gdf[gdf.tile_id.str.endswith("2023-01")].plot()
```

---

## 19. Key design decisions — consolidated

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Name | `geedl` | Short, memorable |
| 2 | ROI delivery to EE | Upload as EE asset once per job | Eliminates per-tile JSON payload; enables server-side clip by reference |
| 3 | Asset ID | sha1 of shapefile bytes → deterministic path | Same file reuses existing asset; different files never collide |
| 4 | Geometry simplification | 10% of native resolution before upload | Sub-pixel precision is meaningless; reduces upload + parse time |
| 5 | Tile size | Back-calculated from 20 MB pixel budget | Safe under EE's 48 MB cap + 2.25× worst-case reprojection oversampling |
| 6 | Tile classification | inside / partial / edge / outside | Eliminates EE requests for empty space — largest single speed win |
| 7 | Coverage threshold | Skip tiles < 5% ROI coverage | Not worth EE compute for nearly-empty borders |
| 8 | Server-side clip | `partial` tiles only | `inside` would waste EE compute; `edge`/`outside` are skipped entirely |
| 9 | Local mask | Always applied to `partial` tiles | Safety net for sub-pixel CRS boundary drift |
| 10 | Tile ordering | Hilbert space-filling curve | EE cache warmth; lower per-tile latency |
| 11 | Concurrency | Async semaphore + thread pool, default 16 | Comfortably under EE quota (~40); tune per project |
| 12 | Retry strategy | Exponential backoff + full jitter | Prevents thundering herd on rate-limit bursts |
| 13 | Write safety | `.tmp` → atomic `os.rename` | Crash never leaves corrupt file at real path |
| 14 | Resume model | SQLite (WAL); `in_flight` reset on startup | Full idempotency; safe to kill at any point |
| 15 | Download API | `computePixels` exclusively | Local-first; no GCS/Drive dependency |
| 16 | Wire format | NPY (numpy binary) | Fastest deserialization; no image codec |
| 17 | Output format | COG by default | QGIS/GDAL/stackstac native |
| 18 | Two-stage output | Stage to `.tmp/` then `rasterio.merge` per window | One COG per ROI/window beats N partial tiles for downstream tooling |
| 19 | Mask materialisation | `image.unmask(nodata)` before `computePixels` | Without it, EE emits 0 for masked pixels regardless of nodata tag |
| 20 | Scene mode | `windows.py` returns `None`; runner delegates to `scenes.py` | Keeps `windows.py` pure and credential-free |
| 21 | Scene-mode pinning | `Window.scene_ids` carries exact IDs | Coverage-filtered scenes are not re-derived by date+bounds |
| 22 | Window label | `label_format` strftime on anchor | Folder names unambiguous regardless of window shape |
| 23 | Band order | `bands.order` + per-index `position` | Fully declarative; no Python edit needed |
| 24 | Index extensibility | `@index` decorator; no core changes | Adding an index = adding one function |
| 25 | S1 compositing | Registry-level `composite_strategy_override: mosaic` | Median meaningless for SAR backscatter; enforced automatically |
| 26 | L7 SLC-off | `multi_temporal` only; validated at job start | Median compositor fills gaps at ≥ 3 scenes; no focal blur |
| 27 | Config identity | sha1 over canonical YAML of resolved config | Prevents silently resuming wrong job |
| 28 | Checkpoint granularity | `{tile_grid_label}_{window_label}` | Each spatial × temporal unit resumable |
| 29 | Auth | `auth.method: browser | service_account`; single `initialize_ee` call site | Switchable without touching code |
| 30 | Progress | tqdm overall + per-window; updated via `_bump_progress` only | UI concern isolated to the runner |
| 31 | AI agent interface | YAML is complete job spec; hooks via `"module:fn"` | Agents refactor jobs by editing config alone |

---

## 20. Known limitations & future work

**v0.2 scope:**

- **Single machine.** Async pipeline is one process. A Celery/Ray backend is
  architecturally compatible (tile manifest + checkpoint DB are the right
  abstraction) but out of scope.
- **`feature_mode: split` / `filter` accepted in schema, not yet wired through
  the runner.** All features are unioned today. Per-feature output is a v0.3 item.
- **Landsat 7 SLC-off:** `multi_temporal` only. `focal_fill` is explicitly
  excluded — it blurs and corrupts index calculations.
- **No GUI.** CLI only. A FastAPI + htmx dashboard is a plausible v0.4 addition.
- **`timeseries_mode` is in the schema but not wired through the finalize
  step.** Per-window mosaics are written; multi-window stacking remains future work.

**Known data caveats:**

- Very narrow windows with L7 post-2003 will have residual gaps even after
  compositing. `geedl validate` warns; the user must widen the window or use L8/L9.
- Sentinel-1 `mosaic` takes the first valid pixel; for true multi-temporal
  backscatter averaging users should reduce themselves via the `post_tile` hook.
- Landsat C2 scaling (`× 0.0000275 − 0.2`) is applied by default. With
  `dtype: int16` values round after scaling — `geedl validate` warns.
