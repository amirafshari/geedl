"""Scene-mode enumeration and nearest-date suggestion.

Mocks ee.ImageCollection's chained calls so no live EE credentials are needed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from geedl.datasets.registry import get
from geedl.pipeline.scenes import (
    NoScenesAvailableError,
    enumerate_scenes,
    scenes_to_windows,
    suggest_nearest_dates,
)


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _mock_collection(scene_dates: list[date]):
    """Return a MagicMock that mimics the chained ee.ImageCollection API."""
    col = MagicMock(name="ImageCollection")
    col.filterDate.return_value = col
    col.filterBounds.return_value = col
    col.filter.return_value = col

    times = [_ms(d) for d in scene_dates]
    ids = [f"S_{i}" for i in range(len(scene_dates))]

    def agg(prop):
        result = MagicMock()
        result.getInfo.return_value = times if "time" in prop else ids
        return result

    col.aggregate_array.side_effect = agg
    return col


def test_enumerate_returns_sorted_scenes() -> None:
    spec = get("sentinel-2")
    roi_fc = MagicMock()
    roi_fc.geometry.return_value = MagicMock()
    dates = [date(2024, 6, 13), date(2024, 6, 10), date(2024, 6, 18)]
    with patch("geedl.pipeline.scenes.ee.ImageCollection", return_value=_mock_collection(dates)):
        scenes = enumerate_scenes(spec, roi_fc, date(2024, 6, 1), date(2024, 6, 30))
    assert [s.date for s in scenes] == sorted(dates)


def test_enumerate_empty_when_no_scenes() -> None:
    spec = get("sentinel-2")
    roi_fc = MagicMock()
    roi_fc.geometry.return_value = MagicMock()
    with patch("geedl.pipeline.scenes.ee.ImageCollection", return_value=_mock_collection([])):
        scenes = enumerate_scenes(spec, roi_fc, date(2024, 6, 15), date(2024, 6, 15))
    assert scenes == []


def test_suggest_nearest_ranks_by_distance() -> None:
    spec = get("sentinel-2")
    roi_fc = MagicMock()
    roi_fc.geometry.return_value = MagicMock()
    # Target = 2024-06-15. Closest: 13 (Δ2), 18 (Δ3), 10 (Δ5), 25 (Δ10), 01 (Δ14)
    available = [
        date(2024, 6, 13),
        date(2024, 6, 18),
        date(2024, 6, 10),
        date(2024, 6, 25),
        date(2024, 6, 1),
        date(2024, 7, 5),
    ]
    with patch("geedl.pipeline.scenes.ee.ImageCollection", return_value=_mock_collection(available)):
        suggestions = suggest_nearest_dates(spec, roi_fc, date(2024, 6, 15), n=3)
    assert suggestions == [date(2024, 6, 13), date(2024, 6, 18), date(2024, 6, 10)]


def test_suggest_nearest_widens_then_gives_up() -> None:
    spec = get("sentinel-2")
    roi_fc = MagicMock()
    roi_fc.geometry.return_value = MagicMock()
    with patch("geedl.pipeline.scenes.ee.ImageCollection", return_value=_mock_collection([])):
        suggestions = suggest_nearest_dates(spec, roi_fc, date(2024, 6, 15))
    assert suggestions == []


def test_suggest_nearest_deduplicates_same_day_scenes() -> None:
    spec = get("sentinel-2")
    roi_fc = MagicMock()
    roi_fc.geometry.return_value = MagicMock()
    # Two scenes on the same day should collapse to one suggestion.
    available = [date(2024, 6, 13), date(2024, 6, 13), date(2024, 6, 18)]
    with patch("geedl.pipeline.scenes.ee.ImageCollection", return_value=_mock_collection(available)):
        suggestions = suggest_nearest_dates(spec, roi_fc, date(2024, 6, 15), n=5)
    assert suggestions == [date(2024, 6, 13), date(2024, 6, 18)]


def test_scenes_to_windows_one_per_date() -> None:
    from geedl.pipeline.scenes import Scene

    scenes = [
        Scene("a", date(2024, 6, 10), _ms(date(2024, 6, 10))),
        Scene("b", date(2024, 6, 13), _ms(date(2024, 6, 13))),
        Scene("c", date(2024, 6, 13), _ms(date(2024, 6, 13)) + 1000),
    ]
    windows = scenes_to_windows(scenes, "%Y-%m-%d")
    assert [w.label for w in windows] == ["2024-06-10", "2024-06-13"]
    assert all(w.start == w.end for w in windows)


def test_no_scenes_error_message_single_date() -> None:
    err = NoScenesAvailableError(
        "sentinel-2",
        (date(2024, 6, 15), date(2024, 6, 15)),
        [date(2024, 6, 13), date(2024, 6, 18)],
    )
    msg = str(err)
    assert "2024-06-15" in msg
    assert "2024-06-13" in msg
    assert "2024-06-18" in msg
    assert "→" not in msg  # single-date form, not a range


def test_no_scenes_error_message_range() -> None:
    err = NoScenesAvailableError(
        "sentinel-2", (date(2024, 6, 1), date(2024, 6, 30)), []
    )
    assert "2024-06-01" in str(err)
    assert "2024-06-30" in str(err)
    assert err.suggestions == []
