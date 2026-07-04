"""Schedule business logic — add shifts, query schedules, detect understaffing."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.shift import LeaveRequest, Shift, ShiftType

log = logging.getLogger(__name__)

_TZ = ZoneInfo(settings.bot_timezone)

# Minimum staff per store per day (configurable)
MIN_STAFF_PER_DAY: int = 2

_SHIFT_HOURS: dict[ShiftType, tuple[time, time]] = {
    "早班":   (time(7, 0),  time(15, 0)),
    "午班":   (time(13, 30), time(18, 30)),
    "中班":   (time(11, 0), time(19, 0)),
    "晚班":   (time(18, 30), time(23, 30)),
    "大夜班": (time(23, 0), time(7, 0)),
    "全天班": (time(8, 0),  time(20, 0)),
}


def parse_time_range(text: str) -> tuple[time, time] | None:
    """Parse 'HH:MM-HH:MM' or 'H-H' → (start_time, end_time)."""
    text = text.strip()
    if "-" not in text:
        return None
    parts = text.split("-", 1)
    try:
        def _t(s: str) -> time:
            s = s.strip()
            if ":" in s:
                h, m = s.split(":")
                return time(int(h), int(m))
            return time(int(s), 0)
        return _t(parts[0]), _t(parts[1])
    except (ValueError, TypeError):
        return None


def week_range(ref: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the week containing *ref*."""
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


async def add_shift(
    shift_date: date,
    employee_id: str,
    employee_name: str,
    store: str,
    start_time: time,
    end_time: time,
    shift_type: ShiftType = "早班",
    notes: str = "",
) -> tuple[Shift, list[str]]:
    """Create a Shift, run compliance checks, write to Sheets.

    Returns (shift, warning_messages).
    """
    from app.utils.labor_rules import check_single_shift, check_consecutive_days
    from app.services.sheets_service import (
        append_shift, get_employee_shifts_in_range,
    )

    shift = Shift(
        shift_date=shift_date,
        employee_id=employee_id,
        employee_name=employee_name,
        store=store,
        start_time=start_time,
        end_time=end_time,
        shift_type=shift_type,
        notes=notes,
    )

    warnings: list[str] = []

    # Daily checks
    daily_warns = check_single_shift(shift)
    warnings.extend(w.message for w in daily_warns)

    # Consecutive days check: look at ±7 days
    monday, _ = week_range(shift_date)
    prev_monday = monday - timedelta(days=7)
    next_sunday = monday + timedelta(days=13)
    existing = await get_employee_shifts_in_range(employee_id, prev_monday, next_sunday)
    consec_warn = check_consecutive_days(existing, shift_date)
    if consec_warn:
        warnings.append(consec_warn.message)

    await append_shift(shift)
    return shift, warnings


async def get_my_shifts(employee_id: str, ref_date: date) -> list[Shift]:
    """Return this week's shifts for *employee_id*."""
    from app.services.sheets_service import get_employee_shifts_in_range
    monday, sunday = week_range(ref_date)
    return await get_employee_shifts_in_range(employee_id, monday, sunday)


async def get_store_day_shifts(store: str, target_date: date) -> list[Shift]:
    """Return all shifts for a store on a given date."""
    from app.services.sheets_service import get_shifts_by_date
    shifts = await get_shifts_by_date(target_date)
    if store:
        shifts = [s for s in shifts if s.store == store]
    return shifts


async def get_understaffed_days(
    store: str,
    from_date: date,
    to_date: date,
) -> list[tuple[date, int]]:
    """Return list of (date, staff_count) where count < MIN_STAFF_PER_DAY."""
    from app.services.sheets_service import get_shifts_by_date_range
    all_shifts = await get_shifts_by_date_range(from_date, to_date)
    if store:
        all_shifts = [s for s in all_shifts if s.store == store]

    by_date: dict[date, int] = {}
    d = from_date
    while d <= to_date:
        by_date[d] = 0
        d += timedelta(days=1)
    for s in all_shifts:
        if s.status == "正常":
            by_date[s.shift_date] = by_date.get(s.shift_date, 0) + 1

    return [(d, cnt) for d, cnt in sorted(by_date.items()) if cnt < MIN_STAFF_PER_DAY]


async def get_weekly_hours(employee_id: str, ref_date: date) -> dict[str, Any]:
    """Return weekly hours summary with labor compliance check."""
    from app.services.sheets_service import get_employee_shifts_in_range
    from app.utils.labor_rules import check_weekly

    monday, sunday = week_range(ref_date)
    shifts = await get_employee_shifts_in_range(employee_id, monday, sunday)
    stats = check_weekly(shifts)
    return {
        "week": f"{monday} ~ {sunday}",
        "workdays": stats.workdays,
        "normal_hours": stats.normal_hours,
        "overtime_hours": stats.overtime_hours,
        "total_hours": stats.total_hours,
        "warnings": [w.message for w in stats.warnings],
    }


async def submit_leave(
    employee_id: str,
    employee_name: str,
    leave_date: date,
    leave_type: str,
    reason: str,
) -> LeaveRequest:
    """Create a leave request and write to Sheets."""
    from app.services.sheets_service import append_leave_request

    now = datetime.now(_TZ).isoformat()
    req = LeaveRequest(
        apply_time=now,
        employee_id=employee_id,
        employee_name=employee_name,
        leave_date=leave_date,
        leave_type=leave_type,  # type: ignore[arg-type]
        reason=reason,
    )
    await append_leave_request(req)
    return req


def format_shift_list(shifts: list[Shift], title: str = "") -> str:
    """Format a list of shifts into a human-readable LINE message."""
    if not shifts:
        return f"{title}\n（暫無班表資料）" if title else "（暫無班表資料）"

    lines = [title] if title else []
    for s in sorted(shifts, key=lambda x: (x.shift_date, x.start_time)):
        from app.utils.tw_holidays import holiday_name
        holiday = holiday_name(s.shift_date)
        holi_tag = f" 🎌{holiday}" if holiday else ""
        status_tag = "" if s.status == "正常" else f" [{s.status}]"
        lines.append(
            f"📅 {s.shift_date} ({_weekday(s.shift_date)}){holi_tag}{status_tag}\n"
            f"   {s.employee_name} ▸ {s.store}\n"
            f"   {s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}"
            f"（{s.hours:.1f}h）{s.shift_type}"
        )
    return "\n\n".join(lines)


def _weekday(d: date) -> str:
    return ["一", "二", "三", "四", "五", "六", "日"][d.weekday()]
