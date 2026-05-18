"""Config schema validation tests."""

from __future__ import annotations

from datetime import date

import pytest

from geedl.config import JobConfig, load_config


def _minimal() -> dict:
    return {
        "job_name": "demo",
        "roi": {"path": "tests/fixtures/roi.shp"},
        "dataset": {"name": "sentinel-2"},
        "date": {"start": "2023-01-15", "end": "2023-06-30"},
        "asset": {"project": "my-proj", "base_path": "users/me/geedl"},
    }


def test_minimal_config_validates():
    cfg = JobConfig.model_validate(_minimal())
    assert cfg.job_name == "demo"
    assert cfg.date.start == date(2023, 1, 15)
    assert cfg.composite.strategy == "median"  # default


def test_end_before_start_rejected():
    raw = _minimal()
    raw["date"] = {"start": "2023-06-30", "end": "2023-01-15"}
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        JobConfig.model_validate(raw)


def test_hook_format_validation():
    raw = _minimal()
    raw["hooks"] = {"post_tile": "not_a_valid_hook"}
    with pytest.raises(Exception):
        JobConfig.model_validate(raw)
    raw["hooks"] = {"post_tile": "my_module:fn"}
    JobConfig.model_validate(raw)


def test_fixed_days_requires_size():
    raw = _minimal()
    raw["composite"] = {"window": {"type": "fixed_days"}}
    with pytest.raises(Exception):
        JobConfig.model_validate(raw)
    raw["composite"] = {"window": {"type": "fixed_days", "size": 40}}
    JobConfig.model_validate(raw)


def test_config_hash_is_stable():
    cfg = JobConfig.model_validate(_minimal())
    h1 = cfg.config_hash()
    h2 = cfg.config_hash()
    assert h1 == h2
    # Different config produces different hash
    raw2 = _minimal()
    raw2["job_name"] = "other"
    cfg2 = JobConfig.model_validate(raw2)
    assert cfg2.config_hash() != h1


def test_empty_bands_with_indices_validates():
    raw = _minimal()
    raw["dataset"] = {
        "name": "sentinel-2",
        "bands": {"select": []},
        "indices": [{"name": "NDVI"}],
    }
    cfg = JobConfig.model_validate(raw)
    assert cfg.dataset.bands.select == []
    assert [e.name for e in cfg.dataset.indices] == ["NDVI"]


def test_empty_bands_without_indices_rejected():
    raw = _minimal()
    raw["dataset"] = {"name": "sentinel-2", "bands": {"select": []}}
    with pytest.raises(Exception, match="empty image"):
        JobConfig.model_validate(raw)


def test_load_config_from_yaml(tmp_path):
    import yaml
    p = tmp_path / "job.yaml"
    p.write_text(yaml.safe_dump(_minimal()))
    cfg = load_config(p)
    assert cfg.job_name == "demo"
