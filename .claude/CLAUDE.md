# CLAUDE.md — geedl

This file is the authoritative guide for Claude Code working on geedl.
Read it fully before writing any code. Re-read the relevant section before
touching any module.

---

## What geedl is

**geedl** (GEE Downloader) is a local-first, resumable, high-throughput CLI tool
for downloading satellite imagery from Google Earth Engine directly to disk —
no Google Cloud Storage, no Google Drive.

Users point it at a shapefile (their ROI), a dataset slug, a date range, and a
set of indices. geedl tiles the geometry, downloads each tile via
`ee.data.computePixels()`, and writes Cloud-Optimized GeoTIFFs locally.

The full design rationale lives in `GEEDL_DESIGN.md`. When in doubt about a
design decision, that document is the source of truth, not intuition.

---

## Non-negotiable constraints

These are hard rules. Do not work around them, do not ask if they apply.

1. **No Google Cloud Storage. No Google Drive.** All data flows through
   `ee.data.computePixels()` directly to local disk. Never introduce an export
   task, a GCS bucket, or a Drive folder.

2. **All writes are atomic.** Always write to `{path}.tmp.tif` first, then
   `os.rename()` to the real path. Never write directly to the final path.
   A killed process must never leave a corrupt file at a real output path.

3. **The YAML config is the single source of truth.** Every structural decision
   (band order, output shape, time windows, composite strategy) must be
   addressable from the config file. If a behavior cannot be changed via YAML,
   that is a design defect.

4. **Checkpoint before and after, never during.** Mark a tile `in_flight` before
   starting its download. Mark it `done` only after the atomic rename completes
   successfully. Never mark done before the file is safely on disk.

5. **The index engine is plugin-only.** Never hard-code index logic inside the
   pipeline. All indices go through the `@index` decorator in `indices/__init__.py`.
   Adding an index = adding one decorated function. Nothing else changes.

6. **Landsat 7 SLC-off is handled by compositing only.** No focal fill, no
   interpolation, no special download path. The QA mask flags gaps; the median
   compositor fills them across scenes. If a user's window is too narrow to fill
   gaps, warn at validation time — never at runtime.

7. **Sentinel-1 composite strategy is always `mosaic`.** The registry entry
   has `composite_strategy_override: mosaic`. Never let a user configure `median`
   for Sentinel-1 — it is physically meaningless for SAR backscatter.

---

## Engineering ethos

Modular, clean, minimal, optimized. **No overengineering.** Apply on every change:

- **Prefer editing over creating.** Don't add a new file/module/class if an
  existing one fits. Three similar lines beat a premature abstraction.
- **Build for the task, not the hypothetical.** No speculative flags, no
  "might need later" config knobs, no extension points without a second caller.
- **No defensive scaffolding inside trust boundaries.** Validate at the YAML
  edge (config schema) and at the EE/IO edge. Trust internal callers — skip
  redundant `isinstance` checks, fallback branches, and try/except that just
  re-raises.
- **No backwards-compatibility shims.** Change call sites; don't leave
  deprecated wrappers, alias re-exports, or `# removed` comments.
- **No dead code.** Delete unused params, helpers, and imports rather than
  prefixing with `_` or leaving TODOs.
- **Comments earn their keep.** Default to none. Write one only when the *why*
  is non-obvious (a workaround, an EE quirk, a checkpoint invariant). Never
  restate the code.
- **One concern per module.** If a function needs to know about both EE and the
  filesystem, it belongs in `pipeline/` — not in `utils/` or `datasets/`.
- **Pure where possible.** `utils/windows.py`, `roi/tiler.py` classification,
  `pipeline/compositor.generate_windows()` stay free of I/O, logging, and EE
  calls so they remain trivially testable.
- **Optimize only with evidence.** Don't add caching, batching, or parallelism
  layers until a profile or a failing job demands them. The existing semaphore
  + thread pool is the concurrency story — don't bolt on another.
- **One way to do a thing.** If two code paths converge on the same outcome,
  pick one and delete the other. Same for two config fields that overlap.

When in doubt: write less. A reviewer should be able to justify every line.

---

## Repository layout

