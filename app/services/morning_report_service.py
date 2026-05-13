"""Morning report service — aggregates daily summary and pushes to admin LINE.

Triggered by:
  1. POST /api/morning-report/send  (Railway Cron / external scheduler)
  2. LINE command /晨報              (manual, admin only)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app.config import settings

log = logging.getLogger(__name__)
_TZ = ZoneInfo(settings.bot_timezone)

_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


async def build_report(ref_date: date | None = None) -> str:
    """Build the full morning report string for *ref_date* (defaults to today)."""
    import asyncio
    from datetime import datetime

    today = ref_date or date.today()
    yesterday = today - timedelta(days=1)
    weekday = _WEEKDAY_ZH[today.weekday()]

    sections: list[str] = []
    sections.append(f"🌅 明倫餐飲晨報 {today}（{weekday}）")
    sections.append("━━━━━━━━━━━━━━━")

    # Run all data fetches concurrently
    finance_task = asyncio.create_task(_finance_section(yesterday))
    schedule_task = asyncio.create_task(_schedule_section(today))
    pending_task = asyncio.create_task(_pending_section())
    order_task = asyncio.create_task(_order_section(yesterday))
    inventory_task = asyncio.create_task(_inventory_section())

    finance, schedule, pending, order, inventory = await asyncio.gather(
        finance_task, schedule_task, pending_task, order_task, inventory_task,
        return_exceptions=True,
    )

    for label, result in [
        ("finance", finance),
        ("schedule", schedule),
        ("pending", pending),
        ("order", order),
        ("inventory", inventory),
    ]:
        if isinstance(result, Exception):
            log.warning("morning report section %s failed: %s", label, result)
        elif result:
            sections.append(result)  # type: ignore[arg-type]

    sections.append("━━━━━━━━━━━━━━━")
    sections.append("輸入 /月報 查看本月完整報表")
    return "\n".join(sections)


async def send_morning_report(ref_date: date | None = None) -> bool:
    """Build and push the morning report to admin. Returns True on success."""
    if not settings.admin_line_user_id:
        log.warning("ADMIN_LINE_USER_ID not set; cannot send morning report")
        return False

    try:
        report = await build_report(ref_date)
        from app.line.reply import push_text
        await push_text(settings.admin_line_user_id, report)
        log.info("morning report sent to %s", settings.admin_line_user_id)
        return True
    except Exception as e:
        log.exception("send_morning_report failed: %s", e)
        return False


# ─── Section builders ─────────────────────────────────────────────────

async def _finance_section(yesterday: date) -> str:
    """昨日收支摘要（from 記帳流水帳）."""
    try:
        from app.services.sheets_service import get_monthly_summary
        # get yesterday's data by scanning the ledger for that date
        income, expense = await _day_finance(yesterday)
        net = income - expense
        net_sign = "+" if net >= 0 else ""
        prev_week_same = yesterday - timedelta(days=7)
        p_income, p_expense = await _day_finance(prev_week_same)
        p_net = p_income - p_expense

        diff = net - p_net
        trend = f"（較上週同日 {'↑' if diff >= 0 else '↓'} NT${abs(diff):,.0f}）"

        lines = [
            "💰 昨日財務",
            f"  收入：NT${income:,.0f}",
            f"  支出：NT${expense:,.0f}",
            f"  淨額：NT${net:,.0f} {trend}",
        ]
        return "\n".join(lines)
    except Exception as e:
        log.warning("_finance_section error: %s", e)
        return "💰 昨日財務（資料取得失敗）"


async def _day_finance(target: date) -> tuple[float, float]:
    """Sum income and expense for a single date from the ledger sheet."""
    import asyncio
    from app.services.sheets_service import _sheets
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range="記帳流水帳!A:D",
        ).execute()
    )
    rows = result.get("values", [])[1:]
    prefix = target.isoformat()
    income = expense = 0.0
    for r in rows:
        if len(r) < 4 or not str(r[0]).startswith(prefix):
            continue
        try:
            amt = float(r[3])
        except (ValueError, TypeError):
            continue
        cat = r[1] if len(r) > 1 else ""
        if cat == "收入":
            income += amt
        elif cat == "支出":
            expense += amt
    return income, expense


async def _schedule_section(today: date) -> str:
    """今日班表概況 + 缺工警示."""
    try:
        from app.services.sheets_service import get_shifts_by_date
        from app.utils.tw_holidays import holiday_name

        shifts = await get_shifts_by_date(today)
        active = [s for s in shifts if s.status == "正常"]

        holi = holiday_name(today)
        lines = [f"📅 今日班表{'（' + holi + '）' if holi else ''}"]

        if not active:
            lines.append("  ⚠️ 今日無排班資料")
            return "\n".join(lines)

        by_store: dict[str, list] = {}
        for s in active:
            by_store.setdefault(s.store, []).append(s)

        from app.services.schedule_service import MIN_STAFF_PER_DAY
        for store, store_shifts in sorted(by_store.items()):
            cnt = len(store_shifts)
            types = "／".join(s.shift_type for s in store_shifts)
            warn = " ⚠️缺工" if cnt < MIN_STAFF_PER_DAY else ""
            lines.append(f"  {store}：{cnt} 人（{types}）{warn}")

        return "\n".join(lines)
    except Exception as e:
        log.warning("_schedule_section error: %s", e)
        return "📅 今日班表（資料取得失敗）"


async def _pending_section() -> str:
    """待處理事項：請假待審 + 大額警示 (recent receipts with high confidence low)."""
    lines = ["📋 待處理事項"]
    try:
        leave_count = await _count_pending_leaves()
        if leave_count:
            lines.append(f"  • 請假待審：{leave_count} 件（輸入 /核假 處理）")
        else:
            lines.append("  • 請假待審：無")
    except Exception as e:
        log.warning("pending leaves error: %s", e)
        lines.append("  • 請假待審：（查詢失敗）")

    try:
        low_conf = await _count_low_confidence_receipts()
        if low_conf:
            lines.append(f"  • 低信心度收據待核對：{low_conf} 件")
    except Exception:
        pass

    return "\n".join(lines)


async def _count_pending_leaves() -> int:
    import asyncio
    from app.services.sheets_service import _sheets, SHEET_LEAVE
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_LEAVE}!G:G",
        ).execute()
    )
    rows = result.get("values", [])[1:]
    return sum(1 for r in rows if r and r[0] == "待審")


async def _count_low_confidence_receipts() -> int:
    """Count recent (last 30 rows) receipts with confidence = 低."""
    import asyncio
    from app.services.sheets_service import _sheets, SHEET_RECEIPTS
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_RECEIPTS}!K:K",
        ).execute()
    )
    rows = result.get("values", [])[1:]
    recent = rows[-30:] if len(rows) > 30 else rows
    return sum(1 for r in recent if r and r[0] == "低")


async def _order_section(yesterday: date) -> str:
    """昨日叫貨 + 待到貨統計."""
    try:
        import asyncio
        from app.services.sheets_service import _sheets, SHEET_ORDERS
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ORDERS}!A:E",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        yesterday_str = yesterday.isoformat()
        new_orders = sum(1 for r in rows if len(r) > 0 and r[0] == yesterday_str)
        pending = sum(1 for r in rows if len(r) > 4 and r[4] in ("待確認", "已確認", "出貨中"))

        lines = ["📦 補貨狀況"]
        lines.append(f"  昨日新叫貨：{new_orders} 筆")
        if pending:
            lines.append(f"  待到貨／處理中：{pending} 筆")
        else:
            lines.append("  無待處理訂單")
        return "\n".join(lines)
    except Exception as e:
        log.warning("_order_section error: %s", e)
        return "📦 補貨狀況（資料取得失敗）"


async def _inventory_section() -> str:
    """低庫存品項警示（只有有低庫存時才顯示）."""
    try:
        from app.services.inventory_service import get_low_stock_items
        low = await get_low_stock_items()
        if not low:
            return ""   # 庫存正常時不佔版面
        lines = [f"🔴 低庫存警示（{len(low)} 項需補貨）"]
        for it in low:
            lines.append(
                f"  {it.name}：{it.current_stock:.1f}/{it.safety_stock:.1f} {it.unit}"
            )
        lines.append("輸入 /採購預測 查看補貨建議")
        return "\n".join(lines)
    except Exception as e:
        log.warning("_inventory_section error: %s", e)
        return ""
