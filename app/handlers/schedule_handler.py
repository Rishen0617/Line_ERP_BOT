"""LINE command handlers for the scheduling system.

Supported commands:
  Employee
    /查班表 [YYYY-MM-DD]   — 查自己本週（或指定週）班表
    /我的工時 [YYYY-MM-DD] — 查自己本週工時與加班狀況
    請假 YYYY-MM-DD [假別] [原因]

  Manager / Admin
    /今日班表 [店別]        — 今日所有班次
    /本週班表 [店別]        — 本週所有班次
    /缺工 [店別]            — 查本週缺工日
    /新增班 YYYY-MM-DD 員工名 HH:MM-HH:MM 店別 [班別]
    /核假 員工名 YYYY-MM-DD — 核准請假
"""
from __future__ import annotations

import logging
import re
from datetime import date, time, timedelta

from app.line.reply import push_text

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RANGE_RE = re.compile(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}|\d{1,2}-\d{1,2}")


# ─── Public dispatch ─────────────────────────────────────────────────

async def handle_schedule_command(
    text: str,
    user_id: str,
    group_id: str,
) -> None:
    stripped = text.strip()

    if stripped.startswith("/查班表"):
        await _cmd_my_schedule(stripped, user_id, group_id)
    elif stripped.startswith("/我的工時"):
        await _cmd_my_hours(stripped, user_id, group_id)
    elif stripped.startswith("/今日班表"):
        await _cmd_today(stripped, group_id)
    elif stripped.startswith("/本週班表"):
        await _cmd_week(stripped, group_id)
    elif stripped.startswith("/缺工"):
        await _cmd_understaffed(stripped, group_id)
    elif stripped.startswith("/新增班"):
        await _cmd_add_shift(stripped, user_id, group_id)
    elif stripped.startswith("/核假"):
        await _cmd_approve_leave(stripped, user_id, group_id)
    elif _is_leave_request(stripped):
        await _cmd_leave_request(stripped, user_id, group_id)


def _is_leave_request(text: str) -> bool:
    return text.startswith("請假")


# ─── /查班表 ──────────────────────────────────────────────────────────

async def _cmd_my_schedule(text: str, user_id: str, group_id: str) -> None:
    from app.services.schedule_service import get_my_shifts, format_shift_list

    ref = _extract_date(text) or date.today()
    try:
        shifts = await get_my_shifts(user_id, ref)
        monday = ref - timedelta(days=ref.weekday())
        sunday = monday + timedelta(days=6)
        title = f"📅 本週班表（{monday} ~ {sunday}）"
        await push_text(group_id, format_shift_list(shifts, title))
    except Exception as e:
        log.error("_cmd_my_schedule error: %s", e)
        await push_text(group_id, f"⚠️ 查詢班表失敗：{e}")


# ─── /我的工時 ────────────────────────────────────────────────────────

async def _cmd_my_hours(text: str, user_id: str, group_id: str) -> None:
    from app.services.schedule_service import get_weekly_hours

    ref = _extract_date(text) or date.today()
    try:
        stats = await get_weekly_hours(user_id, ref)
        lines = [
            f"⏱ 工時統計（{stats['week']}）",
            f"出勤天數：{stats['workdays']} 天",
            f"正常工時：{stats['normal_hours']:.1f} h",
            f"加班工時：{stats['overtime_hours']:.1f} h",
            f"本週合計：{stats['total_hours']:.1f} h",
        ]
        if stats["warnings"]:
            lines.append("─────────────")
            lines.extend(stats["warnings"])
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        log.error("_cmd_my_hours error: %s", e)
        await push_text(group_id, f"⚠️ 查詢工時失敗：{e}")


# ─── /今日班表 ────────────────────────────────────────────────────────

