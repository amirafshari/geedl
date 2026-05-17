"""Pure window generation. No EE, no I/O, no side effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    label: str
    # Scene-mode only: explicit EE asset IDs to pin the collection to a
    # specific set of scenes (e.g. after per-scene ROI coverage filtering).
    # build_collection will filter by these IDs instead of date+bounds.
    scene_ids: tuple[str, ...] | None = None


def _add_one_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def _last_day_of_month(d: date) -> date:
    return _add_one_month(d.replace(day=1)) - timedelta(days=1)


def _anchor(window_start: date, window_end: date, mode: str) -> date:
    if mode == "start":
        return window_start
    if mode == "end":
        return window_end
    if mode == "center":
        return window_start + (window_end - window_start) // 2
    raise ValueError(f"Unknown anchor mode: {mode}")


def generate_windows(
    start: date,
    end: date,
    window_type: str,
    size: int | None = None,
    step: int | None = None,
    anchor: str = "start",
    label_format: str = "%Y-%m-%d",
) -> list[Window] | None:
    """Generate ordered time windows.

    Returns None for window_type='scene' — sentinel telling the compositor to
    iterate EE scenes directly without windowing.
    """
    if end < start:
        raise ValueError(f"end ({end}) is before start ({start})")

    if window_type == "scene":
        return None

    if window_type == "full_range":
        anchor_date = _anchor(start, end, anchor)
        return [Window(start, end, anchor_date.strftime(label_format))]

    if window_type == "calendar_year":
        windows: list[Window] = []
        year = start.year
        while date(year, 1, 1) <= end:
            w_start = max(date(year, 1, 1), start)
            w_end = min(date(year, 12, 31), end)
            anchor_date = _anchor(w_start, w_end, anchor)
            windows.append(Window(w_start, w_end, anchor_date.strftime(label_format)))
            year += 1
        return windows

    if window_type == "calendar_month":
        windows = []
        cursor = start.replace(day=1)
        while cursor <= end:
            w_start = max(cursor, start)
            w_end = min(_last_day_of_month(cursor), end)
            anchor_date = _anchor(w_start, w_end, anchor)
            windows.append(Window(w_start, w_end, anchor_date.strftime(label_format)))
            cursor = _add_one_month(cursor)
        return windows

    if window_type == "fixed_days":
        if size is None or size <= 0:
            raise ValueError("fixed_days requires size > 0")
        step_days = step if step is not None else size
        if step_days <= 0:
            raise ValueError("step must be > 0")
        windows = []
        cursor = start
        size_delta = timedelta(days=size)
        step_delta = timedelta(days=step_days)
        while cursor <= end:
            full_end = cursor + size_delta - timedelta(days=1)
            if full_end > end:
                break
            anchor_date = _anchor(cursor, full_end, anchor)
            windows.append(Window(cursor, full_end, anchor_date.strftime(label_format)))
            cursor += step_delta
        return windows

    raise ValueError(f"Unknown window type: {window_type}")
