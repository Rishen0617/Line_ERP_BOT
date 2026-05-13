"""LINE command handlers for e-commerce administration.

Commands
--------
Employee / Admin
  /新增訂單 平台 客戶名 金額 品項 [運費]
      範例：/新增訂單 蝦皮 王小明 580 冰心豆腐鍋 60
  /訂單 訂單編號
      查詢訂單詳細狀態
  /確認付款 訂單編號
      標記訂單已付款
  /出貨 訂單編號 物流 單號
      範例：/出貨 SP05121234 黑貓 AB1234567890
  /退款 訂單編號 原因
  /取消訂單 訂單編號 原因
  /未付款
      列出所有待付款訂單
  /未出貨
      列出所有待出貨訂單
  /電商日報 [YYYY-MM-DD]
      當日電商收單摘要
"""
from __future__ import annotations

import logging
import re

from app.line.reply import push_text

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


async def handle_ecommerce_command(
    text: str,
    user_id: str,
    group_id: str,
) -> None:
    s = text.strip()

    if s.startswith("/新增訂單"):
        await _cmd_new_order(s, user_id, group_id)
    elif s.startswith("/訂單"):
        await _cmd_query_order(s, group_id)
    elif s.startswith("/確認付款"):
        await _cmd_confirm_payment(s, user_id, group_id)
    elif s.startswith("/出貨"):
        await _cmd_ship(s, user_id, group_id)
    elif s.startswith("/退款"):
        await _cmd_refund(s, user_id, group_id)
    elif s.startswith("/取消訂單"):
        await _cmd_cancel(s, user_id, group_id)
    elif s.startswith("/未付款"):
        await _cmd_list_unpaid(group_id)
    elif s.startswith("/未出貨"):
        await _cmd_list_unshipped(group_id)
    elif s.startswith("/電商日報"):
        await _cmd_daily_summary(s, group_id)


# ─── /新增訂單 平台 客戶 金額 品項 [運費] ────────────────────────────

async def _cmd_new_order(text: str, user_id: str, group_id: str) -> None:
    from app.services.ecommerce_service import create_order, format_order

    # /新增訂單 蝦皮 王小明 580 冰心豆腐鍋 60
    parts = text.split(maxsplit=5)
    if len(parts) < 5:
        await push_text(
            group_id,
            "格式：/新增訂單 平台 客戶名 金額 品項 [運費]\n"
            "平台可選：LINE購物 蝦皮 91App 官網 電話 其他\n"
            "範例：/新增訂單 蝦皮 王小明 580 冰心豆腐鍋 60",
        )
        return

    platform = parts[1]
    customer_name = parts[2]
    try:
        total = float(parts[3].replace(",", ""))
    except ValueError:
        await push_text(group_id, "⚠️ 金額格式錯誤，請輸入數字")
        return
    items = parts[4]
    shipping_fee = 0.0
    if len(parts) > 5:
        try:
            shipping_fee = float(parts[5].replace(",", ""))
        except ValueError:
            pass

    try:
        order = await create_order(
            platform=platform,
            customer_name=customer_name,
            items_summary=items,
            total_amount=total,
            shipping_fee=shipping_fee,
            created_by=user_id,
        )
        await push_text(
            group_id,
            f"✅ 訂單已建立\n{format_order(order)}"
        )
    except Exception as e:
        log.error("_cmd_new_order error: %s", e)
        await push_text(group_id, f"⚠️ 建立訂單失敗：{e}")


# ─── /訂單 訂單編號 ───────────────────────────────────────────────────

