"""Job runner — wires every layer together. The only place ee.Initialize is called."""

from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import ee
import yaml
from rasterio.transform import Affine

from ..config import JobConfig
from ..datasets.registry import get as get_dataset
from ..io.catalog import write_catalog_parquet, write_stac_sidecar
from ..io.checkpoint import Checkpoint
from ..io.writer import write_tile
from ..roi.asset_manager import asset_id_for, delete_asset, upload_roi_asset
from ..roi.loader import load_roi
from ..roi.simplifier import simplify_for_upload
from ..roi.tiler import Tile, generate_tiles
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
) -> None:
    tile_unit = f"{tile.grid_label}_{window.label}"
    if not checkpoint.claim(tile_unit):
        return

    resolution_m = dataset_spec.native_res
    minx, miny, maxx, maxy = tile.request_geom.bounds
    width_px = int(round((maxx - minx) / resolution_m))
    height_px = int(round((maxy - miny) / resolution_m))

    out_dir = output_root / cfg.dataset.name / window.label
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
        return
    except Exception as exc:  # noqa: BLE001
        log.error("tile %s exhausted retries: %s", tile_unit, exc)
        checkpoint.mark_failed(tile_unit, str(exc))
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
    if hooks["post_tile"]:
        hooks["post_tile"](tile_unit=tile_unit, output_path=str(written), config=cfg)


async def _run(cfg: JobConfig, *, fresh: bool, retry_failed: bool) -> None:
    ee.Initialize(project=cfg.asset.project)

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

    pending = set(ckpt.pending_ids())
    work = [(t, w) for t, w in units if f"{t.grid_label}_{w.label}" in pending]
    log.info("%d/%d units pending", len(work), len(units))

    if hooks["pre_download"]:
        hooks["pre_download"](config=cfg, asset_id=asset_id, n_units=len(work))

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
            )

        await scheduler.run(work, worker)
    finally:
        scheduler.close()

    counts = ckpt.counts()
    log.info("final tile counts: %s", counts)

    if counts.get("done", 0) > 0 and counts.get("pending", 0) == 0 and counts.get("failed", 0) == 0:
        ckpt.mark_job_complete()
        _write_catalog(output_root, ckpt, cfg)
        if cfg.asset.auto_cleanup:
            delete_asset(asset_id)

    if hooks["post_job"]:
        hooks["post_job"](config=cfg, counts=counts)

    ckpt.close()


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
