"""LINE command handlers for vendor management.

Commands:
  /廠商設定 廠商名 發票類型 請款週期 銀行代碼-帳號 戶名 [LINE群組ID]
      Register or update a vendor in the master sheet.
      發票類型: 統一發票 | 農產品收據 | 一般收據
      請款週期: 週結 | 月結

  /應付 廠商名
      Show all pending AP records for a vendor with subtotal.

  /匯款 廠商名 YYYY-MM-DD
      Mark all pending AP as paid, push wire transfer notice to vendor group.
"""
from __future__ import annotations

import logging
import re

from app.line.reply import push_text

log = logging.getLogger(__name__)

_VALID_INVOICE_TYPES = {"統一發票", "農產品收據", "一般收據"}
_VALID_BILLING_CYCLES = {"週結", "月結"}
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


async def handle_vendor_command(text: str, user_id: str, group_id: str) -> None:
    stripped = text.strip()
    if stripped.startswith("/廠商設定"):
        await _cmd_vendor_setup(stripped, group_id)
    elif stripped.startswith("/應付"):
        await _cmd_ap_query(stripped, group_id)
    elif stripped.startswith("/匯款"):
        await _cmd_wire_transfer(stripped, user_id, group_id)


async def _cmd_vendor_setup(text: str, group_id: str) -> None:
    """Parse and upsert vendor. Format:
    /廠商設定 廠商名 發票類型 請款週期 銀行代碼-帳號 戶名 [LINE群組ID]
    """
    from app.models.vendor import Vendor
    from app.services.sheets_service import upsert_vendor

    parts = text.split(maxsplit=6)
    if len(parts) < 6:
        await push_text(
            group_id,
            "格式：/廠商設定 廠商名 發票類型 請款週期 銀行代碼-帳號 戶名 [LINE群組ID]\n"
            "範例：/廠商設定 大成農城 農產品收據 週結 004-123456789 大成農業股份有限公司\n"
            "發票類型：統一發票 / 農產品收據 / 一般收據\n"
            "請款週期：週結 / 月結"
        )
        return

    vendor_name = parts[1]
    invoice_type = parts[2]
    billing_cycle = parts[3]
    bank_raw = parts[4]   # e.g. "004-123456789"
    account_name = parts[5]
    line_group_id = parts[6].strip() if len(parts) > 6 else ""

    if invoice_type not in _VALID_INVOICE_TYPES:
        await push_text(
            group_id,
            f"⚠️ 發票類型「{invoice_type}」不正確\n可選：統一發票 / 農產品收據 / 一般收據"
        )
        return

    if billing_cycle not in _VALID_BILLING_CYCLES:
        await push_text(
            group_id,
            f"⚠️ 請款週期「{billing_cycle}」不正確\n可選：週結 / 月結"
        )
        return

    bank_parts = bank_raw.split("-", 1)
    bank_code = bank_parts[0] if len(bank_parts) > 1 else ""
    account_number = bank_parts[1] if len(bank_parts) > 1 else bank_raw

    try:
        vendor = Vendor(
            name=vendor_name,
            invoice_type=invoice_type,  # type: ignore[arg-type]
            billing_cycle=billing_cycle,  # type: ignore[arg-type]
            bank_code=bank_code,
            account_number=account_number,
            account_name=account_name,
            line_group_id=line_group_id,
        )
        await upsert_vendor(vendor)
        await push_text(
            group_id,
            f"✅ 廠商已設定：{vendor_name}\n"
            f"發票類型：{invoice_type}\n"
            f"請款週期：{billing_cycle}\n"
            f"匯款帳號：{bank_code}-{account_number}（{account_name}）"
            + (f"\nLINE群組：已綁定" if line_group_id else "\nLINE群組：未設定（匯款通知將略過）")
        )
    except Exception as e:
        log.error("_cmd_vendor_setup error: %s", e)
        await push_text(group_id, f"⚠️ 廠商設定失敗：{e}")


async def _cmd_ap_query(text: str, group_id: str) -> None:
    """/應付 廠商名"""
    from app.services.sheets_service import get_vendor, get_pending_ap
    from app.services.vendor_service import format_ap_summary

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await push_text(group_id, "格式：/應付 廠商名\n範例：/應付 大成農城")
        return

    vendor_name = parts[1].strip()
    try:
        vendor = await get_vendor(vendor_name)
        if vendor is None:
            await push_text(
                group_id,
                f"找不到廠商「{vendor_name}」\n請先使用 /廠商設定 建立廠商資料"
            )
            return
        records = await get_pending_ap(vendor_name)
        await push_text(group_id, format_ap_summary(vendor, records))
    except Exception as e:
        log.error("_cmd_ap_query error: %s", e)
        await push_text(group_id, f"⚠️ 應付查詢失敗：{e}")


async def _cmd_wire_transfer(text: str, user_id: str, group_id: str) -> None:
    """/匯款 廠商名 YYYY-MM-DD"""
    from app.services.sheets_service import get_vendor, get_pending_ap, mark_ap_paid
    from app.services.vendor_service import build_wire_transfer_push

    parts = text.split()
    if len(parts) < 3:
        await push_text(
            group_id,
            "格式：/匯款 廠商名 YYYY-MM-DD\n範例：/匯款 大成農城 2026-05-15"
        )
        return

    vendor_name = parts[1]
    wire_date = parts[2]

    if not _DATE_RE.fullmatch(wire_date):
        await push_text(group_id, "⚠️ 日期格式錯誤，請用 YYYY-MM-DD")
        return

    try:
        vendor = await get_vendor(vendor_name)
        if vendor is None:
            await push_text(
                group_id,
                f"找不到廠商「{vendor_name}」\n請先使用 /廠商設定 建立廠商資料"
            )
            return

        records = await get_pending_ap(vendor_name)
        if not records:
            await push_text(group_id, f"✅ {vendor_name} 目前無待付款記錄，無需匯款")
            return

        total = sum(r.amount for r in records)
        updated = await mark_ap_paid(vendor_name, wire_date)

        # Confirm to operator group
        await push_text(
            group_id,
            f"✅ 已記錄匯款\n"
            f"廠商：{vendor_name}\n"
            f"日期：{wire_date}\n"
            f"金額：NT${total:,.0f}\n"
            f"筆數：{updated} 筆"
        )

        # Push to vendor LINE group if configured
        if vendor.line_group_id:
            push_msg = build_wire_transfer_push(vendor, records, wire_date)
            await push_text(vendor.line_group_id, push_msg)
        else:
            await push_text(
                group_id,
                f"ℹ️ {vendor_name} 尚未設定 LINE 群組，未發送廠商通知\n"
                f"可用 /廠商設定 {vendor_name} ... LINE群組ID 補設"
            )
    except Exception as e:
        log.error("_cmd_wire_transfer error: %s", e)
        await push_text(group_id, f"⚠️ 匯款記錄失敗：{e}")
