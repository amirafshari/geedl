"""Pytest config: opt-in `--live` marker for tests that hit real Earth Engine."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run @pytest.mark.live tests that hit real Earth Engine.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: requires authenticated Earth Engine credentials"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live (real Earth Engine access)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
