"""E-commerce administration service.

Lifecycle: 未付款 → 已付款 → 待出貨 → 出貨中 → 已送達
           任何階段可 → 退款中 → 已退款
           任何階段可 → 取消
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.ecommerce import EcommerceOrder, PaymentStatus, Platform, ShipStatus

log = logging.getLogger(__name__)
_TZ = ZoneInfo(settings.bot_timezone)

_ORDER_NO_RE = re.compile(r"[A-Za-z0-9\-]{4,30}")


def _now() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")


def generate_order_number(platform: str) -> str:
    prefix = {
        "LINE購物": "LN", "蝦皮": "SP", "91App": "91",
        "官網": "WB", "電話": "PH", "其他": "OT",
    }.get(platform, "OT")
    ts = datetime.now(_TZ).strftime("%m%d%H%M")
    uid = uuid.uuid4().hex[:4].upper()
    return f"{prefix}{ts}{uid}"


# ─── CRUD ────────────────────────────────────────────────────────────

async def create_order(
    platform: str,
    customer_name: str,
    items_summary: str,
    total_amount: float,
    payment_method: str = "其他",
    shipping_fee: float = 0.0,
    customer_phone: str = "",
    shipping_address: str = "",
    notes: str = "",
    created_by: str = "",
    order_number: str = "",
) -> EcommerceOrder:
    from app.services.sheets_service import append_ecommerce_order

    order = EcommerceOrder(
        created_at=_now(),
        order_number=order_number or generate_order_number(platform),
        platform=platform,  # type: ignore[arg-type]
        customer_name=customer_name,
        customer_phone=customer_phone,
        shipping_address=shipping_address,
        items_summary=items_summary,
        subtotal=total_amount - shipping_fee,
        shipping_fee=shipping_fee,
        total_amount=total_amount,
        payment_method=payment_method,  # type: ignore[arg-type]
        created_by=created_by,
        notes=notes,
    )
    await append_ecommerce_order(order)
    return order


async def confirm_payment(order_number: str, operator: str) -> bool:
    """Mark order as 已付款. Returns True if found and updated."""
    from app.services.sheets_service import update_ecommerce_order_fields
    return await update_ecommerce_order_fields(
        order_number,
        {"payment_status": "已付款", "notes_append": f"[{_now()} {operator} 確認付款]"},
    )


async def ship_order(
    order_number: str,
    logistics_company: str,
    tracking_number: str,
    operator: str,
) -> bool:
    """Record shipment info and mark as 出貨中."""
    from app.services.sheets_service import update_ecommerce_order_fields
    return await update_ecommerce_order_fields(
        order_number,
        {
            "logistics_company": logistics_company,
            "tracking_number": tracking_number,
            "ship_status": "出貨中",
            "notes_append": f"[{_now()} {operator} 出貨 {logistics_company} {tracking_number}]",
        },
    )


async def process_refund(order_number: str, reason: str, operator: str) -> bool:
    from app.services.sheets_service import update_ecommerce_order_fields
    return await update_ecommerce_order_fields(
        order_number,
        {
            "payment_status": "退款中",
            "ship_status": "退貨中",
            "notes_append": f"[{_now()} {operator} 申請退款：{reason}]",
        },
    )


async def cancel_order(order_number: str, reason: str, operator: str) -> bool:
    from app.services.sheets_service import update_ecommerce_order_fields
    return await update_ecommerce_order_fields(
        order_number,
        {
            "ship_status": "取消",
            "notes_append": f"[{_now()} {operator} 取消：{reason}]",
        },
    )


# ─── Queries ─────────────────────────────────────────────────────────

async def get_order(order_number: str) -> EcommerceOrder | None:
    from app.services.sheets_service import find_ecommerce_order
    return await find_ecommerce_order(order_number)


async def list_pending_payment() -> list[EcommerceOrder]:
    from app.services.sheets_service import get_ecommerce_orders_by_status
    return await get_ecommerce_orders_by_status(payment_status="未付款")


async def list_pending_shipment() -> list[EcommerceOrder]:
    from app.services.sheets_service import get_ecommerce_orders_by_status
    return await get_ecommerce_orders_by_status(ship_status="待出貨")


async def daily_summary(target_date_str: str | None = None) -> dict[str, Any]:
    """Return today's e-commerce summary."""
    from datetime import date
    from app.services.sheets_service import get_ecommerce_orders_by_date

    target = target_date_str or date.today().isoformat()
    orders = await get_ecommerce_orders_by_date(target)

    total_revenue = sum(o.total_amount for o in orders if o.payment_status == "已付款")
    pending_pay = [o for o in orders if o.payment_status == "未付款"]
    pending_ship = [o for o in orders if o.ship_status == "待出貨"]
    refunds = [o for o in orders if o.payment_status in ("退款中", "已退款")]

    return {
        "date": target,
        "total_orders": len(orders),
        "paid_revenue": total_revenue,
        "pending_payment": len(pending_pay),
        "pending_shipment": len(pending_ship),
        "refunds": len(refunds),
        "orders": orders,
    }


# ─── Formatting ──────────────────────────────────────────────────────

def format_order(order: EcommerceOrder) -> str:
    pay_icon = {"未付款": "⏳", "已付款": "✅", "退款中": "🔄", "已退款": "↩️"}.get(
        order.payment_status, "❓"
    )
    ship_icon = {
        "待出貨": "📦", "出貨中": "🚚", "已送達": "✅",
        "退貨中": "🔄", "已退貨": "↩️", "取消": "❌",
    }.get(order.ship_status, "❓")

    lines = [
        f"🛒 訂單：{order.order_number}",
        f"平台：{order.platform}  建立：{order.created_at}",
        f"客戶：{order.customer_name or '（未填）'}",
        f"品項：{order.items_summary}",
        f"金額：NT${order.total_amount:,.0f}"
        + (f"（含運 NT${order.shipping_fee:,.0f}）" if order.shipping_fee else ""),
        f"付款：{pay_icon} {order.payment_status}  出貨：{ship_icon} {order.ship_status}",
    ]
    if order.tracking_number:
        lines.append(f"物流：{order.logistics_company} {order.tracking_number}")
    if order.notes:
        lines.append(f"備註：{order.notes[-60:]}")
    return "\n".join(lines)


def format_order_list(orders: list[EcommerceOrder], title: str = "") -> str:
    if not orders:
        return f"{title}\n（無資料）" if title else "（無資料）"
    parts = [title] if title else []
    for o in orders[:10]:  # cap at 10 to avoid LINE message limit
        parts.append(
            f"• {o.order_number}  {o.customer_name or '?'}  "
            f"NT${o.total_amount:,.0f}  {o.ship_status}"
        )
    if len(orders) > 10:
        parts.append(f"（共 {len(orders)} 筆，僅顯示前 10 筆）")
    return "\n".join(parts)
