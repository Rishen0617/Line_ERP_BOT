"""Text message processing — accounting, orders, and intent fallback."""
from __future__ import annotations

import logging
import re
from datetime import date

from app.config import settings
from app.line.reply import push_text
from app.line.router import extract_tracking_numbers, route_text

log = logging.getLogger(__name__)

# Regex for quick amount extraction: e.g. "3200" "12,500" "NT$800"
_AMOUNT_RE = re.compile(r"(?:NT\$|NTD|台幣)?\s*([\d,]+(?:\.\d{1,2})?)")
# Counter-party: text before/after amount, simple heuristic
_PARTY_RE = re.compile(r"([^\d\s,]{2,12}(?:公司|行|店|廠|企業|食品)?)")


async def _fetch_user_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id


async def process_text(
    text: str,
    reply_token: str,
    user_id: str,
    group_id: str,
) -> None:
    intent = route_text(text)
    log.info("text intent=%s user=%s", intent, user_id)

    if intent == "help":
        from app.handlers.command_handler import handle_help
        await handle_help(group_id)

    elif intent == "command":
        from app.handlers.command_handler import handle_command
        await handle_command(text, reply_token, user_id, group_id)

    elif intent == "admin":
        await _handle_admin(text, user_id, group_id)

    elif intent == "ecommerce":
        from app.handlers.ecommerce_handler import handle_ecommerce_command
        await handle_ecommerce_command(text, user_id, group_id)

    elif intent == "inventory":
        from app.handlers.inventory_handler import handle_inventory_command
        await handle_inventory_command(text, user_id, group_id)

    elif intent == "schedule":
        from app.handlers.schedule_handler import handle_schedule_command
        await handle_schedule_command(text, user_id, group_id)

    elif intent == "logistics":
        tracking_numbers = extract_tracking_numbers(text)
        from app.services.logistics_service import query_tracking
        for tn in tracking_numbers:
            result = await query_tracking(tn)
            await push_text(group_id, result)

    elif intent == "accounting":
        await _handle_accounting(text, user_id, group_id)

    elif intent == "order":
        await _handle_order(text, user_id, group_id)

    else:
        # AI fallback
        from app.services.claude_service import parse_intent
        parsed = await parse_intent(text)
        ai_intent = parsed.get("intent", "unknown")

        if ai_intent == "accounting":
            await _handle_accounting(text, user_id, group_id, ai_data=parsed)
        elif ai_intent == "order":
            await _handle_order(text, user_id, group_id, ai_data=parsed)
        else:
            await push_text(
                group_id,
                "我不太了解這個訊息 😅\n"
                "可以試試：\n"
                "• 傳送收據/發票照片\n"
                "• 輸入「支出 3200 王老吉食品 進貨礦泉水」\n"
                "• 輸入「/月報」查看當月收支",
            )


async def _handle_accounting(
    text: str, user_id: str, group_id: str, ai_data: dict | None = None
) -> None:
    from app.models.transaction import Transaction
    from app.services.sheets_service import append_transaction
    from app.utils.amount_validator import check_and_alert

    # Try to parse from ai_data first, fall back to regex
    if ai_data and ai_data.get("amount"):
        try:
            amount = float(ai_data["amount"])
            category = ai_data.get("category", "支出")
            description = ai_data.get("description", text[:80])
            counter_party = ai_data.get("counter_party")
        except (TypeError, ValueError):
            amount, category, description, counter_party = _quick_parse(text)
    else:
        amount, category, description, counter_party = _quick_parse(text)

    if not amount:
        await push_text(group_id, "⚠️ 無法解析金額，請包含數字，例如：支出 3200 王老吉 進貨礦泉水")
        return

    recorder_name = await _fetch_user_name(user_id)
    tx = Transaction(
        tx_date=date.today(),
        category=category,
        description=description,
        amount=amount,
        counter_party=counter_party,
        recorded_by=user_id,
        group_id=group_id,
    )

    await check_and_alert(amount, category, None, group_id)

    try:
        row = await append_transaction(tx, recorder_name)
        await push_text(
            group_id,
            f"✅ 已記帳\n"
            f"{category} NT${amount:,.0f}\n"
            f"{'對象：' + counter_party + chr(10) if counter_party else ''}"
            f"說明：{description}\n"
            f"已存入：流水帳 第 {row} 列",
        )
    except Exception as e:
        log.error("append_transaction failed: %s", e)
        await push_text(group_id, f"⚠️ 寫入失敗：{e}")


async def _handle_order(
    text: str, user_id: str, group_id: str, ai_data: dict | None = None
) -> None:
    from app.models.order import Order, OrderItem
    from app.services.sheets_service import append_order

    # Simple extraction from ai_data or text
    if ai_data and ai_data.get("supplier"):
        supplier = ai_data.get("supplier", "未知廠商")
        items_raw = ai_data.get("items", [])
        items = [
            OrderItem(
                product_name=it.get("name", "品項"),
                qty=float(it.get("qty", 1)),
                unit=it.get("unit", "個"),
            )
            for it in items_raw
        ] if items_raw else [OrderItem(product_name=text[:40], qty=1, unit="批")]
    else:
        supplier = _extract_supplier(text)
        items = [OrderItem(product_name=text[:60], qty=1, unit="批")]

    creator_name = await _fetch_user_name(user_id)
    order = Order(
        order_date=date.today(),
        supplier=supplier,
        items=items,
        created_by=user_id,
        group_id=group_id,
    )

    try:
        row = await append_order(order, creator_name)
        await push_text(
            group_id,
            f"✅ 訂單已建立（待確認）\n"
            f"供應商：{supplier}\n"
            f"品項：{items[0].product_name}{'等' if len(items)>1 else ''}\n"
            f"已存入：訂單追蹤 第 {row} 列",
        )
    except Exception as e:
        log.error("append_order failed: %s", e)
        await push_text(group_id, f"⚠️ 訂單寫入失敗：{e}")


def _quick_parse(text: str) -> tuple[float | None, str, str, str | None]:
    """Heuristic: extract (amount, category, description, counter_party) from text."""
    category = "支出"
    if any(k in text for k in ("收入", "收款", "應收")):
        category = "收入"
    elif "應付" in text:
        category = "應付"
    elif "應收" in text:
        category = "應收"

    amounts = _AMOUNT_RE.findall(text)
    amount = None
    if amounts:
        try:
            amount = float(amounts[0].replace(",", ""))
        except ValueError:
            pass

    parties = _PARTY_RE.findall(text)
    counter_party = parties[0] if parties else None

    return amount, category, text[:80], counter_party


def _extract_supplier(text: str) -> str:
    parties = _PARTY_RE.findall(text)
    return parties[0] if parties else "未知廠商"


async def _handle_admin(text: str, user_id: str, group_id: str) -> None:
    """Handle admin commands (/晨報)."""
    stripped = text.strip()

    if stripped.startswith("/晨報"):
        # Only allow admin user to trigger manually
        if settings.admin_line_user_id and user_id != settings.admin_line_user_id:
            await push_text(group_id, "⚠️ 僅限管理員使用此指令")
            return
        from app.services.morning_report_service import build_report
        from app.utils.date_parser import parse_date
        import re
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", stripped)
        ref = None
        if date_match:
            ref = parse_date(date_match.group())
        try:
            report = await build_report(ref)
            await push_text(group_id, report)
        except Exception as e:
            log.error("_handle_admin /晨報 failed: %s", e)
            await push_text(group_id, f"⚠️ 晨報產生失敗：{e}")
