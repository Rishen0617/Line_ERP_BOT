"""Slash command handler: /月報、/查帳、/訂單、/查 etc."""
from __future__ import annotations

import logging
from datetime import date

from app.line.reply import push_text

log = logging.getLogger(__name__)


async def handle_help(group_id: str, category: str = "") -> None:
    from app.config import settings
    trigger = settings.bot_trigger.strip()
    prefix = f"{trigger} " if trigger else ""
    footer = f"\n{'群組中請以「' + trigger + '」開頭呼叫' if trigger else '直接輸入指令即可'}"

    _CATEGORIES = {
        "記帳": "💰",
        "排班": "📅",
        "庫存": "📦",
        "電商": "🛒",
        "管理": "🌅",
        "查詢": "📊",
    }

    cat = category.strip()

    if not cat:
        # 首頁：顯示分類選單
        lines = [
            "📖 ERP Bot 功能選單",
            "─────────────────",
            "輸入 /help [分類] 查看詳細指令：",
            "",
            f"  /help 記帳   💰 文字記帳 & OCR",
            f"  /help 查詢   📊 月報/查帳/物流",
            f"  /help 排班   📅 班表/請假/缺工",
            f"  /help 庫存   📦 叫貨/到貨/採購預測",
            f"  /help 電商   🛒 訂單/付款/出貨",
            f"  /help 管理   🌅 晨報（管理員）",
            "",
            "📷 任何時候直接傳收據照片 → AI 自動辨識",
            footer,
        ]
        await push_text(group_id, "\n".join(lines))
        return

    if cat in ("記帳",):
        msg = (
            "💰 記帳功能\n"
            "─────────────────\n"
            "📷 上傳圖片\n"
            "  直接傳收據/發票/出貨單照片\n"
            "  → AI 自動辨識金額、廠商、單號\n\n"
            "✏️ 文字記帳\n"
            f"  {prefix}支出 3200 王老吉 進貨\n"
            f"  {prefix}收入 85000 客戶A 貨款\n"
            f"  {prefix}應付 12000 台塑 燃料費\n"
            f"  {prefix}應收 50000 客戶B 未付款\n\n"
            "⚠️ 金額超過 NT$100,000 自動警示管理員"
            + footer
        )

    elif cat in ("查詢",):
        msg = (
            "📊 查詢指令\n"
            "─────────────────\n"
            f"  {prefix}/月報          當月收支摘要\n"
            f"  {prefix}/月報 2026-04  指定月份\n"
            f"  {prefix}/查帳          最近 10 筆流水帳\n"
            f"  {prefix}/訂單          最近 5 筆叫貨訂單\n"
            f"  {prefix}/查 單號       查詢特定單據\n\n"
            "🚚 物流查詢（直接貼單號）\n"
            f"  {prefix}AB1234567890   黑貓宅急便\n"
            f"  {prefix}123456789012   7-11 統一速達\n"
            f"  {prefix}RR123456789TW  中華郵政"
            + footer
        )

    elif cat in ("排班",):
        msg = (
            "📅 排班系統\n"
            "─────────────────\n"
            "👤 員工自助\n"
            f"  {prefix}/查班表              我的本週班表\n"
            f"  {prefix}/查班表 2026-05-20   指定週班表\n"
            f"  {prefix}/我的工時            本週工時 & 加班統計\n"
            f"  {prefix}請假 2026-05-20 特休 家庭出遊\n\n"
            "👔 店長/行政\n"
            f"  {prefix}/今日班表 [店別]     今日出勤人員\n"
            f"  {prefix}/本週班表 [店別]     本週全店班表\n"
            f"  {prefix}/缺工               本週人力不足日\n"
            f"  {prefix}/新增班 2026-05-15 王小明 13:30-18:30 福星店 午班\n"
            f"  {prefix}/核假 王小明 2026-05-20\n\n"
            "假別：特休 事假 病假 婚假 喪假 補休 其他"
            + footer
        )

    elif cat in ("庫存",):
        msg = (
            "📦 庫存叫貨系統\n"
            "─────────────────\n"
            "🛍 叫貨作業\n"
            f"  {prefix}/叫貨 青蔥 5斤 福星店   登記叫貨（通知中央工廠）\n"
            f"  {prefix}/到貨 青蔥 5斤 福星店   確認到貨，庫存自動 +5\n"
            f"  {prefix}/消耗 醬油 2瓶 信義店   記錄消耗，庫存自動 -2\n"
            f"  {prefix}/盤點 青蔥 8斤 中央工廠 手動設定庫存（盤點用）\n\n"
            "📋 庫存查詢\n"
            f"  {prefix}/庫存               全部品項狀況\n"
            f"  {prefix}/庫存 青蔥          查單一品項\n"
            f"  {prefix}/低庫存             低於安全庫存清單\n"
            f"  {prefix}/採購預測           30日消耗分析+補貨建議\n\n"
            "⚙️ 設定\n"
            f"  {prefix}/安全庫存 青蔥 3    設定安全庫存警戒量"
            + footer
        )

    elif cat in ("電商",):
        msg = (
            "🛒 電商行政系統\n"
            "─────────────────\n"
            "📝 建立訂單\n"
            f"  {prefix}/新增訂單 蝦皮 王小明 580 冰心豆腐鍋 60\n"
            "  （平台：LINE購物 蝦皮 91App 官網 電話 其他）\n\n"
            "💳 付款/出貨流程\n"
            f"  {prefix}/訂單 SP05121234ABCD      查詢訂單\n"
            f"  {prefix}/確認付款 SP05121234ABCD  標記已付款\n"
            f"  {prefix}/出貨 SP05121234ABCD 黑貓 AB1234567890\n"
            f"  {prefix}/退款 SP05121234ABCD 客戶要求退貨\n"
            f"  {prefix}/取消訂單 SP05121234ABCD 重複下單\n\n"
            "📊 狀況總覽\n"
            f"  {prefix}/未付款   所有待付款清單 & 合計\n"
            f"  {prefix}/未出貨   所有待出貨清單\n"
            f"  {prefix}/電商日報 今日收單摘要\n\n"
            f"🏭 廠商管理\n"
            f"  {prefix}/廠商設定 大成農城 農產品收據 週結 004-帳號 戶名\n"
            f"  {prefix}/應付 大成農城     查詢待付款明細\n"
            f"  {prefix}/匯款 大成農城 2026-05-15  記錄匯款＋通知廠商"
            + footer
        )

    elif cat in ("管理",):
        msg = (
            "🌅 管理員指令\n"
            "─────────────────\n"
            "📰 晨報（限管理員）\n"
            f"  {prefix}/晨報              立即產生今日晨報\n"
            f"  {prefix}/晨報 2026-05-10   指定日期晨報\n\n"
            "晨報內容：\n"
            "  💰 昨日收支（含與上週同日比較）\n"
            "  📅 今日班表 & 缺工警示\n"
            "  📋 待審請假件數\n"
            "  📦 昨日叫貨 & 待到貨筆數\n"
            "  🔴 低庫存警示（有低庫存時顯示）"
            + footer
        )

    else:
        cats = "、".join(_CATEGORIES.keys())
        msg = f"找不到分類「{cat}」\n可用分類：{cats}\n\n輸入 /help 查看選單"

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
