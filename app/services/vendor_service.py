"""Vendor management business logic.

Provides:
  format_ap_summary()       — build LINE message for /應付 查詢
  build_wire_transfer_push() — build push message for vendor LINE group after wire transfer
"""
from __future__ import annotations

from app.models.vendor import APRecord, Vendor


def format_ap_summary(vendor: Vendor, records: list[APRecord]) -> str:
    """Format AP query result as a LINE text message."""
    if not records:
        return (
            f"✅ {vendor.name} 目前無待付款記錄\n"
            f"請款週期：{vendor.billing_cycle}"
        )

    total = sum(r.amount for r in records)
    lines = [
        f"📋 {vendor.name} 本週應付明細",
        f"請款週期：{vendor.billing_cycle}　發票類型：{vendor.invoice_type}",
        "─────────────────",
    ]
    for r in records:
        lines.append(
            f"{r.delivery_date}　{r.item_name}　"
            f"{r.qty:.0f}{r.unit} @{r.unit_price:,.0f} = NT${r.amount:,.0f}"
        )
    lines += [
        "─────────────────",
        f"合計：NT${total:,.0f}",
        f"匯款帳號：{vendor.bank_code}-{vendor.account_number}（{vendor.account_name}）",
        f"\n輸入 /匯款 {vendor.name} YYYY-MM-DD 確認匯款",
    ]
    return "\n".join(lines)


def build_wire_transfer_push(
    vendor: Vendor, records: list[APRecord], wire_date: str
) -> str:
    """Build push message text to send to vendor LINE group."""
    total = sum(r.amount for r in records)
    item_lines = "\n".join(
        f"  {r.delivery_date} {r.item_name} {r.qty:.0f}{r.unit} NT${r.amount:,.0f}"
        for r in records
    )
    count = len(records)
    return (
        f"🏦 明倫餐飲集團 匯款通知\n"
        f"日期：{wire_date}\n"
        f"金額：NT${total:,.0f}\n"
        f"品項：\n{item_lines}\n"
        f"共 {count} 筆\n"
        f"─────────────────\n"
        f"如有疑問請回覆此訊息，謝謝！"
    )
