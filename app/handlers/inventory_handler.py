"""LINE command handlers for inventory / restocking system.

Commands
--------
  /叫貨 品項 數量 [店別] [備註]
      快速叫貨，通知中央工廠
  /到貨 品項 數量 [店別]
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
"""
from __future__ import annotations

import logging

from app.line.reply import push_text

log = logging.getLogger(__name__)


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


# ─── /叫貨 品項 數量 [店別] [備註] ───────────────────────────────────

async def _cmd_order(text: str, user_id: str, group_id: str) -> None:
    from app.services.inventory_service import quick_order

    # /叫貨 青蔥 5 福星店 急
    parts = text.split(maxsplit=4)
    if len(parts) < 3:
        await push_text(
            group_id,
            "格式：/叫貨 品項 數量 [店別] [備註]\n"
            "範例：/叫貨 青蔥 5斤 福星店"
        )
        return

    item_name = parts[1]
    qty, unit = _parse_qty(parts[2])
    store = parts[3] if len(parts) > 3 else ""
    notes = parts[4] if len(parts) > 4 else ""
    operator = await _fetch_name(user_id)

    try:
        movement, warnings = await quick_order(item_name, qty, store, operator, notes)
        lines = [
            f"✅ 叫貨已登記",
            f"品項：{item_name}　數量：{qty}{unit or movement.unit}",
        ]
        if store:
            lines.append(f"店別：{store}")
        lines.append(f"叫貨人：{operator}　時間：{movement.moved_at}")
        if warnings:
            lines.extend(warnings)
        await push_text(group_id, "\n".join(lines))
    except Exception as e:
        log.error("_cmd_order error: %s", e)
        await push_text(group_id, f"⚠️ 叫貨失敗：{e}")


# ─── /到貨 品項 數量 [單價] [廠商名] [店別] ──────────────────────────

async def _cmd_arrival(text: str, user_id: str, group_id: str) -> None:
    """Confirm arrival, update inventory, optionally create AP record.

    Formats accepted:
      /到貨 品項 數量 [店別]
      /到貨 品項 數量 單價 廠商名 [店別]
    If a numeric 3rd arg follows qty, it is treated as unit_price.
    If vendor name is given, an AP record is written to 應付帳款.
    """
    import re
    from datetime import date as _date
    from app.services.inventory_service import confirm_arrival, format_item

    parts = text.split(maxsplit=5)
    if len(parts) < 3:
        await push_text(
            group_id,
            "格式：/到貨 品項 數量 [單價 廠商名] [店別]\n"
            "不含單價：/到貨 青蔥 5斤 福星店\n"
            "含單價：  /到貨 青蔥 5斤 120 大成農城 福星店"
        )
        return

    item_name = parts[1]
    qty, unit = _parse_qty(parts[2])

    # Detect optional unit_price: parts[3] is purely numeric
    unit_price: float = 0.0
    vendor_name: str = ""
    store: str = ""

    remaining = parts[3:]  # everything after qty
    _NUM_RE = re.compile(r"^[\d.]+$")

    if remaining and _NUM_RE.match(remaining[0]):
        # Has unit price
        try:
            unit_price = float(remaining[0])
        except ValueError:
            pass
        remaining = remaining[1:]
        # Next token is vendor name (if present)
        if remaining:
            vendor_name = remaining[0]
            remaining = remaining[1:]
        if remaining:
            store = remaining[0]
    else:
        # No unit price — first remaining token is store
        if remaining:
            store = remaining[0]

    operator = await _fetch_name(user_id)

    try:
        item = await confirm_arrival(item_name, qty, store, operator)
        msg = f"✅ 到貨已確認，庫存已更新\n{format_item(item)}"

        # If unit price and vendor provided, write AP record
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
    """Parse '5斤' or '5' → (5.0, '斤') or (5.0, '')."""
    import re
    m = re.match(r"([\d.]+)(.*)", text.strip())
    if m:
        try:
            return float(m.group(1)), m.group(2).strip()
        except ValueError:
            pass
    return 1.0, ""


async def _fetch_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id
