"""LINE command handlers for inventory / restocking system.

Commands
--------
  /叫貨 品項 數量 [品項2 數量2 ...] [店別] [備註]
      快速叫貨（支援多品項），通知中央工廠
  /到貨 品項 數量 [單價 廠商名] [店別]
      確認到貨，更新庫存
  /消耗 品項 數量 [店別]
      記錄日常消耗，扣減庫存
  /盤點 品項 數量 [店別]
      手動設定庫存（絕對值）
  /安全庫存 品項 數量
      設定安全庫存警戒量
  /庫存 [品項名]
      查庫存狀況（全部 or 單品）
  /低庫存
      列出所有低於安全庫存的品項
  /採購預測
      基於30日消耗率推估補貨需求

自然語言格式（明倫蛋餅）
  叫貨：青蔥 5斤 雞蛋 2箱
  今日叫貨 青蔥5斤 蛋2箱
  /叫貨 青蔥 5斤 雞蛋 2箱
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import NamedTuple

from app.line.reply import push_text

log = logging.getLogger(__name__)

# ─── 明倫品項別名對照表 ───────────────────────────────────────────────
# key = 別名（lowercase），value = (正式名稱, 預設單位)
_MINGLUN_ITEMS: dict[str, tuple[str, str]] = {
    # 青蔥
    "青蔥": ("青蔥", "斤"),
    "蔥":   ("青蔥", "斤"),
    # 雞蛋
    "雞蛋": ("雞蛋", "箱"),
    "蛋":   ("雞蛋", "箱"),
    # 醬料
    "醬料": ("醬料", "桶"),
    "醬":   ("醬料", "桶"),
    # 包材
    "包材": ("包材", "包"),
    "袋子": ("包材", "包"),
    "包裝": ("包材", "包"),
    # 蛋餅皮
    "蛋餅皮": ("蛋餅皮", "箱"),
    "餅皮":   ("蛋餅皮", "箱"),
    "皮":     ("蛋餅皮", "箱"),
    # 培根
    "培根": ("培根", "包"),
    "bacon": ("培根", "包"),
    # 起司
    "起司": ("起司", "包"),
    "起士": ("起司", "包"),
    "cheese": ("起司", "包"),
}

_KNOWN_UNITS = {"斤", "箱", "桶", "包", "袋", "個", "條", "瓶", "片", "公斤", "kg"}


class OrderItem(NamedTuple):
    name: str
    qty: float
    unit: str


# ─── public entry point ──────────────────────────────────────────────

async def handle_inventory_command(
    text: str,
    user_id: str,
    group_id: str,
) -> None:
    s = text.strip()

    if s.startswith("/叫貨"):
        await _cmd_order(s, user_id, group_id)
    elif s.startswith("/到貨"):
        await _cmd_arrival(s, user_id, group_id)
    elif s.startswith("/消耗"):
        await _cmd_consume(s, user_id, group_id)
    elif s.startswith("/盤點"):
        await _cmd_stockcount(s, user_id, group_id)
    elif s.startswith("/安全庫存"):
        await _cmd_set_safety(s, group_id)
    elif s.startswith("/低庫存"):
        await _cmd_low_stock(group_id)
    elif s.startswith("/採購預測"):
        await _cmd_forecast(group_id)
    elif s.startswith("/庫存"):
        await _cmd_query(s, group_id)
    else:
        # Natural-language 叫貨: "叫貨：...", "今日叫貨 ..."
        await _cmd_order_nl(s, user_id, group_id)


# ─── /叫貨 — supports multiple items ─────────────────────────────────

async def _cmd_order(text: str, user_id: str, group_id: str) -> None:
    """Handle /叫貨 with support for multiple items.

    Accepted formats:
      /叫貨 青蔥 5斤 福星店
      /叫貨 青蔥 5斤 雞蛋 2箱 福星店
      /叫貨 青蔥 5 雞蛋 2 福星店 急用
    """
    # Strip the command token
    body = text[len("/叫貨"):].strip()
    await _process_order(body, user_id, group_id)


async def _cmd_order_nl(text: str, user_id: str, group_id: str) -> None:
    """Handle natural-language 叫貨 messages routed from router.py.

    Accepted formats:
      叫貨：青蔥 5斤 雞蛋 2箱
      叫貨:青蔥 5 雞蛋 2
      今日叫貨 青蔥5斤 蛋2箱
    """
    # Strip leading trigger words
    body = re.sub(r"^(今日叫貨|叫貨[：:﹕]?\s*)", "", text).strip()
    await _process_order(body, user_id, group_id)


async def _process_order(body: str, user_id: str, group_id: str) -> None:
    """Parse items from body and write purchase order(s) to Sheets.

    Body is everything after the command/trigger prefix, e.g.:
      "青蔥 5斤 雞蛋 2箱 福星店"
      "青蔥5斤、蛋2箱"
    """
    from app.services.inventory_service import quick_order

    if not body:
        await push_text(
            group_id,
            "格式：/叫貨 品項 數量 [品項2 數量2 ...] [店別]\n"
            "範例：/叫貨 青蔥 5斤 雞蛋 2箱 福星店\n"
            "自然語言：叫貨：青蔥5斤、蛋2箱",
        )
        return

    items, store, notes = _parse_order_body(body)
    if not items:
        await push_text(
            group_id,
            "⚠️ 無法辨識品項，請確認格式：\n"
            "/叫貨 青蔥 5斤 雞蛋 2箱\n"
            "叫貨：青蔥 5斤、蛋 2箱",
        )
        return

    operator = await _fetch_name(user_id)
    now_str = _now_taipei()

    succeeded: list[str] = []
    warnings: list[str] = []
    failed: list[str] = []

    for item in items:
        try:
            movement, item_warnings = await quick_order(
                item.name, item.qty, store, operator, notes
            )
            succeeded.append(
                f"• {item.name} {item.qty}{item.unit or movement.unit}"
            )
            warnings.extend(item_warnings)
        except Exception as e:
            log.error("_process_order quick_order error [%s]: %s", item.name, e)
            failed.append(f"• {item.name}：{e}")

    # Reply to origin group
    if succeeded:
        lines = ["✅ 叫貨已登記"]
        if store:
            lines.append(f"店別：{store}")
        lines.append("品項：")
        lines.extend(succeeded)
        lines.append(f"叫貨人：{operator}　時間：{now_str}")
        if warnings:
            lines.extend(warnings)
        await push_text(group_id, "\n".join(lines))

    if failed:
        await push_text(group_id, "⚠️ 以下品項叫貨失敗：\n" + "\n".join(failed))

    # Forward to factory group if configured
    if succeeded:
        await _forward_to_factory(items, store, operator, now_str, group_id)


async def _forward_to_factory(
    items: list[OrderItem],
    store: str,
    creator_name: str,
    now: str,
    origin_group_id: str,
) -> None:
    """Push order notification to central factory LINE group if configured."""
    from app.config import settings

    factory_group = settings.factory_line_group_id
    if not factory_group:
        return
    if factory_group == origin_group_id:
        # Avoid duplicate message when order is placed from the factory group itself
        return

    store_label = store if store else "（未指定）"
    item_lines = "\n".join(
        f"• {it.name} {it.qty}{it.unit}" for it in items
    )
    msg = (
        f"📦 新叫貨單\n"
        f"店別：{store_label}\n"
        f"品項：\n{item_lines}\n"
        f"建立者：{creator_name}\n"
        f"時間：{now}"
    )
    try:
        await push_text(factory_group, msg)
    except Exception as e:
        log.error("_forward_to_factory push failed: %s", e)


# ─── /到貨 品項 數量 [單價] [廠商名] [店別] ──────────────────────────

async def _cmd_arrival(text: str, user_id: str, group_id: str) -> None:
    """Confirm arrival, update inventory, optionally create AP record.

    Formats accepted:
      /到貨 品項 數量 [店別]
      /到貨 品項 數量 單價 廠商名 [店別]
    If a numeric 3rd arg follows qty, it is treated as unit_price.
    If vendor name is given, an AP record is written to 應付帳款.
    """
    from datetime import date as _date
    from app.services.inventory_service import confirm_arrival, format_item

    parts = text.split(maxsplit=5)
    if len(parts) < 3:
        await push_text(
            group_id,
            "格式：/到貨 品項 數量 [單價 廠商名] [店別]\n"
            "不含單價：/到貨 青蔥 5斤 福星店\n"
            "含單價：  /到貨 青蔥 5斤 120 大成農城 福星店",
        )
        return

    item_name = parts[1]
    qty, unit = _parse_qty(parts[2])

    # Detect optional unit_price: parts[3] is purely numeric
    unit_price: float = 0.0
    vendor_name: str = ""
    store: str = ""

    remaining = parts[3:]
    _NUM_RE = re.compile(r"^[\d.]+$")

    if remaining and _NUM_RE.match(remaining[0]):
        try:
            unit_price = float(remaining[0])
        except ValueError:
            pass
        remaining = remaining[1:]
        if remaining:
            vendor_name = remaining[0]
            remaining = remaining[1:]
        if remaining:
            store = remaining[0]
    else:
        if remaining:
            store = remaining[0]

    operator = await _fetch_name(user_id)

    try:
        item = await confirm_arrival(item_name, qty, store, operator)
        msg = f"✅ 到貨已確認，庫存已更新\n{format_item(item)}"

        if unit_price > 0 and vendor_name:
            from app.models.vendor import APRecord
            from app.services.sheets_service import get_vendor, append_ap_record

            vendor = await get_vendor(vendor_name)
            ap = APRecord(
                delivery_date=_date.today().isoformat(),
                vendor_name=vendor_name,
                item_name=item_name,
                qty=qty,
                unit=unit or (item.unit if hasattr(item, "unit") else ""),
                unit_price=unit_price,
                invoice_type=vendor.invoice_type if vendor else "",
                billing_cycle=vendor.billing_cycle if vendor else "",
            )
            ap_row = await append_ap_record(ap)
            msg += (
                f"\n─────────────\n"
                f"📋 應付帳款已記錄（第 {ap_row} 列）\n"
                f"廠商：{vendor_name}　金額：NT${ap.amount:,.0f}"
            )
            if vendor and not vendor.line_group_id:
                msg += f"\nℹ️ {vendor_name} 尚未設定 LINE 群組"

        await push_text(group_id, msg)
    except Exception as e:
        log.error("_cmd_arrival error: %s", e)
        await push_text(group_id, f"⚠️ 到貨登記失敗：{e}")


# ─── /消耗 品項 數量 [店別] ──────────────────────────────────────────

async def _cmd_consume(text: str, user_id: str, group_id: str) -> None:
    from app.services.inventory_service import record_consumption, format_item

    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        await push_text(group_id, "格式：/消耗 品項 數量 [店別]\n範例：/消耗 醬油 2瓶 信義店")
        return

    item_name = parts[1]
    qty, _ = _parse_qty(parts[2])
    store = parts[3] if len(parts) > 3 else ""
    operator = await _fetch_name(user_id)

    try:
        item = await record_consumption(item_name, qty, store, operator)
        await push_text(group_id, f"✅ 消耗已記錄\n{format_item(item)}")
    except Exception as e:
        log.error("_cmd_consume error: %s", e)
        await push_text(group_id, f"⚠️ 消耗記錄失敗：{e}")


# ─── /盤點 品項 數量 [店別] ──────────────────────────────────────────

async def _cmd_stockcount(text: str, user_id: str, group_id: str) -> None:
    from app.services.inventory_service import set_stock_count, format_item

    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        await push_text(group_id, "格式：/盤點 品項 數量 [店別]\n範例：/盤點 青蔥 8斤 中央工廠")
        return

    item_name = parts[1]
    qty, _ = _parse_qty(parts[2])
    store = parts[3] if len(parts) > 3 else ""
    operator = await _fetch_name(user_id)

    try:
        item = await set_stock_count(item_name, qty, store, operator)
        await push_text(group_id, f"✅ 盤點完成，庫存已更新\n{format_item(item)}")
    except Exception as e:
        log.error("_cmd_stockcount error: %s", e)
        await push_text(group_id, f"⚠️ 盤點失敗：{e}")


# ─── /安全庫存 品項 數量 ─────────────────────────────────────────────

async def _cmd_set_safety(text: str, group_id: str) -> None:
    from app.services.inventory_service import set_safety_stock, format_item

    parts = text.split()
    if len(parts) < 3:
        await push_text(group_id, "格式：/安全庫存 品項 數量\n範例：/安全庫存 青蔥 3")
        return

    item_name = parts[1]
    qty, _ = _parse_qty(parts[2])

    try:
        item = await set_safety_stock(item_name, qty)
        await push_text(group_id, f"✅ 安全庫存已設定\n{format_item(item)}")
    except Exception as e:
        log.error("_cmd_set_safety error: %s", e)
        await push_text(group_id, f"⚠️ 設定失敗：{e}")


# ─── /庫存 [品項名] ──────────────────────────────────────────────────

async def _cmd_query(text: str, group_id: str) -> None:
    from app.services.inventory_service import format_item, format_inventory_list
    from app.services.sheets_service import get_all_inventory_items, get_inventory_item

    parts = text.split(maxsplit=1)
    item_name = parts[1].strip() if len(parts) > 1 else ""

    try:
        if item_name:
            item = await get_inventory_item(item_name)
            if item:
                await push_text(group_id, format_item(item))
            else:
                await push_text(group_id, f"找不到品項「{item_name}」，請先盤點或叫貨建立記錄")
        else:
            items = await get_all_inventory_items()
            if not items:
                await push_text(group_id, "庫存台帳目前無資料，請先使用 /盤點 建立品項")
                return
            low = [it for it in items if it.is_low]
            normal = [it for it in items if not it.is_low]
            lines = [f"📦 庫存狀況（共 {len(items)} 項）"]
            if low:
                lines.append(f"⚠️ 低庫存 {len(low)} 項：")
                for it in low:
                    lines.append(f"  {it.name}：{it.current_stock:.1f}/{it.safety_stock:.1f} {it.unit}")
            lines.append(f"✅ 正常 {len(normal)} 項")
            for it in normal[:8]:
                lines.append(f"  {it.name}：{it.current_stock:.1f} {it.unit}")
            if len(normal) > 8:
                lines.append(f"  …（另 {len(normal)-8} 項正常）")
            await push_text(group_id, "\n".join(lines))
    except Exception as e:
        log.error("_cmd_query error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /低庫存 ─────────────────────────────────────────────────────────

async def _cmd_low_stock(group_id: str) -> None:
    from app.services.inventory_service import get_low_stock_items, format_inventory_list

    try:
        items = await get_low_stock_items()
        title = f"⚠️ 低庫存品項（{len(items)} 項）"
        await push_text(group_id, format_inventory_list(items, title))
    except Exception as e:
        log.error("_cmd_low_stock error: %s", e)
        await push_text(group_id, f"⚠️ 查詢失敗：{e}")


# ─── /採購預測 ───────────────────────────────────────────────────────

async def _cmd_forecast(group_id: str) -> None:
    from app.services.inventory_service import get_procurement_forecast, format_forecast

    try:
        forecasts = await get_procurement_forecast()
        await push_text(group_id, format_forecast(forecasts))
    except Exception as e:
        log.error("_cmd_forecast error: %s", e)
        await push_text(group_id, f"⚠️ 採購預測失敗：{e}")


# ─── helpers ─────────────────────────────────────────────────────────

def _parse_qty(text: str) -> tuple[float, str]:
    """Parse '5斤' or '5' → (5.0, '斤') or (5.0, '').

    Handles glued unit like '5斤', '2箱', '1.5桶'.
    """
    m = re.match(r"([\d.]+)(.*)", text.strip())
    if m:
        try:
            return float(m.group(1)), m.group(2).strip()
        except ValueError:
            pass
    return 1.0, ""


def _normalize_item_name(raw: str) -> tuple[str, str]:
    """Resolve alias → (canonical_name, default_unit).

    Falls back to (raw, '') if unknown.
    """
    hit = _MINGLUN_ITEMS.get(raw) or _MINGLUN_ITEMS.get(raw.lower())
    if hit:
        return hit
    return raw, ""


def _parse_order_body(body: str) -> tuple[list[OrderItem], str, str]:
    """Parse the body of a 叫貨 command into items, store name, and notes.

    Strategy:
    1. Split on whitespace / 頓號 「、」
    2. Walk tokens left-to-right:
       - If token is a known item name (or alias) → start new item
       - If current item exists and token looks like a qty → assign qty+unit
       - Otherwise → leftover (store/notes candidate)

    Returns:
      items : list of OrderItem
      store : store name string (may be "")
      notes : extra notes string (may be "")
    """
    # Normalise separators: replace 、with space
    body = body.replace("、", " ").replace("，", " ").replace(",", " ")

    # Split glued "蛋2箱" → ["蛋", "2箱"] by inserting space before digit after CJK
    body = re.sub(r"([^\d\s])(\d)", r"\1 \2", body)

    tokens = body.split()

    items: list[OrderItem] = []
    leftovers: list[str] = []

    # State machine
    current_name: str | None = None
    current_unit_default: str = ""

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # Check if this token is a known item name (or alias)
        canonical, default_unit = _normalize_item_name(tok)
        if canonical != tok or tok in _MINGLUN_ITEMS:
            # Flush previous item (qty unknown yet → qty=1)
            if current_name is not None:
                items.append(OrderItem(current_name, 1.0, current_unit_default))
            current_name = canonical
            current_unit_default = default_unit
            i += 1
            continue

        # Check if looks like a qty token (starts with digit, possibly ends with unit)
        qty_match = re.match(r"^([\d.]+)(.*)$", tok)
        if qty_match:
            qty_val = float(qty_match.group(1))
            qty_unit = qty_match.group(2).strip()
            if not qty_unit and current_unit_default:
                qty_unit = current_unit_default
            # If unit was inferred from default, the next token might be the literal
            # unit word (e.g. "青蔥 5 斤" → tok="5", next="斤"). Skip it to avoid
            # it being misinterpreted as a store name.
            skip_next = (
                not qty_match.group(2).strip()      # no unit glued to the number
                and i + 1 < len(tokens)
                and tokens[i + 1] in _KNOWN_UNITS
            )
            if current_name is not None:
                items.append(OrderItem(current_name, qty_val, qty_unit))
                current_name = None
                current_unit_default = ""
            else:
                leftovers.append(tok)
            i += 2 if skip_next else 1
            continue

        # Token is neither a known item nor a qty → treat as store/notes leftover
        if current_name is not None:
            # Might be next item or store; if we haven't assigned qty, flush with qty=1
            items.append(OrderItem(current_name, 1.0, current_unit_default))
            current_name = None
            current_unit_default = ""
        leftovers.append(tok)
        i += 1

    # Flush last pending item
    if current_name is not None:
        items.append(OrderItem(current_name, 1.0, current_unit_default))

    # Interpret leftovers: first unknown token = store, rest = notes
    store = leftovers[0] if leftovers else ""
    notes = " ".join(leftovers[1:]) if len(leftovers) > 1 else ""

    return items, store, notes


def _now_taipei() -> str:
    """Return current datetime string in Asia/Taipei timezone."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        tz = ZoneInfo("Asia/Taipei")
    except ImportError:
        import pytz  # type: ignore[import]
        tz = pytz.timezone("Asia/Taipei")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")


async def _fetch_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id
