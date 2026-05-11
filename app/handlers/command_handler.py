"""Slash command handler: /月報、/查帳、/訂單、/查 etc."""
from __future__ import annotations

import logging
from datetime import date

from app.line.reply import push_text

log = logging.getLogger(__name__)


async def handle_help(group_id: str) -> None:
    from app.config import settings
    trigger = settings.bot_trigger.strip()
    prefix = f"{trigger} " if trigger else ""

    msg = (
        "📖 ERP Bot 使用說明\n"
        "─────────────────\n"
        "📷 上傳圖片\n"
        "  直接傳送收據、發票、出貨單照片\n"
        "  → AI 自動辨識，存入 Sheets\n\n"
        "💰 文字記帳\n"
        f"  {prefix}支出 3200 王老吉 進貨\n"
        f"  {prefix}收入 85000 客戶A 貨款\n"
        f"  {prefix}應付 12000 台塑 燃料費\n\n"
        "📦 叫貨訂單\n"
        f"  {prefix}叫貨 統一 泡麵 100箱\n"
        f"  {prefix}訂購 聯華 洋芋片 50箱\n\n"
        "🚚 物流查詢\n"
        f"  {prefix}AB1234567890（黑貓單號）\n"
        f"  {prefix}123456789012（7-11 單號）\n\n"
        "📊 查詢指令\n"
        f"  {prefix}/月報        當月收支摘要\n"
        f"  {prefix}/月報 2026-04 指定月份\n"
        f"  {prefix}/查帳        最近 10 筆流水帳\n"
        f"  {prefix}/訂單        最近 5 筆訂單\n"
        f"  {prefix}/查 單號     查詢特定單據\n\n"
        "─────────────────\n"
        f"{'群組中請以「' + trigger + '」開頭呼叫' if trigger else '直接輸入指令即可'}"
    )
    await push_text(group_id, msg)


async def handle_command(
    text: str,
    reply_token: str,
    user_id: str,
    group_id: str,
) -> None:
    stripped = text.strip()

    if stripped.startswith("/月報"):
        await _monthly_report(stripped, group_id)

    elif stripped.startswith("/查帳"):
        await _query_ledger(stripped, group_id)

    elif stripped.startswith("/訂單"):
        await _query_orders(stripped, group_id)

    elif stripped.startswith("/查 ") or stripped.startswith("/查"):
        doc_number = stripped[2:].strip()
        await _query_receipt(doc_number, group_id)

    else:
        await push_text(
            group_id,
            "可用指令：\n"
            "/月報 [YYYY-MM] — 當月收支摘要\n"
            "/查帳 — 最近 10 筆流水帳\n"
            "/訂單 — 最近訂單狀態\n"
            "/查 單號 — 查詢特定單據",
        )


async def _monthly_report(text: str, group_id: str) -> None:
    from app.services.sheets_service import get_monthly_summary

    # Parse optional YYYY-MM arg, e.g. "/月報 2026-04"
    parts = text.split()
    today = date.today()
    year, month = today.year, today.month
    if len(parts) > 1:
        try:
            ym = parts[1].split("-")
            year, month = int(ym[0]), int(ym[1])
        except (ValueError, IndexError):
            pass

    try:
        s = await get_monthly_summary(year, month)
        msg = (
            f"📊 {year}年{month}月 收支摘要\n"
            f"💚 收入：NT${s['income']:,.0f}\n"
            f"❤️  支出：NT${s['expense']:,.0f}\n"
            f"📋 應收：NT${s['receivable']:,.0f}\n"
            f"📋 應付：NT${s['payable']:,.0f}\n"
            f"─────────────\n"
            f"{'✅' if s['net'] >= 0 else '⚠️'} 淨額：NT${s['net']:,.0f}"
        )
    except Exception as e:
        msg = f"⚠️ 月報查詢失敗：{e}"

    await push_text(group_id, msg)


async def _query_ledger(text: str, group_id: str) -> None:
    """Show last 10 ledger rows — reads Sheets directly."""
    import asyncio
    from app.config import settings
    from app.services.sheets_service import _sheets

    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range="記帳流水帳!A:G",
            ).execute()
        )
        rows = result.get("values", [])[1:]  # skip header
        if not rows:
            await push_text(group_id, "流水帳目前沒有資料。")
            return
        last10 = rows[-10:]
        lines = ["📒 最近 10 筆流水帳："]
        for r in last10:
            date_s = r[0] if len(r) > 0 else ""
            cat = r[1] if len(r) > 1 else ""
            desc = r[2][:16] if len(r) > 2 else ""
            amt = r[3] if len(r) > 3 else ""
            lines.append(f"{date_s} {cat} {amt} {desc}")
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        await push_text(group_id, f"⚠️ 查帳失敗：{e}")


async def _query_orders(text: str, group_id: str) -> None:
    import asyncio
    from app.config import settings
    from app.services.sheets_service import _sheets

    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range="訂單追蹤!A:G",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        if not rows:
            await push_text(group_id, "訂單追蹤目前沒有資料。")
            return
        last5 = rows[-5:]
        lines = ["📦 最近 5 筆訂單："]
        for r in last5:
            date_s = r[0] if len(r) > 0 else ""
            supplier = r[1] if len(r) > 1 else ""
            summary = r[2][:20] if len(r) > 2 else ""
            status = r[4] if len(r) > 4 else ""
            lines.append(f"{date_s} {supplier} [{status}] {summary}")
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        await push_text(group_id, f"⚠️ 訂單查詢失敗：{e}")


async def _query_receipt(doc_number: str, group_id: str) -> None:
    if not doc_number:
        await push_text(group_id, "請輸入單號，例如：/查 AB-12345678")
        return
    from app.services.sheets_service import find_by_doc_number
    try:
        result = await find_by_doc_number(doc_number)
        if result:
            await push_text(group_id, f"✅ 找到單號 {doc_number}（第 {result['row']} 列）")
        else:
            await push_text(group_id, f"找不到單號 {doc_number}，請確認是否已上傳。")
    except Exception as e:
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")
