"""geedl CLI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

import geedl.indices.optical  # noqa: F401 — registers optical indices
import geedl.indices.sar  # noqa: F401 — registers SAR indices

from .config import load_config
from .datasets.registry import get as get_dataset
from .datasets.registry import list_slugs
from .indices import list_indices
from .io.checkpoint import Checkpoint
from .pipeline.runner import run_job
from .pipeline.scenes import NoScenesAvailableError
from .utils.windows import generate_windows

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Local-first GEE downloader.")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML config."),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore checkpoint, start over."),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Retry tiles in 'failed' state."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Run or resume a download job."""
    _setup_logging(verbose)
    cfg = load_config(config)
    try:
        run_job(cfg, fresh=fresh, retry_failed=retry_failed)
    except NoScenesAvailableError as exc:
        typer.echo(str(exc), err=True)
        if exc.suggestions:
            typer.echo("\nTry one of these dates in date.start / date.end:", err=True)
            for d in exc.suggestions:
                typer.echo(f"  {d.isoformat()}", err=True)
        raise typer.Exit(code=2)


@app.command()
def validate(
    config: Path = typer.Option(..., "--config", "-c"),
) -> None:
    """Validate a config file without contacting Earth Engine."""
    cfg = load_config(config)
    ds = get_dataset(cfg.dataset.name)
    typer.echo(f"OK: {cfg.job_name}")
    typer.echo(f"  dataset: {cfg.dataset.name} ({ds.collection})")
    typer.echo(f"  date:    {cfg.date.start} → {cfg.date.end}")
    typer.echo(f"  hash:    {cfg.config_hash()}")
    for entry in cfg.dataset.indices:
        from .indices import supports
        if not supports(entry.name, cfg.dataset.name):
            typer.echo(f"  WARN: index {entry.name} not supported for {cfg.dataset.name}", err=True)
    if ds.slc_off_date and cfg.date.start > ds.slc_off_date:
        if cfg.composite.window.type == "scene":
            raise typer.BadParameter(
                "Landsat 7 post-2003 cannot be used with composite.window.type='scene' — "
                "single-scene output would be heavily gapped."
            )
        if cfg.composite.window.type == "fixed_days" and cfg.composite.window.size:
            approx_scenes = cfg.composite.window.size / 16
            if approx_scenes < cfg.dataset.slc_off.min_scenes_warning:
                typer.echo(
                    f"  WARN: SLC-off — window of {cfg.composite.window.size} days yields "
                    f"~{approx_scenes:.1f} scenes (< {cfg.dataset.slc_off.min_scenes_warning}). "
                    "Widen the window or use L8/L9.",
                    err=True,
                )


@app.command()
def status(
    config: Path = typer.Option(..., "--config", "-c"),
) -> None:
    """Show tile counts for an existing job."""
    cfg = load_config(config)
    db = Path(cfg.output.dir) / "checkpoint.db"
    if not db.exists():
        typer.echo("No checkpoint yet — job has not been run.")
        raise typer.Exit(0)
    ckpt = Checkpoint(db)
    counts = ckpt.counts()
    for k in ("pending", "in_flight", "done", "failed"):
        typer.echo(f"  {k:<10} {counts.get(k, 0)}")
    ckpt.close()


@app.command()
def plan(
    config: Path = typer.Option(..., "--config", "-c"),
) -> None:
    """Dry run — print windows and tile geometry without contacting EE."""
    cfg = load_config(config)
    ds = get_dataset(cfg.dataset.name)
    windows = generate_windows(
        cfg.date.start, cfg.date.end,
        cfg.composite.window.type,
        size=cfg.composite.window.size,
        step=cfg.composite.window.step,
        anchor=cfg.composite.window.anchor,
        label_format=cfg.composite.window.label_format,
    )
    if windows is None:
        typer.echo("scene mode — no precomputed windows")
    else:
        typer.echo(f"{len(windows)} windows:")
        for w in windows:
            typer.echo(f"  {w.label}  {w.start} → {w.end}")
    typer.echo(f"dataset: {cfg.dataset.name}  native_res={ds.native_res}m")


@app.command()
def datasets() -> None:
    """List available dataset slugs."""
    for s in list_slugs():
        typer.echo(s)


@app.command()
def indices(
    dataset: str | None = typer.Option(None, "--dataset", "-d"),
) -> None:
    """List spectral indices, optionally filtered by dataset support."""
    for name in list_indices(dataset):
        typer.echo(name)


@app.command()
def cleanup(
    config: Path = typer.Option(..., "--config", "-c"),
) -> None:
    """Delete the EE asset associated with a job."""
    from .roi.asset_manager import asset_id_for, delete_asset
    from .utils.auth import initialize_ee
    cfg = load_config(config)
    initialize_ee(cfg)
    aid = asset_id_for(cfg.asset.base_path, cfg.roi.path)
    delete_asset(aid)
    typer.echo(f"deleted: {aid}")


if __name__ == "__main__":  # pragma: no cover
    app()
