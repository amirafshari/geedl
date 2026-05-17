"""Config schema round-trip + AuthConfig validation."""

from __future__ import annotations

import pytest
import yaml

from geedl.config import JobConfig


def _minimal() -> dict:
    return {
        "job_name": "demo",
        "roi": {"path": "tests/fixtures/roi.shp"},
        "dataset": {"name": "sentinel-2"},
        "date": {"start": "2023-01-15", "end": "2023-06-30"},
        "asset": {"project": "my-proj", "base_path": "users/me/geedl"},
    }


def test_yaml_round_trip_preserves_hash() -> None:
    cfg1 = JobConfig.model_validate(_minimal())
    dumped = yaml.safe_dump(cfg1.model_dump(mode="json"))
    cfg2 = JobConfig.model_validate(yaml.safe_load(dumped))
    assert cfg1.config_hash() == cfg2.config_hash()


def test_auth_default_is_browser() -> None:
    cfg = JobConfig.model_validate(_minimal())
    assert cfg.auth.method == "browser"


def test_auth_service_account_validates() -> None:
    raw = _minimal()
    raw["auth"] = {
        "method": "service_account",
        "service_account_email": "bot@proj.iam.gserviceaccount.com",
        "key_file": "/etc/secrets/key.json",
    }
    cfg = JobConfig.model_validate(raw)
    assert cfg.auth.method == "service_account"
    assert cfg.auth.service_account_email
    assert cfg.auth.key_file


def test_auth_invalid_method_rejected() -> None:
    raw = _minimal()
    raw["auth"] = {"method": "magic"}
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        JobConfig.model_validate(raw)


def test_unknown_field_rejected() -> None:
    raw = _minimal()
    raw["nonsense_field"] = 1
    with pytest.raises(Exception):
        JobConfig.model_validate(raw)


def test_output_format_enum_rejects_bad_value() -> None:
    raw = _minimal()
    raw["output"] = {"format": "JPEG2000"}
    with pytest.raises(Exception):
        JobConfig.model_validate(raw)


def test_composite_strategy_enum_rejects_bad_value() -> None:
    raw = _minimal()
    raw["composite"] = {"strategy": "max"}
    with pytest.raises(Exception):
        JobConfig.model_validate(raw)


def test_index_position_accepts_int_and_literals() -> None:
    raw = _minimal()
    raw["dataset"]["indices"] = [
        {"name": "NDVI", "position": "after_bands"},
        {"name": "NDWI", "position": 2},
    ]
    cfg = JobConfig.model_validate(raw)
    assert cfg.dataset.indices[1].position == 2