```
geedl/
  geedl/
    cli.py              # typer CLI — entry point only, no logic here
    config.py           # pydantic v2 schema for the full YAML config
    datasets/
      registry.yaml     # all dataset definitions — edit here to add datasets
      registry.py       # loads registry.yaml; never mutate at runtime
      cloud_masks.py    # one function per sensor mask profile
    indices/
      __init__.py       # @index decorator + apply_indices()
      optical.py        # all optical indices (NDVI, EVI, NDWI, ...)
      sar.py            # all SAR indices (RVI, ...)
    roi/
      loader.py         # shapefile → GeoDataFrame, auto-UTM reproject
      simplifier.py     # vertex reduction before EE asset upload
      tiler.py          # grid generation + tile classification
      asset_manager.py  # EE asset upload, reuse, cleanup
    pipeline/
      scheduler.py      # asyncio task runner + semaphore
      downloader.py     # ee.data.computePixels wrapper
      compositor.py     # window generation + image compositing
      validator.py      # per-tile array integrity checks
    io/
      writer.py         # atomic COG/GeoTIFF write
      catalog.py        # STAC sidecar + GeoParquet index
      checkpoint.py     # SQLite state machine
    utils/
      crs.py            # auto-UTM from centroid
      retry.py          # exponential backoff with full jitter
      budget.py         # pixel budget calculator
      windows.py        # time window generator
  tests/
    fixtures/           # small shapefiles + VCR cassettes
  GEEDL_DESIGN.md       # full design doc — read before touching architecture
  CLAUDE.md             # this file
  pyproject.toml
```

---

## Module contracts

Each module owns exactly one concern. Do not let concerns bleed across boundaries.

