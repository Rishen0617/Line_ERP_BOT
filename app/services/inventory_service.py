"""Inventory management service.

Flow:
  /叫貨 → StockMovement(type=叫貨, qty=-n) → notify central kitchen
  /到貨 → StockMovement(type=到貨, qty=+n) → update Sheet8 current_stock
  /消耗 → StockMovement(type=消耗, qty=-n) → update Sheet8 current_stock
  /盤點 → set absolute current_stock in Sheet8

Consumption analytics:
  avg_daily = sum(|qty| for 消耗 movements in last 30 days) / 30
  days_until_stockout = current_stock / avg_daily  (if avg > 0)
  reorder_point = safety_stock + avg_daily * LEAD_DAYS
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.inventory import InventoryItem, MovementType, StockMovement

log = logging.getLogger(__name__)
_TZ = ZoneInfo(settings.bot_timezone)

LEAD_DAYS = 2          # 到貨前置天數（預設 2 天）
ANALYSIS_DAYS = 30     # 消耗率計算天數


def _now() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")


# ─── Core operations ─────────────────────────────────────────────────

async def quick_order(
    item_name: str,
    quantity: float,
    store: str,
    operator: str,
    notes: str = "",
) -> tuple[StockMovement, list[str]]:
    """Create a 叫貨 movement, notify central kitchen, alert if needed."""
    from app.services.sheets_service import (
        append_stock_movement, get_inventory_item,
    )

    movement = StockMovement(
        moved_at=_now(),
        item_name=item_name,
        movement_type="叫貨",
        quantity=quantity,
        store=store,
        operator=operator,
        notes=notes,
    )
    await append_stock_movement(movement)

    warnings: list[str] = []
    try:
        item = await get_inventory_item(item_name)
        if item and item.is_low:
            warnings.append(f"⚠️ {item_name} 目前庫存 {item.current_stock}{item.unit}，已低於安全庫存")
    except Exception:
        pass

    # Notify central kitchen if configured
    await _notify_kitchen(item_name, quantity, store, operator)

    return movement, warnings


async def confirm_arrival(
    item_name: str,
    quantity: float,
    store: str,
    operator: str,
    ref_order_no: str = "",
) -> InventoryItem:
    """Record arrival and update current stock (+quantity)."""
    from app.services.sheets_service import (
        append_stock_movement, update_inventory_stock,
    )

    movement = StockMovement(
        moved_at=_now(),
        item_name=item_name,
        movement_type="到貨",
        quantity=quantity,
        store=store,
        operator=operator,
        ref_order_no=ref_order_no,
    )
    await append_stock_movement(movement)
    item = await update_inventory_stock(item_name, delta=quantity)
    return item


async def record_consumption(
    item_name: str,
    quantity: float,
    store: str,
    operator: str,
) -> InventoryItem:
    """Record consumption (-quantity) and update current stock."""
    from app.services.sheets_service import (
        append_stock_movement, update_inventory_stock,
    )

    movement = StockMovement(
        moved_at=_now(),
        item_name=item_name,
        movement_type="消耗",
        quantity=-abs(quantity),
        store=store,
        operator=operator,
    )
    await append_stock_movement(movement)
    item = await update_inventory_stock(item_name, delta=-abs(quantity))

    if item.is_low:
        await _alert_low_stock(item)

    return item


async def set_stock_count(
    item_name: str,
    quantity: float,
    store: str,
    operator: str,
) -> InventoryItem:
    """盤點：set absolute stock value."""
    from app.services.sheets_service import (
        append_stock_movement, update_inventory_stock, get_inventory_item,
    )

    old = await get_inventory_item(item_name)
    old_qty = old.current_stock if old else 0.0
    delta = quantity - old_qty

    movement = StockMovement(
        moved_at=_now(),
        item_name=item_name,
        movement_type="盤點",
        quantity=delta,
        store=store,
        operator=operator,
        notes=f"盤點調整：{old_qty} → {quantity}",
    )
    await append_stock_movement(movement)
    return await update_inventory_stock(item_name, absolute=quantity)


async def set_safety_stock(item_name: str, level: float) -> InventoryItem:
    """Update safety stock level for an item."""
    from app.services.sheets_service import update_inventory_safety_stock
    return await update_inventory_safety_stock(item_name, level)


# ─── Queries ─────────────────────────────────────────────────────────

async def get_low_stock_items() -> list[InventoryItem]:
    from app.services.sheets_service import get_all_inventory_items
    items = await get_all_inventory_items()
    return [it for it in items if it.is_low]


async def get_procurement_forecast() -> list[dict[str, Any]]:
    """Analyse consumption and predict reorder needs."""
    from app.services.sheets_service import (
        get_all_inventory_items, get_stock_movements_since,
    )

    since = (datetime.now(_TZ) - timedelta(days=ANALYSIS_DAYS)).strftime("%Y-%m-%d")
    movements = await get_stock_movements_since(since)
    items = await get_all_inventory_items()

    # Build consumption map: item → total consumed in ANALYSIS_DAYS
    consumed: dict[str, float] = {}
    for m in movements:
        if m.movement_type == "消耗":
            consumed[m.item_name] = consumed.get(m.item_name, 0) + abs(m.quantity)

    forecasts = []
    for item in items:
        total_consumed = consumed.get(item.name, 0.0)
        avg_daily = total_consumed / ANALYSIS_DAYS if total_consumed > 0 else 0.0

        if avg_daily > 0:
            days_left = item.current_stock / avg_daily
        else:
            days_left = None

        reorder_point = item.safety_stock + avg_daily * LEAD_DAYS
        need_reorder = item.current_stock <= reorder_point

        forecasts.append({
            "name": item.name,
            "unit": item.unit,
            "current_stock": item.current_stock,
            "safety_stock": item.safety_stock,
            "avg_daily": round(avg_daily, 2),
            "days_left": round(days_left, 1) if days_left is not None else None,
            "reorder_point": round(reorder_point, 1),
            "need_reorder": need_reorder,
            "suggested_qty": round(avg_daily * (LEAD_DAYS + 3), 1) if avg_daily > 0 else 0,
        })

    # Sort: urgent first (need_reorder=True), then by days_left asc
    forecasts.sort(key=lambda x: (not x["need_reorder"], x["days_left"] or 9999))
    return forecasts


# ─── Formatting ──────────────────────────────────────────────────────

def format_item(item: InventoryItem) -> str:
    status = "⚠️ 低庫存" if item.is_low else "✅ 正常"
    lines = [
        f"📦 {item.name}（{item.spec or item.unit}）{status}",
        f"目前庫存：{item.current_stock:.1f} {item.unit}",
        f"安全庫存：{item.safety_stock:.1f} {item.unit}",
    ]
    if item.category:
        lines.append(f"分類：{item.category}　供應商：{item.supplier or '未設定'}")
    return "\n".join(lines)


def format_inventory_list(items: list[InventoryItem], title: str = "") -> str:
    if not items:
        return f"{title}\n（無資料）" if title else "（無資料）"
    lines = [title] if title else []
    for it in items:
        icon = "⚠️" if it.is_low else "✅"
        lines.append(
            f"{icon} {it.name}：{it.current_stock:.1f}/{it.safety_stock:.1f} {it.unit}"
        )
    return "\n".join(lines)


def format_forecast(forecasts: list[dict]) -> str:
    if not forecasts:
        return "目前無消耗記錄可供分析。"
    lines = ["📊 採購預測（近30日消耗分析）", "─────────────────"]
    urgent = [f for f in forecasts if f["need_reorder"]]
    ok = [f for f in forecasts if not f["need_reorder"]]

    if urgent:
        lines.append("🔴 需補貨：")
        for f in urgent:
            d = f"剩 {f['days_left']}天" if f["days_left"] is not None else "無消耗記錄"
            lines.append(
                f"  {f['name']}  現貨{f['current_stock']}{f['unit']}  "
                f"日均耗{f['avg_daily']}{f['unit']}  {d}"
                f"\n    建議叫貨：{f['suggested_qty']}{f['unit']}"
            )
    if ok:
        lines.append("🟢 庫存充足：")
        for f in ok[:5]:
            d = f"剩 {f['days_left']}天" if f["days_left"] is not None else "-"
            lines.append(f"  {f['name']}  {f['current_stock']}{f['unit']}  {d}")
        if len(ok) > 5:
            lines.append(f"  …（另 {len(ok)-5} 項充足，省略）")
    return "\n".join(lines)


# ─── Internal helpers ─────────────────────────────────────────────────

async def _notify_kitchen(
    item_name: str, qty: float, store: str, operator: str
) -> None:
    """Push order notification to central kitchen group if configured."""
    from app.config import settings as cfg
    kitchen_id = getattr(cfg, "kitchen_group_id", "")
    if not kitchen_id:
        return
    from app.line.reply import push_text
    try:
        await push_text(
            kitchen_id,
            f"🔔 叫貨通知\n"
            f"品項：{item_name}\n"
            f"數量：{qty}\n"
            f"店別：{store}\n"
            f"叫貨人：{operator}\n"
            f"時間：{_now()}"
        )
    except Exception as e:
        log.warning("kitchen notify failed: %s", e)


async def _alert_low_stock(item: InventoryItem) -> None:
    from app.config import settings as cfg
    if not cfg.admin_line_user_id:
        return
    from app.line.reply import push_text
    try:
        await push_text(
            cfg.admin_line_user_id,
            f"⚠️ 低庫存警示\n"
            f"品項：{item.name}\n"
            f"目前庫存：{item.current_stock:.1f} {item.unit}\n"
            f"安全庫存：{item.safety_stock:.1f} {item.unit}\n"
            f"請盡快補貨！"
        )
    except Exception as e:
        log.warning("low stock alert failed: %s", e)