async def _cmd_query_order(text: str, group_id: str) -> None:
    from app.services.ecommerce_service import get_order, format_order

    parts = text.split()
    if len(parts) < 2:
        await push_text(group_id, "格式：/訂單 訂單編號\n範例：/訂單 SP05121234ABCD")
        return

    order_no = parts[1]
    try:
        order = await get_order(order_no)
        if order:
            await push_text(group_id, format_order(order))
        else:
            await push_text(group_id, f"找不到訂單 {order_no}，請確認編號是否正確")
    except Exception as e:
        log.error("_cmd_query_order error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /確認付款 訂單編號 ───────────────────────────────────────────────

async def _cmd_confirm_payment(text: str, user_id: str, group_id: str) -> None:
    from app.services.ecommerce_service import confirm_payment

    parts = text.split()
    if len(parts) < 2:
        await push_text(group_id, "格式：/確認付款 訂單編號")
        return

    order_no = parts[1]
    operator = await _fetch_user_name(user_id)
    try:
        ok = await confirm_payment(order_no, operator)
        if ok:
            await push_text(group_id, f"✅ 訂單 {order_no} 已標記為「已付款」\n確認人：{operator}")
        else:
            await push_text(group_id, f"找不到訂單 {order_no}")
    except Exception as e:
        log.error("_cmd_confirm_payment error: %s", e)
        await push_text(group_id, f"⚠️ 操作失敗：{e}")


# ─── /出貨 訂單編號 物流 單號 ─────────────────────────────────────────

async def _cmd_ship(text: str, user_id: str, group_id: str) -> None:
    from app.services.ecommerce_service import ship_order

    # /出貨 SP05121234ABCD 黑貓 AB1234567890
    parts = text.split()
    if len(parts) < 4:
        await push_text(
            group_id,
            "格式：/出貨 訂單編號 物流公司 物流單號\n"
            "範例：/出貨 SP05121234 黑貓 AB1234567890",
        )
        return

    order_no = parts[1]
    logistics = parts[2]
    tracking = parts[3]
    operator = await _fetch_user_name(user_id)

    try:
        ok = await ship_order(order_no, logistics, tracking, operator)
        if ok:
            await push_text(
                group_id,
                f"🚚 訂單 {order_no} 已出貨\n"
                f"物流：{logistics}\n"
                f"單號：{tracking}\n"
                f"操作人：{operator}"
            )
        else:
            await push_text(group_id, f"找不到訂單 {order_no}")
    except Exception as e:
        log.error("_cmd_ship error: %s", e)
        await push_text(group_id, f"⚠️ 操作失敗：{e}")


# ─── /退款 訂單編號 原因 ──────────────────────────────────────────────

async def _cmd_refund(text: str, user_id: str, group_id: str) -> None:
    from app.services.ecommerce_service import process_refund

    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await push_text(group_id, "格式：/退款 訂單編號 原因")
        return

    order_no = parts[1]
    reason = parts[2] if len(parts) > 2 else "（未填原因）"
    operator = await _fetch_user_name(user_id)

    try:
        ok = await process_refund(order_no, reason, operator)
        if ok:
            await push_text(group_id, f"🔄 訂單 {order_no} 已申請退款\n原因：{reason}")
        else:
            await push_text(group_id, f"找不到訂單 {order_no}")
    except Exception as e:
        log.error("_cmd_refund error: %s", e)
        await push_text(group_id, f"⚠️ 操作失敗：{e}")


# ─── /取消訂單 訂單編號 原因 ──────────────────────────────────────────

async def _cmd_cancel(text: str, user_id: str, group_id: str) -> None:
    from app.services.ecommerce_service import cancel_order

    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await push_text(group_id, "格式：/取消訂單 訂單編號 原因")
        return

    order_no = parts[1]
    reason = parts[2] if len(parts) > 2 else "（未填原因）"
    operator = await _fetch_user_name(user_id)

    try:
        ok = await cancel_order(order_no, reason, operator)
        if ok:
            await push_text(group_id, f"❌ 訂單 {order_no} 已取消\n原因：{reason}")
        else:
            await push_text(group_id, f"找不到訂單 {order_no}")
    except Exception as e:
        log.error("_cmd_cancel error: %s", e)
        await push_text(group_id, f"⚠️ 操作失敗：{e}")


# ─── /未付款 ─────────────────────────────────────────────────────────

async def _cmd_list_unpaid(group_id: str) -> None:
    from app.services.ecommerce_service import list_pending_payment, format_order_list

    try:
        orders = await list_pending_payment()
        total = sum(o.total_amount for o in orders)
        title = f"⏳ 待付款訂單（{len(orders)} 筆，合計 NT${total:,.0f}）"
        await push_text(group_id, format_order_list(orders, title))
    except Exception as e:
        log.error("_cmd_list_unpaid error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /未出貨 ─────────────────────────────────────────────────────────

async def _cmd_list_unshipped(group_id: str) -> None:
    from app.services.ecommerce_service import list_pending_shipment, format_order_list

    try:
        orders = await list_pending_shipment()
        title = f"📦 待出貨訂單（{len(orders)} 筆）"
        await push_text(group_id, format_order_list(orders, title))
    except Exception as e:
        log.error("_cmd_list_unshipped error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /電商日報 [YYYY-MM-DD] ───────────────────────────────────────────

async def _cmd_daily_summary(text: str, group_id: str) -> None:
    from app.services.ecommerce_service import daily_summary

    date_match = _DATE_RE.search(text)
    target = date_match.group() if date_match else None

    try:
        s = await daily_summary(target)
        label = s["date"]
        lines = [
            f"🛒 電商日報（{label}）",
            f"總訂單：{s['total_orders']} 筆",
            f"已付款收入：NT${s['paid_revenue']:,.0f}",
            f"待付款：{s['pending_payment']} 筆",
            f"待出貨：{s['pending_shipment']} 筆",
        ]
        if s["refunds"]:
            lines.append(f"退款中：{s['refunds']} 筆  ⚠️ 需處理")
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        log.error("_cmd_daily_summary error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── helper ──────────────────────────────────────────────────────────

async def _fetch_user_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id
