"""Pydantic v2 schema for the full geedl YAML config."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, populate_by_name=True)


class RoiConfig(_Frozen):
    path: str = Field(..., description="Path to shapefile (.shp, .geojson, .gpkg).")
    layer: str | None = Field(None, description="Optional layer name for multi-layer files.")
    feature_mode: Literal["union", "split", "filter"] = Field(
        "union", description="How to combine features in the ROI source."
    )
    filter_expr: str | None = Field(
        None, description="Pandas query string used when feature_mode='filter'."
    )
    simplify_tolerance: float | Literal["auto"] = Field(
        "auto", description="Simplification tolerance in metres, or 'auto' = 10% of resolution."
    )


class IndexEntry(_Frozen):
    name: str = Field(..., description="Registered index name (e.g. NDVI).")
    output_band: str | None = Field(None, description="Output band name (default: index name).")
    position: Literal["after_bands", "before_bands"] | int = Field(
        "after_bands", description="Where to place the index in band order."
    )


class BandsConfig(_Frozen):
    select: list[str] | None = Field(None, description="Bands to keep (null = all in registry).")
    order: list[str] | None = Field(None, description="Explicit output band order.")
    rename: dict[str, str] | None = Field(None, description="Rename map applied after download.")
    scale_factor: float | None = Field(None, description="Scale factor (null = registry default).")
    offset: float = Field(0.0, description="Additive offset applied after scale.")


class CloudMaskConfig(_Frozen):
    enabled: bool = True
    profile: str | Literal["auto"] = "auto"
    mask_shadow: bool = True
    mask_snow: bool = False


class SlcOffConfig(_Frozen):
    strategy: Literal["multi_temporal"] = "multi_temporal"
    min_scenes_warning: int = 3


class DatasetConfig(_Frozen):
    name: str = Field(..., description="Dataset slug from registry.yaml.")
    bands: BandsConfig = Field(default_factory=BandsConfig)
    indices: list[IndexEntry] = Field(default_factory=list)
    cloud_mask: CloudMaskConfig = Field(default_factory=CloudMaskConfig)
    slc_off: SlcOffConfig = Field(default_factory=SlcOffConfig)


class DateConfig(_Frozen):
    start: date
    end: date

    @model_validator(mode="after")
    def _check_order(self) -> "DateConfig":
        if self.end < self.start:
            raise ValueError(f"date.end ({self.end}) is before date.start ({self.start})")
        return self


class WindowConfig(_Frozen):
    type: Literal["fixed_days", "calendar_month", "calendar_year", "full_range", "scene"] = (
        "full_range"
    )
    size: int | None = Field(None, description="Window length in days (fixed_days only).")
    step: int | None = Field(None, description="Step in days (null = same as size).")
    anchor: Literal["start", "end", "center"] = "start"
    min_scenes: int = 1
    label_format: str = "%Y-%m-%d"

    @model_validator(mode="after")
    def _check_fixed_days(self) -> "WindowConfig":
        if self.type == "fixed_days" and (self.size is None or self.size <= 0):
            raise ValueError("composite.window.size must be > 0 when type='fixed_days'")
        return self


class CompositeConfig(_Frozen):
    strategy: Literal["median", "mean", "mosaic", "none"] = "median"
    window: WindowConfig = Field(default_factory=WindowConfig)


class OutputStructureConfig(_Frozen):
    timeseries_mode: bool = False
    band_interleave: Literal["BIP", "BIL", "BSQ"] = "BIP"
    filename_template: str = "tile_{tile_id}_{window_label}"
    separate_indices: bool = True


class OutputConfig(_Frozen):
    dir: str = "./output"
    format: Literal["COG", "GeoTIFF"] = "COG"
    nodata: float = -9999.0
    dtype: Literal["float32", "int16", "uint16"] = "float32"
    crs: str | None = Field(None, description="EPSG code, or null for auto-UTM.")
    compression: Literal["LZW", "DEFLATE", "ZSTD", "none"] = "LZW"
    structure: OutputStructureConfig = Field(default_factory=OutputStructureConfig)


class TilingConfig(_Frozen):
    max_tile_bytes: int | None = None
    overlap_px: int = 2
    skip_coverage_threshold: float = 0.05
    grid_snap_m: int = 100


class PipelineConfig(_Frozen):
    concurrency: int = 16
    max_retries: int = 6
    retry_base_delay: float = 1.0
    timeout_per_tile: int = 120


class AssetConfig(_Frozen):
    project: str = Field(..., description="EE project ID or username.")
    base_path: str = Field(..., description="EE asset folder for ROI uploads.")
    auto_cleanup: bool = False


class AuthConfig(_Frozen):
    method: Literal["browser", "service_account"] = Field(
        "browser",
        description="Authentication method: 'browser' uses Application Default Credentials; "
        "'service_account' uses a JSON key file.",
    )
    service_account_email: str | None = Field(
        None, description="Service account email (required when method='service_account')."
    )
    key_file: str | None = Field(
        None, description="Path to service account JSON key file (required when method='service_account')."
    )

    @model_validator(mode="after")
    def _check_service_account_fields(self) -> "AuthConfig":
        if self.method == "service_account":
            missing = [f for f, v in [("service_account_email", self.service_account_email), ("key_file", self.key_file)] if v is None]
            if missing:
                raise ValueError(
                    f"auth.method='service_account' requires: {', '.join(missing)}"
                )
        return self


class HooksConfig(_Frozen):
    pre_download: str | None = None
    post_tile: str | None = None
    post_job: str | None = None

    @field_validator("pre_download", "post_tile", "post_job")
    @classmethod
    def _check_hook_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v.count(":") != 1 or not all(part.strip() for part in v.split(":")):
            raise ValueError(f"hook must be 'module.path:function_name', got {v!r}")
        return v


class JobConfig(_Frozen):
    job_name: str
    roi: RoiConfig
    dataset: DatasetConfig
    date: DateConfig
    composite: CompositeConfig = Field(default_factory=CompositeConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    tiling: TilingConfig = Field(default_factory=TilingConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    asset: AssetConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)

    def config_hash(self) -> str:
        """sha1 of canonical YAML serialisation of the resolved config."""
        canonical = yaml.safe_dump(
            self.model_dump(mode="json"), sort_keys=True, default_flow_style=False
        ).encode("utf-8")
        return hashlib.sha1(canonical).hexdigest()


def load_config(path: str | Path) -> JobConfig:
    """Load and validate a YAML config from disk."""
    raw = yaml.safe_load(Path(path).read_text())
    return JobConfig.model_validate(raw)
