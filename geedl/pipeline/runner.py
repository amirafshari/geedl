"""Job runner — wires every layer together. The only place ee.Initialize is called."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import ee
import rasterio
import yaml
from tqdm import tqdm
from rasterio.enums import Resampling
from rasterio.merge import merge as rio_merge
from rasterio.transform import Affine
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform
import pyproj

from ..config import JobConfig
from ..datasets.registry import get as get_dataset
from ..io.catalog import write_catalog_parquet, write_stac_sidecar
from ..io.checkpoint import Checkpoint
from ..io.writer import write_tile
from ..roi.asset_manager import asset_id_for, delete_asset, upload_roi_asset
from ..roi.loader import load_roi
from ..roi.simplifier import simplify_for_upload
from ..roi.tiler import Tile, generate_tiles
from ..utils.auth import initialize_ee
from ..utils.retry import RetryableError, with_retry
from ..utils.windows import Window, generate_windows
from . import compositor, downloader, validator
from .scheduler import Scheduler

log = logging.getLogger(__name__)


def _load_hook(spec: str | None) -> Callable[..., Any] | None:
    if spec is None:
        return None
    module_path, fn_name = spec.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, fn_name)


def _bump_progress(
    progress: dict[str, Any] | None,
    window_label: str,
    *,
    failed: bool,
) -> None:
    if progress is None:
        return
    progress["overall"].update(1)
    bar = progress["windows"].get(window_label)
    if bar is not None:
        bar.update(1)
    if failed:
        progress["failed"] += 1
        progress["overall"].set_postfix_str(f"failed={progress['failed']}", refresh=False)


def _classify_ee_error(exc: BaseException) -> Exception:
    msg = str(exc).lower()
    if any(s in msg for s in ("rate limit", "429", "exceeded quota", "too many")):
        return RetryableError(str(exc))
    if any(s in msg for s in ("500", "502", "503", "internal", "timeout", "deadline")):
        return RetryableError(str(exc))
    return exc


async def _process_tile(
    tile: Tile,
    window: Window,
    *,
    cfg: JobConfig,
    dataset_spec,
    roi_fc: ee.FeatureCollection,
    epsg: int,
    output_root: Path,
    checkpoint: Checkpoint,
    scheduler: Scheduler,
    hooks: dict[str, Callable[..., Any] | None],
    progress: dict[str, Any] | None = None,
) -> None:
    tile_unit = f"{tile.grid_label}_{window.label}"
    if not checkpoint.claim(tile_unit):
        return

    resolution_m = dataset_spec.native_res
    minx, miny, maxx, maxy = tile.request_geom.bounds
    width_px = int(round((maxx - minx) / resolution_m))
    height_px = int(round((maxy - miny) / resolution_m))

    out_dir = output_root / ".tmp" / cfg.dataset.name / window.label
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = cfg.output.structure.filename_template.format(
        tile_id=tile.grid_label,
        window_label=window.label,
        dataset=cfg.dataset.name,
        date_start=cfg.date.start.isoformat(),
        date_end=cfg.date.end.isoformat(),
        strategy=cfg.composite.strategy,
    )
    out_path = out_dir / f"{fname}.tif"

    image, ordered_bands = compositor.build_window_image(
        cfg.dataset, dataset_spec, cfg.composite.strategy, window, roi_fc,
    )
    if tile.tile_class == "partial":
        image = image.clip(roi_fc)

    affine = (resolution_m, 0.0, minx, 0.0, -resolution_m, maxy)

    async def _fetch():
        try:
            return await asyncio.wait_for(
                scheduler.run_blocking(
                    downloader.download_tile,
                    image,
                    bands=ordered_bands,
                    epsg=epsg,
                    affine=affine,
                    width_px=width_px,
                    height_px=height_px,
                ),
                timeout=cfg.pipeline.timeout_per_tile,
            )
        except (downloader.EmptyTileError, downloader.TileShapeError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise _classify_ee_error(exc) from exc

    try:
        array = await with_retry(
            _fetch,
            max_attempts=cfg.pipeline.max_retries,
            base_delay=cfg.pipeline.retry_base_delay,
            retryable=(RetryableError, downloader.EmptyTileError),
            label=f"tile {tile_unit}",
        )
    except downloader.TileShapeError as exc:
        log.error("tile %s shape mismatch — not retried: %s", tile_unit, exc)
        checkpoint.mark_failed(tile_unit, f"shape: {exc}")
        _bump_progress(progress, window.label, failed=True)
        return
    except (RetryableError, downloader.EmptyTileError) as exc:
        log.error("tile %s exhausted retries: %s", tile_unit, exc)
        checkpoint.mark_failed(tile_unit, str(exc))
        _bump_progress(progress, window.label, failed=True)
        return
    except Exception as exc:  # noqa: BLE001
        log.error("tile %s failed (non-retryable): %s", tile_unit, exc)
        checkpoint.mark_failed(tile_unit, str(exc))
        _bump_progress(progress, window.label, failed=True)
        return

    try:
        validator.validate_tile(
            array,
            expected_shape=(len(ordered_bands), height_px, width_px),
            nodata=cfg.output.nodata,
            tile_id=tile_unit,
        )
    except downloader.EmptyTileError:
        log.warning("tile %s validation: empty — marking failed (will skip)", tile_unit)
        checkpoint.mark_failed(tile_unit, "empty tile after retries")
        _bump_progress(progress, window.label, failed=True)
        return

    transform = Affine(resolution_m, 0.0, minx, 0.0, -resolution_m, maxy)

    # Partial tiles get a local rasterio mask. We mask to the (un-buffered)
    # tile geometry since the ROI lives server-side; the EE-side clip has
    # already trimmed the data to the ROI boundary.
    mask_geom = tile.geom if tile.tile_class == "partial" else None

    written = await scheduler.run_blocking(
        write_tile,
        array,
        output_path=out_path,
        transform=transform,
        crs=f"EPSG:{epsg}",
        band_names=ordered_bands,
        dtype=cfg.output.dtype,
        nodata=cfg.output.nodata,
        compression=cfg.output.compression,
        fmt=cfg.output.format,
        mask_geom=mask_geom,
        overlap_px=cfg.tiling.overlap_px,
    )

    write_stac_sidecar(
        tile_id=tile_unit,
        output_tif=written,
        geometry=tile.geom,
        start=datetime.combine(window.start, datetime.min.time()),
        end=datetime.combine(window.end, datetime.min.time()),
        platform=cfg.dataset.name,
        gsd=resolution_m,
        bands=ordered_bands,
        extra={
            "tile_class": tile.tile_class,
            "coverage": tile.coverage,
            "window_type": cfg.composite.window.type,
        },
    )

    checkpoint.mark_done(tile_unit, str(written))
    _bump_progress(progress, window.label, failed=False)
    if hooks["post_tile"]:
        hooks["post_tile"](tile_unit=tile_unit, output_path=str(written), config=cfg)


async def _run(cfg: JobConfig, *, fresh: bool, retry_failed: bool) -> None:
    initialize_ee(cfg)

    hooks = {
        "pre_download": _load_hook(cfg.hooks.pre_download),
        "post_tile": _load_hook(cfg.hooks.post_tile),
        "post_job": _load_hook(cfg.hooks.post_job),
    }

    dataset_spec = get_dataset(cfg.dataset.name)
    if cfg.dataset.bands.select is None:
        cfg.dataset.bands.select = dataset_spec.band_names()
    n_bands = len(cfg.dataset.bands.select) + len(cfg.dataset.indices)

    gdf, epsg = load_roi(
        cfg.roi.path,
        layer=cfg.roi.layer,
        feature_mode=cfg.roi.feature_mode,
        filter_expr=cfg.roi.filter_expr,
    )
    simplified = simplify_for_upload(gdf, dataset_spec.native_res, cfg.roi.simplify_tolerance)

    asset_id = asset_id_for(cfg.asset.base_path, cfg.roi.path)
    upload_roi_asset(simplified, asset_id)
    roi_fc = ee.FeatureCollection(asset_id)

    roi_geom = gdf.geometry.unary_union
    tiles = generate_tiles(
        roi_geom,
        resolution_m=dataset_spec.native_res,
        n_bands=n_bands,
        overlap_px=cfg.tiling.overlap_px,
        skip_coverage_threshold=cfg.tiling.skip_coverage_threshold,
        grid_snap_m=cfg.tiling.grid_snap_m,
        max_tile_bytes=cfg.tiling.max_tile_bytes,
    )
    log.info("generated %d tiles", len(tiles))

    windows = generate_windows(
        cfg.date.start,
        cfg.date.end,
        cfg.composite.window.type,
        size=cfg.composite.window.size,
        step=cfg.composite.window.step,
        anchor=cfg.composite.window.anchor,
        label_format=cfg.composite.window.label_format,
    )
    if windows is None:
        raise NotImplementedError("scene mode is not yet implemented in runner")
    log.info("generated %d windows", len(windows))

    output_root = Path(cfg.output.dir)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "job.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")))

    ckpt = Checkpoint(output_root / "checkpoint.db")
    if fresh:
        ckpt.close()
        (output_root / "checkpoint.db").unlink(missing_ok=True)
        ckpt = Checkpoint(output_root / "checkpoint.db")

    ckpt.init_job(cfg.config_hash(), asset_id)
    ckpt.recover_from_crash(output_root)

    units: list[tuple[Tile, Window]] = [(t, w) for w in windows for t in tiles]
    ckpt.register_tiles(f"{t.grid_label}_{w.label}" for t, w in units)

    if retry_failed:
        for failed_id in ckpt.pending_ids(include_failed=True):
            ckpt.reset_to_pending(failed_id)

    # Per-window scene count — drops windows that can't be composited.
    # Done after retry_failed reset so we re-probe on every run (data may now exist).
    min_scenes = cfg.composite.window.min_scenes
    viable_windows: list[Window] = []
    for w in windows:
        n_scenes = compositor.count_window_scenes(cfg.dataset, dataset_spec, w, roi_fc)
        if n_scenes < min_scenes:
            log.warning(
                "window %s has %d scenes (< min_scenes=%d) — skipping all tiles in this window",
                w.label, n_scenes, min_scenes,
            )
            reason = f"window {w.label}: {n_scenes} scenes (< min_scenes={min_scenes})"
            for t in tiles:
                ckpt.mark_failed(f"{t.grid_label}_{w.label}", reason)
            continue
        viable_windows.append(w)
    units = [(t, w) for w in viable_windows for t in tiles]

    pending = set(ckpt.pending_ids())
    work = [(t, w) for t, w in units if f"{t.grid_label}_{w.label}" in pending]
    log.info("%d/%d units pending", len(work), len(units))

    if hooks["pre_download"]:
        hooks["pre_download"](config=cfg, asset_id=asset_id, n_units=len(work))

    # Per-window + overall progress bars. Position 0 is the overall bar;
    # window bars stack below it in window order.
    window_totals: dict[str, int] = {}
    for t, w in work:
        window_totals[w.label] = window_totals.get(w.label, 0) + 1

    overall_bar = tqdm(
        total=len(work),
        desc="overall",
        position=0,
        unit="tile",
        dynamic_ncols=True,
    )
    window_bars: dict[str, tqdm] = {}
    for i, label in enumerate(sorted(window_totals), start=1):
        window_bars[label] = tqdm(
            total=window_totals[label],
            desc=f"  {label}",
            position=i,
            unit="tile",
            leave=False,
            dynamic_ncols=True,
        )
    progress: dict[str, Any] = {
        "overall": overall_bar,
        "windows": window_bars,
        "failed": 0,
    }

    scheduler = Scheduler(cfg.pipeline.concurrency)
    try:
        async def worker(item: tuple[Tile, Window]) -> None:
            t, w = item
            await _process_tile(
                t,
                w,
                cfg=cfg,
                dataset_spec=dataset_spec,
                roi_fc=roi_fc,
                epsg=epsg,
                output_root=output_root,
                checkpoint=ckpt,
                scheduler=scheduler,
                hooks=hooks,
                progress=progress,
            )

        await scheduler.run(work, worker)
    finally:
        scheduler.close()
        for bar in window_bars.values():
            bar.close()
        overall_bar.close()

    counts = ckpt.counts()
    log.info("final tile counts: %s", counts)

    if counts.get("done", 0) > 0 and counts.get("pending", 0) == 0 and counts.get("failed", 0) == 0:
        _finalize_outputs(output_root, cfg, windows, roi_geom, epsg, dataset_spec)
        ckpt.mark_job_complete()
        _write_catalog(output_root, ckpt, cfg)
        if cfg.asset.auto_cleanup:
            delete_asset(asset_id)

    if hooks["post_job"]:
        hooks["post_job"](config=cfg, counts=counts)

    ckpt.close()


def _merge_window(
    tile_dir: Path,
    final_path: Path,
    *,
    compression: str,
    fmt: str,
    nodata: float,
) -> Path | None:
    tiles = sorted(tile_dir.glob("*.tif"))
    if not tiles:
        return None

    srcs = [rasterio.open(t) for t in tiles]
    try:
        mosaic, transform = rio_merge(srcs, nodata=nodata)
        ref = srcs[0]
        profile = ref.profile.copy()
        band_descs = ref.descriptions
    finally:
        for s in srcs:
            s.close()

    profile.update(
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=transform,
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        interleave="pixel",
    )
    if compression != "none":
        profile["compress"] = compression
    else:
        profile.pop("compress", None)

    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.with_suffix(final_path.suffix + ".tmp")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(mosaic)
        for i, name in enumerate(band_descs, start=1):
            if name:
                dst.set_band_description(i, name)
        if fmt == "COG":
            dst.build_overviews([2, 4, 8], Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")
    os.rename(tmp, final_path)
    return final_path


def _finalize_outputs(
    output_root: Path,
    cfg: JobConfig,
    windows: list[Window],
    roi_geom: BaseGeometry,
    epsg: int,
    dataset_spec,
) -> None:
    tmp_root = output_root / ".tmp" / cfg.dataset.name
    if not tmp_root.exists():
        return

    project = pyproj.Transformer.from_crs(epsg, 4326, always_xy=True).transform
    geom_4326 = shp_transform(project, roi_geom)
    bands = list(cfg.dataset.bands.select or []) + [i.output_band or i.name for i in cfg.dataset.indices]

    final_dir = output_root / cfg.dataset.name
    for w in windows:
        tile_dir = tmp_root / w.label
        if not tile_dir.exists():
            continue
        final_path = final_dir / f"{cfg.job_name}_{w.label}.tif"
        merged = _merge_window(
            tile_dir,
            final_path,
            compression=cfg.output.compression,
            fmt=cfg.output.format,
            nodata=cfg.output.nodata,
        )
        if merged is None:
            continue
        write_stac_sidecar(
            tile_id=f"{cfg.job_name}_{w.label}",
            output_tif=merged,
            geometry=geom_4326,
            start=datetime.combine(w.start, datetime.min.time()),
            end=datetime.combine(w.end, datetime.min.time()),
            platform=cfg.dataset.name,
            gsd=dataset_spec.native_res,
            bands=bands,
            extra={"window_type": cfg.composite.window.type},
        )

    shutil.rmtree(output_root / ".tmp", ignore_errors=True)


def _write_catalog(output_root: Path, ckpt: Checkpoint, cfg: JobConfig) -> None:
    rows = []
    for tif in output_root.rglob("*.tif"):
        sidecar = tif.with_suffix(".json")
        if not sidecar.exists():
            continue
        import json
        item = json.loads(sidecar.read_text())
        rows.append({
            "tile_id": item["id"],
            "geometry": item["geometry"],
            "datetime": item["properties"]["datetime"],
            "path": str(tif.relative_to(output_root)),
            "_crs": 4326,
        })
    if rows:
        write_catalog_parquet(output_root, rows)


def run_job(cfg: JobConfig, *, fresh: bool = False, retry_failed: bool = False) -> None:
    """Synchronous wrapper around the async runner. Entry point for the CLI."""
    asyncio.run(_run(cfg, fresh=fresh, retry_failed=retry_failed))
