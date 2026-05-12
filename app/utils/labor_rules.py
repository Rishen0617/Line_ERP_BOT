"""Taiwan Labor Standards Act (勞動基準法) compliance checker.

Key rules implemented:
  - Art. 30: Normal working hours ≤ 8 hrs/day, ≤ 40 hrs/week
  - Art. 32: Overtime ≤ 4 hrs/day, ≤ 12 hrs/week (total ≤ 54 hrs/week incl. OT)
  - Art. 35: Rest break ≥ 30 min after every 4 consecutive working hours
  - Art. 36: At least 1 rest day per 7-day period (max 6 consecutive workdays)
  - Art. 37: Mandatory rest on national holidays
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.shift import Shift

NORMAL_HOURS_PER_DAY = 8.0
MAX_OVERTIME_PER_DAY = 4.0          # 每日加班上限
MAX_TOTAL_HOURS_PER_DAY = 12.0      # 正常 + 加班
MAX_OVERTIME_PER_WEEK = 12.0        # 每週加班上限
MAX_NORMAL_HOURS_PER_WEEK = 40.0
MAX_TOTAL_HOURS_PER_WEEK = 54.0     # 40 + 12 + 2-hour exception margin
MAX_CONSECUTIVE_WORKDAYS = 6


@dataclass
class ViolationWarning:
    rule: str
    message: str
    shift_date: date | None = None
    severity: str = "警告"           # 警告 | 違規


@dataclass
class WeeklyStats:
    week_start: date
    normal_hours: float = 0.0
    overtime_hours: float = 0.0
    workdays: int = 0
    warnings: list[ViolationWarning] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        return self.normal_hours + self.overtime_hours


def check_single_shift(shift: "Shift") -> list[ViolationWarning]:
    """Check a single shift for daily rule violations."""
    from app.utils.tw_holidays import is_holiday

    warnings: list[ViolationWarning] = []
    h = shift.hours

    if is_holiday(shift.shift_date):
        hn = shift.shift_date.strftime("%Y-%m-%d")
        warnings.append(ViolationWarning(
            rule="Art.37",
            message=f"⚠️ {hn} 為國定假日，安排出勤需依法加倍給薪",
            shift_date=shift.shift_date,
            severity="警告",
        ))

    if h > MAX_TOTAL_HOURS_PER_DAY:
        warnings.append(ViolationWarning(
            rule="Art.32",
            message=f"❌ {shift.shift_date} 工時 {h:.1f}h 超過每日上限 {MAX_TOTAL_HOURS_PER_DAY}h",
            shift_date=shift.shift_date,
            severity="違規",
        ))
    elif h > NORMAL_HOURS_PER_DAY:
        ot = h - NORMAL_HOURS_PER_DAY
        warnings.append(ViolationWarning(
            rule="Art.32",
            message=f"⚠️ {shift.shift_date} 加班 {ot:.1f}h，請確認員工同意",
            shift_date=shift.shift_date,
            severity="警告",
        ))

    # 連續工作 4 小時未提供休息 30 分鐘（班次設計提示）
    if h >= 4:
        start_mins = shift.start_time.hour * 60 + shift.start_time.minute
        end_mins = shift.end_time.hour * 60 + shift.end_time.minute
        if end_mins <= start_mins:
            end_mins += 24 * 60
        span_mins = end_mins - start_mins
        # heuristic: if span barely equals hours → no break built in
        if span_mins <= h * 60:
            warnings.append(ViolationWarning(
                rule="Art.35",
                message=f"⚠️ {shift.shift_date} 工時達 {h:.0f}h，請確認已安排 30 分鐘休息",
                shift_date=shift.shift_date,
                severity="警告",
            ))

    return warnings


def check_weekly(shifts: list["Shift"]) -> WeeklyStats:
    """Analyse a list of shifts (same employee, any date range) for weekly violations."""
    if not shifts:
        return WeeklyStats(week_start=date.today())

    sorted_shifts = sorted(shifts, key=lambda s: s.shift_date)
    week_start = sorted_shifts[0].shift_date

    stats = WeeklyStats(week_start=week_start)
    for s in sorted_shifts:
        if s.hours <= NORMAL_HOURS_PER_DAY:
            stats.normal_hours += s.hours
        else:
            stats.normal_hours += NORMAL_HOURS_PER_DAY
            stats.overtime_hours += s.hours - NORMAL_HOURS_PER_DAY
        stats.workdays += 1

    if stats.overtime_hours > MAX_OVERTIME_PER_WEEK:
        stats.warnings.append(ViolationWarning(
            rule="Art.32",
            message=(
                f"❌ 本週加班 {stats.overtime_hours:.1f}h 超過法定上限 {MAX_OVERTIME_PER_WEEK}h"
            ),
            severity="違規",
        ))

    if stats.total_hours > MAX_TOTAL_HOURS_PER_WEEK:
        stats.warnings.append(ViolationWarning(
            rule="Art.32",
            message=f"❌ 本週總工時 {stats.total_hours:.1f}h 超過 {MAX_TOTAL_HOURS_PER_WEEK}h",
            severity="違規",
        ))

    if stats.workdays > MAX_CONSECUTIVE_WORKDAYS:
        stats.warnings.append(ViolationWarning(
            rule="Art.36",
            message=(
                f"❌ 連續出勤 {stats.workdays} 天，超過法定 {MAX_CONSECUTIVE_WORKDAYS} 天上限"
            ),
            severity="違規",
        ))

    return stats


def check_consecutive_days(
    employee_shifts: list["Shift"],
    new_shift_date: date,
) -> ViolationWarning | None:
    """Check if adding a shift on *new_shift_date* would exceed consecutive workday limit."""
    work_dates = {s.shift_date for s in employee_shifts}
    work_dates.add(new_shift_date)

    streak = 1
    d = new_shift_date - timedelta(days=1)
    while d in work_dates:
        streak += 1
        d -= timedelta(days=1)

    d = new_shift_date + timedelta(days=1)
    while d in work_dates:
        streak += 1
        d += timedelta(days=1)

    if streak > MAX_CONSECUTIVE_WORKDAYS:
        return ViolationWarning(
            rule="Art.36",
            message=(
                f"⚠️ 新增 {new_shift_date} 後將連續出勤 {streak} 天，"
                f"超過法定 {MAX_CONSECUTIVE_WORKDAYS} 天"
            ),
            shift_date=new_shift_date,
            severity="警告",
        )
    return None


def format_warnings(warnings: list[ViolationWarning]) -> str:
    if not warnings:
        return ""
    lines = [f"{w.severity}：{w.message}" for w in warnings]
    return "\n".join(lines)
