"""Taiwan public holidays (固定假日 + 彈性補假).

Fixed national holidays are listed here. Lunar calendar holidays (Spring Festival,
Dragon Boat, Mid-Autumn) change each year — update the LUNAR_HOLIDAYS dict annually
or override via the EXTRA_HOLIDAYS environment variable (comma-separated YYYY-MM-DD).

Reference: 行政院人事行政總處 https://www.dgpa.gov.tw/
"""
from __future__ import annotations

import os
from datetime import date

# ── Fixed annual holidays (month, day) ────────────────────────────────
_FIXED: set[tuple[int, int]] = {
    (1, 1),    # 元旦
    (2, 28),   # 和平紀念日
    (4, 4),    # 兒童節
    (5, 1),    # 勞動節
    (10, 10),  # 國慶日
}

# ── Lunar calendar holidays — update each year ────────────────────────
# Format: "YYYY-MM-DD"
_LUNAR_HOLIDAYS_2025: set[str] = {
    "2025-01-28", "2025-01-29", "2025-01-30",  # 春節
    "2025-01-31", "2025-02-01", "2025-02-02",
    "2025-04-05",  # 清明節
    "2025-05-31",  # 端午節
    "2025-10-06",  # 中秋節
}

_LUNAR_HOLIDAYS_2026: set[str] = {
    "2026-01-17", "2026-01-18", "2026-01-19",  # 春節
    "2026-01-20", "2026-01-21", "2026-01-22",
    "2026-04-05",  # 清明節
    "2026-06-20",  # 端午節 (approximate)
    "2026-09-25",  # 中秋節 (approximate)
}

_LUNAR_BY_YEAR: dict[int, set[str]] = {
    2025: _LUNAR_HOLIDAYS_2025,
    2026: _LUNAR_HOLIDAYS_2026,
}


def _extra_holidays() -> set[str]:
    raw = os.environ.get("EXTRA_HOLIDAYS", "")
    return {d.strip() for d in raw.split(",") if d.strip()}


def is_holiday(d: date) -> bool:
    """Return True if *d* is a Taiwan public holiday."""
    if (d.month, d.day) in _FIXED:
        return True
    iso = d.isoformat()
    year_set = _LUNAR_BY_YEAR.get(d.year, set())
    if iso in year_set:
        return True
    if iso in _extra_holidays():
        return True
    return False


def holiday_name(d: date) -> str | None:
    """Return Chinese holiday name, or None if not a holiday."""
    names: dict[tuple[int, int], str] = {
        (1, 1): "元旦",
        (2, 28): "和平紀念日",
        (4, 4): "兒童節",
        (5, 1): "勞動節",
        (10, 10): "國慶日",
    }
    if (d.month, d.day) in names:
        return names[(d.month, d.day)]
    if is_holiday(d):
        return "國定假日"
    return None