async def _cmd_today(text: str, group_id: str) -> None:
    from app.services.schedule_service import get_store_day_shifts, format_shift_list

    store = _extract_store(text, prefix="/今日班表")
    target = date.today()
    try:
        shifts = await get_store_day_shifts(store, target)
        title = f"📋 今日班表 {target}（{store or '全店'}）"
        await push_text(group_id, format_shift_list(shifts, title))
    except Exception as e:
        log.error("_cmd_today error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /本週班表 ────────────────────────────────────────────────────────

async def _cmd_week(text: str, group_id: str) -> None:
    from app.services.schedule_service import format_shift_list
    from app.services.sheets_service import get_shifts_by_date_range
    from app.services.schedule_service import week_range

    store = _extract_store(text, prefix="/本週班表")
    monday, sunday = week_range(date.today())
    try:
        shifts = await get_shifts_by_date_range(monday, sunday)
        if store:
            shifts = [s for s in shifts if s.store == store]
        title = f"📋 本週班表（{monday} ~ {sunday}）{store or ''}"
        await push_text(group_id, format_shift_list(shifts, title))
    except Exception as e:
        log.error("_cmd_week error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /缺工 ───────────────────────────────────────────────────────────

async def _cmd_understaffed(text: str, group_id: str) -> None:
    from app.services.schedule_service import get_understaffed_days, week_range

    store = _extract_store(text, prefix="/缺工")
    monday, sunday = week_range(date.today())
    try:
        gaps = await get_understaffed_days(store, monday, sunday)
        if not gaps:
            await push_text(
                group_id,
                f"✅ 本週（{monday} ~ {sunday}）{store or '全店'}班表充足，無缺工"
            )
            return
        lines = [f"⚠️ 本週缺工日（{store or '全店'}）："]
        for d, cnt in gaps:
            lines.append(f"  {d} — 目前 {cnt} 人（最低需 2 人）")
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        log.error("_cmd_understaffed error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /新增班 YYYY-MM-DD 員工名 HH:MM-HH:MM 店別 [班別] ───────────────

async def _cmd_add_shift(text: str, user_id: str, group_id: str) -> None:
    from app.config import settings
    if not settings.is_manager(user_id):
        await push_text(group_id, "⛔ 此指令限店長使用。")
        return

    from app.services.schedule_service import add_shift, _SHIFT_HOURS, format_shift_list

    # Parse: /新增班 2026-05-15 王小明 09:00-17:00 福星店 早班
    parts = text.split()
    # parts[0] = "/新增班", [1]=date, [2]=name, [3]=time_range, [4]=store, [5?]=shift_type
    if len(parts) < 5:
        await push_text(
            group_id,
            "格式：/新增班 YYYY-MM-DD 員工名 HH:MM-HH:MM 店別 [班別]\n"
            "範例：/新增班 2026-05-15 王小明 09:00-17:00 福星店 早班"
        )
        return

    try:
        shift_date = date.fromisoformat(parts[1])
    except ValueError:
        await push_text(group_id, "⚠️ 日期格式錯誤，請用 YYYY-MM-DD")
        return

    employee_name = parts[2]

    from app.services.schedule_service import parse_time_range
    parsed_times = parse_time_range(parts[3])
    if not parsed_times:
        await push_text(group_id, "⚠️ 時間格式錯誤，請用 HH:MM-HH:MM，例如 09:00-17:00")
        return
    start_time, end_time = parsed_times

    store = parts[4]
    shift_type = parts[5] if len(parts) > 5 else "午班"
    valid_types = list(_SHIFT_HOURS.keys())
    if shift_type not in valid_types:
        shift_type = "午班"

    try:
        shift, warnings = await add_shift(
            shift_date=shift_date,
            employee_id=f"manual:{employee_name}",
            employee_name=employee_name,
            store=store,
            start_time=start_time,
            end_time=end_time,
            shift_type=shift_type,  # type: ignore[arg-type]
        )
        msg_lines = [
            f"✅ 班次已新增",
            f"員工：{employee_name}",
            f"日期：{shift_date}",
            f"時間：{start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}（{shift.hours:.1f}h）",
            f"店別：{store}  班別：{shift_type}",
        ]
        if warnings:
            msg_lines.append("─────────────")
            msg_lines.extend(warnings)
        await push_text(group_id, "\n".join(msg_lines))
    except Exception as e:
        log.error("_cmd_add_shift error: %s", e)
        await push_text(group_id, f"⚠️ 新增班次失敗：{e}")


# ─── 請假 YYYY-MM-DD [假別] [原因] ───────────────────────────────────

async def _cmd_leave_request(text: str, user_id: str, group_id: str) -> None:
    from app.services.schedule_service import submit_leave

    # "請假 2026-05-20 特休 家庭出遊"
    parts = text.split(maxsplit=3)
    if len(parts) < 2:
        await push_text(group_id, "格式：請假 YYYY-MM-DD [假別] [原因]\n例如：請假 2026-05-20 特休 家庭出遊")
        return

    try:
        leave_date = date.fromisoformat(parts[1])
    except ValueError:
        await push_text(group_id, "⚠️ 日期格式錯誤，請用 YYYY-MM-DD")
        return

    valid_types = ["特休", "事假", "病假", "婚假", "喪假", "補休", "其他"]
    leave_type = "事假"
    reason = ""
    if len(parts) > 2:
        if parts[2] in valid_types:
            leave_type = parts[2]
            reason = parts[3] if len(parts) > 3 else ""
        else:
            reason = " ".join(parts[2:])

    try:
        user_name = await _fetch_user_name(user_id)
        req = await submit_leave(
            employee_id=user_id,
            employee_name=user_name,
            leave_date=leave_date,
            leave_type=leave_type,
            reason=reason,
        )
        await push_text(
            group_id,
            f"✅ 請假申請已送出\n"
            f"日期：{req.leave_date}\n"
            f"假別：{req.leave_type}\n"
            f"原因：{req.reason or '（未填）'}\n"
            f"狀態：{req.status}（等待主管核准）"
        )
        # Notify admin if configured
        from app.config import settings as cfg
        if cfg.admin_line_user_id:
            await push_text(
                cfg.admin_line_user_id,
                f"📋 請假申請通知\n"
                f"員工：{user_name}\n"
                f"日期：{req.leave_date}\n"
                f"假別：{req.leave_type}\n"
                f"原因：{req.reason or '（未填）'}\n"
                f"輸入 /核假 {user_name} {req.leave_date} 核准"
            )
    except Exception as e:
        log.error("_cmd_leave_request error: %s", e)
        await push_text(group_id, f"⚠️ 請假申請失敗：{e}")


# ─── /核假 員工名 YYYY-MM-DD ──────────────────────────────────────────

async def _cmd_approve_leave(text: str, user_id: str, group_id: str) -> None:
    from app.config import settings
    if not settings.is_manager(user_id):
        await push_text(group_id, "⛔ 此指令限店長使用。")
        return

    from app.services.sheets_service import approve_leave_request

    parts = text.split()
    if len(parts) < 3:
        await push_text(group_id, "格式：/核假 員工名 YYYY-MM-DD")
        return

    employee_name = parts[1]
    try:
        leave_date = date.fromisoformat(parts[2])
    except ValueError:
        await push_text(group_id, "⚠️ 日期格式錯誤")
        return

    try:
        reviewer_name = await _fetch_user_name(user_id)
        updated = await approve_leave_request(employee_name, leave_date, reviewer_name)
        if updated:
            await push_text(
                group_id,
                f"✅ 已核准 {employee_name} {leave_date} 的請假\n核准人：{reviewer_name}"
            )
        else:
            await push_text(group_id, f"找不到 {employee_name} 在 {leave_date} 的待審請假")
    except Exception as e:
        log.error("_cmd_approve_leave error: %s", e)
        await push_text(group_id, f"⚠️ 核假失敗：{e}")


# ─── helpers ──────────────────────────────────────────────────────────

def _extract_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m:
        try:
            return date.fromisoformat(m.group())
        except ValueError:
            pass
    return None


def _extract_store(text: str, prefix: str) -> str:
    rest = text[len(prefix):].strip()
    # Remove any date
    rest = _DATE_RE.sub("", rest).strip()
    return rest


async def _fetch_user_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id
