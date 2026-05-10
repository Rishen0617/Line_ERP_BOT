"""Google Sheets read/write service.

All Sheets access goes through this module. Uses Service Account credentials.

Sheet layout (single Spreadsheet, multiple tabs):
  Sheet1 = 收據記錄
  Sheet2 = 記帳流水帳
  Sheet3 = 訂單追蹤
  Sheet4 = 月報（公式，不由程式寫入）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import settings
from app.models.order import Order
from app.models.receipt import Receipt
from app.models.transaction import Transaction

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_TZ = ZoneInfo(settings.bot_timezone)

# Sheet tab names
SHEET_RECEIPTS = "收據記錄"
SHEET_LEDGER = "記帳流水帳"
SHEET_ORDERS = "訂單追蹤"


@lru_cache(maxsize=1)
def _get_service():
    creds = service_account.Credentials.from_service_account_info(
        settings.google_service_account_info, scopes=_SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _sheets():
    return _get_service().spreadsheets()


def _now_str() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")


# ─── Receipt (Sheet1) ──────────────────────────────────────────────────

async def append_receipt(
    receipt: Receipt, uploader_name: str, group_name: str
) -> int:
    """Append a receipt row to Sheet1. Returns the new row index (1-based)."""
    row = [
        receipt.doc_date.isoformat() if receipt.doc_date else "",  # A 日期
        _now_str(),                                                  # B 上傳時間
        uploader_name,                                               # C 上傳者
        receipt.doc_type,                                            # D 文件類型
        receipt.vendor_name or receipt.customer_name or "",          # E 廠商/客戶
        receipt.items_summary(),                                     # F 品項摘要
        receipt.total_amount or "",                                  # G 金額
        receipt.tax_amount or "",                                    # H 稅額
        receipt.doc_number or "",                                    # I 單號
        receipt.drive_url or "",                                     # J 圖片連結
        receipt.confidence,                                          # K AI信心度
        group_name,                                                  # L 群組
        receipt.notes or "",                                         # M 備註
    ]
    return await _append_row(SHEET_RECEIPTS, row)


async def find_by_doc_number(doc_number: str) -> Optional[dict[str, Any]]:
    """Search Sheet1 column I for an existing doc_number."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_RECEIPTS}!I:I",
            ).execute()
        )
        values = result.get("values", [])
        for i, row in enumerate(values):
            if row and row[0] == doc_number:
                return {"row": i + 1, "doc_number": doc_number}
        return None
    except Exception as e:
        log.error("find_by_doc_number error: %s", e)
        raise


# ─── Transaction (Sheet2) ─────────────────────────────────────────────

async def append_transaction(tx: Transaction, recorder_name: str) -> int:
    row = [
        tx.tx_date.isoformat(),  # A 日期
        tx.category,             # B 類別
        tx.description,          # C 說明
        tx.amount,               # D 金額
        tx.counter_party or "",  # E 對象
        tx.ref_doc_number or "", # F 關聯單號
        recorder_name,           # G 記錄者
    ]
    return await _append_row(SHEET_LEDGER, row)


# ─── Order (Sheet3) ───────────────────────────────────────────────────

async def append_order(order: Order, creator_name: str) -> int:
    summary = "、".join(
        f"{it.product_name} {it.qty}{it.unit}" for it in order.items[:3]
    )
    row = [
        order.order_date.isoformat(),    # A 訂單日期
        order.supplier,                  # B 供應商
        summary,                         # C 品項摘要
        order.total_amount or "",        # D 金額
        order.status,                    # E 狀態
        order.tracking_number or "",     # F 物流單號
        creator_name,                    # G 建立者
    ]
    return await _append_row(SHEET_ORDERS, row)


# ─── Monthly summary (Sheet4 is formula-driven) ───────────────────────

async def get_monthly_summary(year: int, month: int) -> dict[str, Any]:
    """Read ledger rows matching year/month and return aggregated totals."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_LEDGER}!A:D",
            ).execute()
        )
        rows = result.get("values", [])[1:]  # skip header
        prefix = f"{year}-{month:02d}"
        income = expense = payable = receivable = 0.0
        for row in rows:
            if len(row) < 4 or not str(row[0]).startswith(prefix):
                continue
            try:
                amt = float(row[3])
            except (ValueError, IndexError):
                continue
            cat = row[1] if len(row) > 1 else ""
            if cat == "收入":
                income += amt
            elif cat == "支出":
                expense += amt
            elif cat == "應付":
                payable += amt
            elif cat == "應收":
                receivable += amt
        return {
            "year": year, "month": month,
            "income": income, "expense": expense,
            "payable": payable, "receivable": receivable,
            "net": income - expense,
        }
    except Exception as e:
        log.error("get_monthly_summary error: %s", e)
        raise


# ─── internal helper ──────────────────────────────────────────────────

async def _append_row(sheet_name: str, row: list) -> int:
    str_row = [str(v) if v is not None else "" for v in row]
    result = await asyncio.to_thread(
        lambda: _sheets().values().append(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [str_row]},
        ).execute()
    )
    updated = result.get("updates", {}).get("updatedRange", "")
    log.info("appended to %s: %s", sheet_name, updated)
    # Parse row number from range like "Sheet1!A42:M42"
    try:
        return int(updated.split("A")[-1].split(":")[0])
    except (ValueError, IndexError):
        return 0
