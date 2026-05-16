"""Tests for the pure window generator. No EE, no I/O."""

from __future__ import annotations

from datetime import date

import pytest

from geedl.utils.windows import generate_windows


def test_fixed_days_non_overlapping():
    ws = generate_windows(
        date(2023, 1, 15), date(2023, 6, 30),
        "fixed_days", size=40, step=40,
    )
    # Trailing partial window (only 7 days, < size=40) is dropped.
    assert len(ws) == 4
    assert ws[0].start == date(2023, 1, 15)
    assert ws[0].end == date(2023, 2, 23)
    assert ws[0].label == "2023-01-15"
    assert ws[-1].start == date(2023, 5, 15)
    assert ws[-1].end == date(2023, 6, 23)


def test_fixed_days_drops_short_trailing_window():
    ws = generate_windows(
        date(2022, 4, 22), date(2022, 6, 22),
        "fixed_days", size=30, step=30,
    )
    # 62 days total → two full 30-day windows, trailing 2-day sliver dropped.
    assert len(ws) == 2
    assert ws[0].start == date(2022, 4, 22)
    assert ws[1].start == date(2022, 5, 22)
    assert ws[1].end == date(2022, 6, 20)


def test_fixed_days_overlapping():
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 3, 31),
        "fixed_days", size=30, step=10,
    )
    # Starts every 10 days, must be > 1
    assert len(ws) > 1
    starts = [w.start for w in ws]
    assert starts == sorted(starts)
    assert (starts[1] - starts[0]).days == 10


def test_full_range():
    ws = generate_windows(
        date(2023, 1, 15), date(2023, 6, 30),
        "full_range",
    )
    assert len(ws) == 1
    assert ws[0].start == date(2023, 1, 15)
    assert ws[0].end == date(2023, 6, 30)


def test_scene_mode_returns_none():
    assert generate_windows(date(2023, 1, 1), date(2023, 12, 31), "scene") is None


def test_calendar_month():
    ws = generate_windows(
        date(2023, 1, 15), date(2023, 3, 31),
        "calendar_month",
    )
    assert len(ws) == 3
    assert ws[0].start == date(2023, 1, 15)
    assert ws[0].end == date(2023, 1, 31)
    assert ws[1].start == date(2023, 2, 1)
    assert ws[1].end == date(2023, 2, 28)
    assert ws[2].start == date(2023, 3, 1)
    assert ws[2].end == date(2023, 3, 31)


def test_calendar_year():
    ws = generate_windows(
        date(2022, 6, 1), date(2024, 4, 1),
        "calendar_year",
    )
    assert len(ws) == 3
    assert ws[0].start == date(2022, 6, 1)
    assert ws[1].start == date(2023, 1, 1)
    assert ws[1].end == date(2023, 12, 31)
    assert ws[2].end == date(2024, 4, 1)


def test_anchor_modes():
    base = (date(2023, 1, 1), date(2023, 1, 31))
    ws_start = generate_windows(*base, "full_range", anchor="start")
    ws_end = generate_windows(*base, "full_range", anchor="end")
    ws_center = generate_windows(*base, "full_range", anchor="center")
    assert ws_start[0].label == "2023-01-01"
    assert ws_end[0].label == "2023-01-31"
    assert ws_center[0].label == "2023-01-16"


def test_label_format():
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 3, 31),
        "calendar_month", label_format="%Y-%m",
    )
    assert [w.label for w in ws] == ["2023-01", "2023-02", "2023-03"]


def test_end_before_start_raises():
    with pytest.raises(ValueError):
        generate_windows(date(2023, 6, 1), date(2023, 1, 1), "full_range")


def test_fixed_days_requires_positive_size():
    with pytest.raises(ValueError):
        generate_windows(date(2023, 1, 1), date(2023, 12, 31), "fixed_days", size=0)


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        generate_windows(date(2023, 1, 1), date(2023, 12, 31), "nonsense")
