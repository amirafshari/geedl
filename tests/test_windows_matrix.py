"""Window generation across all dataset cadences and window types.

Pure function — no EE, no I/O. Asserts every (dataset, window-type) combo
produces a non-empty, monotonically ordered, non-overlapping-or-overlapping-
as-configured list of windows.
"""

from __future__ import annotations

from datetime import date

import pytest

from geedl.utils.windows import generate_windows

# Typical revisit cadence (days) — used to derive sensible window sizes per dataset.
DATASET_REVISIT = {
    "sentinel-1": 12,
    "sentinel-2": 5,
    "landsat-7": 16,
    "landsat-8": 16,
    "landsat-9": 16,
}

WINDOW_TYPES = ["fixed_days", "calendar_month", "calendar_year", "full_range", "scene"]


@pytest.mark.parametrize("dataset,revisit", DATASET_REVISIT.items())
@pytest.mark.parametrize("wtype", WINDOW_TYPES)
def test_window_matrix(dataset: str, revisit: int, wtype: str) -> None:
    start, end = date(2023, 1, 1), date(2023, 12, 31)
    kwargs: dict = {}
    if wtype == "fixed_days":
        # Pick a size at least 2x revisit so each window can plausibly have scenes.
        kwargs["size"] = revisit * 3
        kwargs["step"] = revisit * 3

    ws = generate_windows(start, end, wtype, **kwargs)

    if wtype == "scene":
        assert ws is None
        return

    assert ws and len(ws) >= 1, f"{dataset}/{wtype} produced no windows"
    # Monotonic non-decreasing start dates.
    starts = [w.start for w in ws]
    assert starts == sorted(starts)
    # Every window stays within the requested range.
    for w in ws:
        assert w.start >= start
        assert w.end <= end
        assert w.end >= w.start


@pytest.mark.parametrize("anchor", ["start", "end", "center"])
def test_fixed_days_anchor_modes(anchor: str) -> None:
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 6, 30),
        "fixed_days", size=30, step=30, anchor=anchor,
    )
    assert ws is not None and len(ws) > 0
    # Labels are unique even when anchor changes their value.
    labels = [w.label for w in ws]
    assert len(set(labels)) == len(labels)


def test_overlapping_step_smaller_than_size() -> None:
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 6, 30),
        "fixed_days", size=30, step=10,
    )
    assert ws is not None
    # Adjacent windows overlap.
    assert (ws[1].start - ws[0].start).days == 10
    assert ws[0].end > ws[1].start


def test_step_larger_than_size_creates_gaps() -> None:
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 6, 30),
        "fixed_days", size=10, step=30,
    )
    assert ws is not None
    # Gap between windows: w[1].start should be > w[0].end.
    assert ws[1].start > ws[0].end


def test_window_short_for_revisit_still_generates() -> None:
    # Window shorter than typical Landsat revisit (16 days) — generation still works.
    ws = generate_windows(
        date(2023, 1, 1), date(2023, 1, 31),
        "fixed_days", size=10, step=10,
    )
    assert ws is not None and len(ws) >= 2