### `config.py`
- Owns: pydantic schema for the entire YAML. All fields documented with descriptions.
- Does not: validate EE-specific constraints (that's `validator.py`) or compute
  derived values (that's each module's responsibility on first use).
- Key types to keep stable: `BandsConfig`, `WindowConfig`, `OutputStructureConfig`,
  `SlcOffConfig`, `HooksConfig`.

### `datasets/registry.py`
- Owns: loading `registry.yaml` into typed dataclasses. Providing `get(slug)`.
- Does not: mutate registry entries at runtime. Does not know about the job config.
- If a dataset needs special behavior, encode it in `registry.yaml` as a field
  (e.g. `composite_strategy_override`), not as an `if dataset == "sentinel-1"` branch.

### `datasets/cloud_masks.py`
- Owns: one `ee.Image → ee.Image` function per mask profile.
- Function signature: `def mask_fn(image: ee.Image) -> ee.Image`
- Named exactly as referenced in `registry.yaml` under `cloud_mask:`.

### `indices/__init__.py`
- Owns: the `@index` decorator and `apply_indices()`.
- `apply_indices(image, names, dataset)` calls each index fn in declaration order
  and `addBands` the result. It raises `ValueError` if a requested index is not
  registered or not supported for the dataset.
- Never import specific index modules here — they register themselves on import.
  `cli.py` imports `indices.optical` and `indices.sar` at startup to trigger registration.

### `roi/tiler.py`
- Owns: grid generation, tile classification, Hilbert ordering.
- Tile class enum: `inside | partial | edge | outside`.
- `edge` = partial AND coverage ratio < `config.tiling.skip_coverage_threshold`.
- `outside` = all corners outside AND centroid outside.
- `partial` tiles get both server-side clip (`img.clip(roi_fc)`) AND local rasterio mask.
- `inside` tiles get neither.
- Returns: `list[Tile]` sorted by Hilbert index.

### `roi/asset_manager.py`
- Owns: EE asset upload lifecycle.
- Asset ID = `{config.asset.base_path}/roi_{sha1(shapefile_bytes)[:10]}`.
- Always check `ee.data.getAsset(asset_id)` before uploading.
- Block until the upload task reaches `COMPLETED` or raises on `FAILED`.
- Store `asset_id` in the checkpoint DB immediately after upload succeeds.
- On resume: read `asset_id` from DB, skip upload entirely.

### `pipeline/compositor.py`
- Owns: `generate_windows()` and `composite()`.
- `generate_windows()` is a pure function — no EE calls, no I/O, no side effects.
  Given config, it returns `list[Window]`. Tests must be able to call it with no
  EE credentials.
- `composite()` applies `composite_strategy_override` from registry before using
  the config strategy. Sentinel-1 always gets `mosaic`.

### `pipeline/scheduler.py`
- Owns: asyncio event loop, semaphore, `asyncio.as_completed` fan-out.
- Does not: know about EE, tiles, or files. It receives a list of coroutines and
  runs them with concurrency control.
- The `ee.data.computePixels` call (sync) must be wrapped in
  `loop.run_in_executor(thread_pool, ...)` — never called directly in async context.

### `pipeline/downloader.py`
- Owns: constructing the `computePixels` params dict and making the call.
- Wire format is always `NPY`. Never change this to GeoTIFF or PNG.
- Returns: `np.ndarray` of shape `(bands, height, width)`.
- Does not: write files, update checkpoints, or apply the local rasterio mask.

### `pipeline/validator.py`
- Owns: per-tile array checks before writing.
- Checks in order: shape matches expected, not all-nodata, value range plausible.
- All-nodata: raise `EmptyTileError` → scheduler retries.
- Shape mismatch: raise `TileShapeError` → scheduler marks `failed`, does not retry.
- Value range: log warning only, never block the write.

### `io/writer.py`
- Owns: atomic COG/GeoTIFF write + local rasterio mask for `partial` tiles.
- Always: write to `.tmp.tif` → call `dst.build_overviews()` → close → `os.rename()`.
- Band metadata (names, descriptions) written as GeoTIFF tag per band.
- `timeseries_mode: true` stacks all windows into one file — writer receives
  the full `list[(window, array)]` in that case.

### `io/checkpoint.py`
- Owns: SQLite schema, state transitions, crash recovery.
- Tile ID format: `{col_letter}{row_number}_{window_label}` e.g. `A01_2023-01-15`.
- On startup: reset all `in_flight` → `pending`, delete their output files.
- `mark_done()` must be called only after `os.rename()` returns successfully.
- Config hash is `sha1(canonical_yaml_bytes)` — computed from the resolved,
  validated config object serialized back to YAML, not the raw file bytes.

### `io/catalog.py`
- Owns: writing STAC Item JSON sidecars and the final `catalog.parquet`.
- STAC extension prefix: `geedl:` for all custom fields.
- `catalog.parquet` is written only after all tiles are `done` — never incrementally.

---

## Config schema rules

When adding or changing config fields:

- Every field needs a `description=` in the pydantic `Field()`.
- Boolean fields that change output structure default to `false`.
- All string enums use `Literal[...]` types — no bare strings.
- Nullable fields that have computed defaults (e.g. `max_tile_bytes: null`)
  use `Optional[X] = None` and the computation lives in the consuming module,
  not in config validation.
- The `hooks` block fields accept `Optional[str]` in format `"module.path:function_name"`.
  The hook loader resolves these at job start, not at config parse time.

---

## Adding a new spectral index

1. Open `indices/optical.py` (or `indices/sar.py` for SAR).
2. Add the band name mapping to `BAND_MAP` if the index uses bands not already there.
3. Write the function:
   ```python
   @index("MYINDEX", datasets=["sentinel-2", "landsat-8", "landsat-9"])
   def myindex(img: ee.Image, ds: str) -> ee.Image:
       b = BAND_MAP[ds]
       return img.expression("...", {...}).rename("MYINDEX")
   ```
4. That's it. No changes to registry, config schema, compositor, or writer.
5. Add a test in `tests/test_indices.py` that calls the function with a mock
   `ee.Image` and asserts the output band is named correctly.

---

## Adding a new dataset

1. Add an entry to `datasets/registry.yaml` with all required fields:
   `collection`, `bands`, `native_res`, `cloud_mask`, `scale_factor`,
   `date_property`, `slc_off_date`.
2. If the dataset needs a custom cloud mask, add the function to `cloud_masks.py`
   and reference it by name in `registry.yaml`.
3. If the dataset needs any composite override (like Sentinel-1's `mosaic`),
   add `composite_strategy_override: mosaic` to its registry entry.
4. Update `BAND_MAP` in `indices/optical.py` if optical indices should support it.
5. Add a validation test that the registry entry loads cleanly.
6. No changes to pipeline, scheduler, downloader, or writer.

---

## Time window rules

- `generate_windows()` in `utils/windows.py` is a pure function. Keep it that way.
  It must be testable with no EE credentials, no filesystem, no side effects.
- `type: scene` returns `None` — this is the sentinel value that tells the
  compositor to bypass windowing and iterate EE scenes directly.
- Window labels come from `label_format` applied to the anchor date.
  Never construct folder names anywhere else in the codebase.
- The `step` field allows overlapping windows (`step < size`). The scheduler
  handles the resulting duplicate spatial tiles across windows correctly because
  tile IDs include the window label.

---

## Tile classification rules

Never change the classification thresholds in code. They come from config:

```python
cfg.tiling.skip_coverage_threshold   # default 0.05 — edge/outside boundary
cfg.tiling.overlap_px                # default 2 — added to request geometry
cfg.tiling.grid_snap_m               # default 100 — grid origin snapping
```

The classification logic itself is not configurable — only the thresholds.
`inside` vs `partial` is always determined by corner-in-polygon test + centroid check.

---

## Error handling conventions

| Error type | Action |
|---|---|
| `EmptyTileError` | Retry (tile may have had no scenes in window) |
| `TileShapeError` | Mark `failed`, do not retry, log full params |
| `RateLimitError` (HTTP 429) | Retry with backoff |
| `ServerError` (HTTP 500/503) | Retry with backoff |
| `AuthError` (HTTP 401/403) | Raise immediately, abort job |
| `BadRequestError` (HTTP 400) | Mark `failed`, do not retry, log EE error message |
| `ConfigError` | Raise at validation time, before any EE calls |
| `AssetUploadError` | Raise, abort job — nothing can proceed without the asset |

All retryable errors go through `utils/retry.py`. Never write `time.sleep` or
`asyncio.sleep` retry loops inline.

---

## Testing conventions

- Use `pytest-recording` (VCR) to record and replay EE HTTP responses.
  Never make live EE calls in CI.
- Fixtures live in `tests/fixtures/`. Small shapefiles only (< 10 KB).
- `generate_windows()` must have 100% branch coverage — it's pure and testable.
- `tiler.py` classification logic must have a test for each of the four classes.
- Atomic write test: write a tile, kill the process mid-write (mock `os.rename`
  to raise), assert no corrupt file at the real path.
- Checkpoint recovery test: insert an `in_flight` tile, run `recover_from_crash()`,
  assert tile is `pending` and output file is deleted.

---

## What not to do

- Do not add `if dataset_name == "..."` branches in pipeline code.
  Dataset-specific behavior belongs in `registry.yaml` or `cloud_masks.py`.
- Do not write index logic inside `compositor.py` or `downloader.py`.
  Indices are applied in `compositor.py` via `apply_indices()` only.
- Do not construct file paths as strings. Use `pathlib.Path` throughout.
- Do not log inside `utils/windows.py`, `roi/tiler.py`, or any pure function.
  Pure functions raise exceptions; callers log.
- Do not catch bare `Exception` in the scheduler. Catch specific error types
  so unknown errors surface immediately rather than being silently retried.
- Do not write `catalog.parquet` incrementally. Write it once at job completion.
- Do not store the raw shapefile bytes in the checkpoint DB. Store only the
  asset ID and config hash.
- Do not call `ee.Initialize()` anywhere except `cli.py`. Modules receive EE
  objects as arguments — they do not initialize EE themselves.

---

## Dependency rules

The dependency graph is strictly layered. Lower layers must not import from upper layers.

```
cli.py
  └── config.py
  └── pipeline/scheduler.py
        └── pipeline/downloader.py
              └── datasets/registry.py
              └── indices/__init__.py
        └── pipeline/compositor.py
              └── utils/windows.py
              └── datasets/registry.py
        └── pipeline/validator.py
        └── io/writer.py
        └── io/checkpoint.py
  └── roi/tiler.py
        └── utils/crs.py
        └── utils/budget.py
  └── roi/asset_manager.py
        └── roi/simplifier.py
        └── utils/retry.py
  └── io/catalog.py
```

`utils/` modules have no internal imports from `geedl/` — they are pure utilities.
`datasets/` modules do not import from `pipeline/` or `roi/`.
`indices/` modules do not import from anywhere except `ee` and `indices/__init__.py`.

---

## Reference: full config field index

For quick lookup when editing config or writing tests.

```
job_name                          str
roi.path                          str (shapefile path)
roi.layer                         str | null
roi.feature_mode                  union | split | filter
roi.filter_expr                   str | null
roi.simplify_tolerance            float | "auto"
dataset.name                      str (registry slug)
dataset.bands.select              list[str] | null
dataset.bands.order               list[str] | null
dataset.bands.rename              dict[str,str] | null
dataset.bands.scale_factor        float | null
dataset.bands.offset              float
dataset.indices[].name            str
dataset.indices[].output_band     str | null
dataset.indices[].position        "after_bands" | "before_bands" | int
dataset.cloud_mask.enabled        bool
dataset.cloud_mask.profile        str | "auto"
dataset.cloud_mask.mask_shadow    bool
dataset.cloud_mask.mask_snow      bool
dataset.slc_off.strategy          "multi_temporal"
dataset.slc_off.min_scenes_warning int
date.start                        str (YYYY-MM-DD)
date.end                          str (YYYY-MM-DD)
composite.strategy                median | mean | mosaic | none
composite.window.type             fixed_days | calendar_month | calendar_year | full_range | scene
composite.window.size             int (days, fixed_days only)
composite.window.step             int | null
composite.window.anchor           start | end | center
composite.window.min_scenes       int
composite.window.label_format     str (strftime)
output.dir                        str
output.format                     COG | GeoTIFF
output.nodata                     float
output.dtype                      float32 | int16 | uint16
output.crs                        str | null
output.compression                LZW | DEFLATE | ZSTD | none
output.structure.timeseries_mode  bool
output.structure.band_interleave  BIP | BIL | BSQ
output.structure.filename_template str
output.structure.separate_indices bool
tiling.max_tile_bytes             int | null
tiling.overlap_px                 int
tiling.skip_coverage_threshold    float
tiling.grid_snap_m                int
pipeline.concurrency              int
pipeline.max_retries              int
pipeline.retry_base_delay         float
pipeline.timeout_per_tile         int
asset.project                     str
asset.base_path                   str
asset.auto_cleanup                bool
hooks.pre_download                str | null  ("module:fn")
hooks.post_tile                   str | null
hooks.post_job                    str | null
```