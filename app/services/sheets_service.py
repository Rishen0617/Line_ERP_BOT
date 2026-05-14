"""Google Sheets read/write service.

All Sheets access goes through this module. Uses Service Account credentials.

Sheet layout (single Spreadsheet, multiple tabs):
  Sheet1 = 收據記錄
  Sheet2 = 記帳流水帳
  Sheet3 = 訂單追蹤
  Sheet4 = 月報（公式，不由程式寫入）
  Sheet5 = 班表        (A=日期 B=員工ID C=員工名 D=店別 E=開始 F=結束 G=工時 H=班別 I=狀態 J=備註)
  Sheet6 = 請假記錄    (A=申請時間 B=員工ID C=員工名 D=假日 E=假別 F=原因 G=狀態 H=審核者 I=備註)
  Sheet7 = 電商訂單    (A=建立時間 B=訂單編號 C=平台 D=客戶 E=電話 F=地址 G=品項
                        H=商品金額 I=運費 J=總金額 K=付款方式 L=付款狀態
                        M=物流公司 N=物流單號 O=出貨狀態 P=備註 Q=建立者)
  Sheet8 = 庫存台帳    (A=品項 B=規格 C=單位 D=安全庫存 E=目前庫存 F=最後更新 G=分類 H=供應商)
  Sheet9 = 庫存異動    (A=時間 B=品項 C=異動類型 D=數量 E=單位 F=店別 G=關聯單號 H=操作者 I=備註)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import settings
from app.models.ecommerce import EcommerceOrder
from app.models.inventory import InventoryItem, StockMovement
from app.models.order import Order
from app.models.receipt import Receipt
from app.models.shift import LeaveRequest, Shift
from app.models.transaction import Transaction

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_TZ = ZoneInfo(settings.bot_timezone)

# Sheet tab names
SHEET_RECEIPTS = "收據記錄"
SHEET_LEDGER = "記帳流水帳"
SHEET_ORDERS = "訂單追蹤"
SHEET_SCHEDULE = "班表"
SHEET_LEAVE = "請假記錄"
SHEET_ECOMMERCE = "電商訂單"
SHEET_INVENTORY = "庫存台帳"
SHEET_MOVEMENTS = "庫存異動"
SHEET_VENDORS = "廠商主檔"
SHEET_AP = "應付帳款"

# Vendor master column indices (0-based, Sheet10)
_VEN_COL_NAME = 0
_VEN_COL_INVOICE_TYPE = 1
_VEN_COL_BILLING_CYCLE = 2
_VEN_COL_BANK_CODE = 3
_VEN_COL_ACCOUNT_NO = 4
_VEN_COL_ACCOUNT_NAME = 5
_VEN_COL_LINE_GROUP = 6
_VEN_COL_NOTES = 7

# AP column indices (0-based, Sheet11)
_AP_COL_DATE = 0
_AP_COL_VENDOR = 1
_AP_COL_ITEM = 2
_AP_COL_QTY = 3
_AP_COL_UNIT = 4
_AP_COL_UNIT_PRICE = 5
_AP_COL_AMOUNT = 6
_AP_COL_INVOICE_TYPE = 7
_AP_COL_INVOICE_NO = 8
_AP_COL_BILLING_CYCLE = 9
_AP_COL_STATUS = 10
_AP_COL_WIRE_DATE = 11
_AP_COL_NOTES = 12

# Inventory column indices (0-based, Sheet8)
_INV_COL_NAME = 0
_INV_COL_STOCK = 4
_INV_COL_SAFETY = 3
_INV_COL_UPDATED = 5

# Column indices for 電商訂單 (0-based)
_EC_COL_ORDER_NO = 1
_EC_COL_PAY_STATUS = 11
_EC_COL_LOGISTICS = 12
_EC_COL_TRACKING = 13
_EC_COL_SHIP_STATUS = 14
_EC_COL_NOTES = 15


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


STORES = ["逢甲店", "福星店", "中科店", "大坑店"]


async def get_store_monthly_data(
    months: int = 6,
    stores: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return per-store income + total expense for each of the last N calendar months.

    Result structure (sorted oldest → newest):
      [{"year":int,"month":int,"stores":{store:income},"income_other":float,"expense":float,"income":float,"net":float}, ...]

    Income attribution: ledger rows where 類別=收入 and 對象 matches a known store name.
    Unmatched income (other/misc) lands in income_other.
    """
    if stores is None:
        stores = STORES

    today = date.today()
    target_months: set[tuple[int, int]] = set()
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        target_months.add((y, m))

    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_LEDGER}!A:E",
            ).execute()
        )
        rows = result.get("values", [])[1:]  # skip header
    except Exception as e:
        log.error("get_store_monthly_data error: %s", e)
        raise

    # Pre-build buckets
    buckets: dict[tuple[int, int], dict] = {
        (y, m): {"year": y, "month": m,
                 "stores": {s: 0.0 for s in stores},
                 "income_other": 0.0, "expense": 0.0}
        for y, m in target_months
    }

    for row in rows:
        if len(row) < 4:
            continue
        date_str = str(row[0])
        try:
            yr = int(date_str[:4])
            mo = int(date_str[5:7])
        except (ValueError, IndexError):
            continue
        key = (yr, mo)
        if key not in buckets:
            continue
        try:
            amt = float(row[3])
        except (ValueError, IndexError):
            continue
        cat = str(row[1]) if len(row) > 1 else ""
        obj = str(row[4]) if len(row) > 4 else ""

        if cat == "收入":
            if obj in stores:
                buckets[key]["stores"][obj] += amt
            else:
                buckets[key]["income_other"] += amt
        elif cat == "支出":
            buckets[key]["expense"] += amt

    out = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        total_income = sum(b["stores"].values()) + b["income_other"]
        out.append({
            "year": b["year"], "month": b["month"],
            "stores": dict(b["stores"]),
            "income_other": b["income_other"],
            "expense": b["expense"],
            "income": total_income,
            "net": total_income - b["expense"],
        })
    return out


# ─── Dashboard reads ─────────────────────────────────────────────────

async def get_recent_receipts(n: int = 30) -> list[dict[str, Any]]:
    """Return the last N receipt rows from Sheet1, newest first."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_RECEIPTS}!A:M",
            ).execute()
        )
        rows = result.get("values", [])
        if len(rows) <= 1:
            return []
        keys = ["date", "upload_time", "uploader", "doc_type", "vendor",
                "items", "amount", "tax", "doc_number", "drive_url",
                "confidence", "group", "notes"]
        data = rows[1:]
        recent = list(reversed(data[-n:]))
        out = []
        for row in recent:
            padded = row + [""] * (len(keys) - len(row))
            out.append(dict(zip(keys, padded)))
        return out
    except Exception as e:
        log.error("get_recent_receipts error: %s", e)
        raise


async def get_recent_orders(n: int = 30) -> list[dict[str, Any]]:
    """Return the last N order rows from Sheet3, newest first."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ORDERS}!A:G",
            ).execute()
        )
        rows = result.get("values", [])
        if len(rows) <= 1:
            return []
        keys = ["date", "supplier", "items", "amount", "status", "tracking", "creator"]
        data = rows[1:]
        recent = list(reversed(data[-n:]))
        out = []
        for row in recent:
            padded = row + [""] * (len(keys) - len(row))
            out.append(dict(zip(keys, padded)))
        return out
    except Exception as e:
        log.error("get_recent_orders error: %s", e)
        raise


# ─── Schedule / Shift (Sheet5) ───────────────────────────────────────

async def append_shift(shift: Shift) -> int:
    """Append one shift row to Sheet5 (班表)."""
    row = [
        shift.shift_date.isoformat(),          # A 日期
        shift.employee_id,                      # B 員工ID
        shift.employee_name,                    # C 員工名
        shift.store,                            # D 店別
        shift.start_time.strftime("%H:%M"),     # E 開始時間
        shift.end_time.strftime("%H:%M"),       # F 結束時間
        shift.hours,                            # G 工時
        shift.shift_type,                       # H 班別
        shift.status,                           # I 狀態
        shift.notes or "",                      # J 備註
    ]
    return await _append_row(SHEET_SCHEDULE, row)


async def get_shifts_by_date(target_date: date) -> list[Shift]:
    """Return all shifts on *target_date*."""
    return await get_shifts_by_date_range(target_date, target_date)


async def get_shifts_by_date_range(from_date: date, to_date: date) -> list[Shift]:
    """Return all shifts where from_date ≤ shift_date ≤ to_date."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_SCHEDULE}!A:J",
            ).execute()
        )
        rows = result.get("values", [])[1:]  # skip header
        shifts: list[Shift] = []
        for r in rows:
            if len(r) < 6:
                continue
            try:
                d = date.fromisoformat(r[0])
            except ValueError:
                continue
            if not (from_date <= d <= to_date):
                continue
            try:
                shifts.append(_row_to_shift(r))
            except Exception:
                continue
        return shifts
    except Exception as e:
        log.error("get_shifts_by_date_range error: %s", e)
        raise


async def get_employee_shifts_in_range(
    employee_id: str, from_date: date, to_date: date
) -> list[Shift]:
    """Return shifts for a specific employee in the date range."""
    all_shifts = await get_shifts_by_date_range(from_date, to_date)
    return [s for s in all_shifts if s.employee_id == employee_id]


def _row_to_shift(r: list) -> Shift:
    from datetime import time as dt_time

    def _t(s: str) -> dt_time:
        h, m = s.split(":")
        return dt_time(int(h), int(m))

    return Shift(
        shift_date=date.fromisoformat(r[0]),
        employee_id=r[1] if len(r) > 1 else "",
        employee_name=r[2] if len(r) > 2 else "",
        store=r[3] if len(r) > 3 else "",
        start_time=_t(r[4]) if len(r) > 4 else dt_time(0, 0),
        end_time=_t(r[5]) if len(r) > 5 else dt_time(0, 0),
        shift_type=r[7] if len(r) > 7 else "早班",    # type: ignore[arg-type]
        status=r[8] if len(r) > 8 else "正常",         # type: ignore[arg-type]
        notes=r[9] if len(r) > 9 else None,
    )


# ─── Leave Request (Sheet6) ──────────────────────────────────────────

async def append_leave_request(req: LeaveRequest) -> int:
    """Append a leave request row to Sheet6 (請假記錄)."""
    row = [
        req.apply_time,        # A 申請時間
        req.employee_id,       # B 員工ID
        req.employee_name,     # C 員工名
        req.leave_date.isoformat(),  # D 假日
        req.leave_type,        # E 假別
        req.reason,            # F 原因
        req.status,            # G 狀態
        req.reviewer,          # H 審核者
        req.notes,             # I 備註
    ]
    return await _append_row(SHEET_LEAVE, row)


async def approve_leave_request(
    employee_name: str, leave_date: date, reviewer: str
) -> bool:
    """Find a pending leave row and update status to 核准. Returns True if found."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_LEAVE}!A:I",
            ).execute()
        )
        rows = result.get("values", [])
        for i, r in enumerate(rows):
            if len(r) < 7:
                continue
            name_match = (r[2] == employee_name)
            date_match = (r[3] == leave_date.isoformat())
            pending = (r[6] == "待審")
            if name_match and date_match and pending:
                row_num = i + 1  # 1-based
                # Update G (status) and H (reviewer)
                await asyncio.to_thread(
                    lambda: _sheets().values().batchUpdate(
                        spreadsheetId=settings.google_spreadsheet_id,
                        body={
                            "valueInputOption": "USER_ENTERED",
                            "data": [
                                {
                                    "range": f"{SHEET_LEAVE}!G{row_num}:H{row_num}",
                                    "values": [["核准", reviewer]],
                                }
                            ],
                        },
                    ).execute()
                )
                return True
        return False
    except Exception as e:
        log.error("approve_leave_request error: %s", e)
        raise


# ─── Vendor Master (Sheet10) ──────────────────────────────────────────

async def get_vendor(name: str) -> Optional["Vendor"]:
    """Return Vendor from 廠商主檔 by name, or None if not found."""
    from app.models.vendor import Vendor
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_VENDORS}!A:H",
            ).execute()
        )
    except Exception as e:
        log.error("get_vendor sheets error: %s", e)
        raise
    rows = result.get("values", [])[1:]  # skip header
    for row in rows:
        if row and row[_VEN_COL_NAME] == name:
            def _get(r, i, default=""):
                return r[i] if len(r) > i else default
            return Vendor(
                name=_get(row, _VEN_COL_NAME),
                invoice_type=_get(row, _VEN_COL_INVOICE_TYPE) or "農產品收據",
                billing_cycle=_get(row, _VEN_COL_BILLING_CYCLE) or "週結",
                bank_code=_get(row, _VEN_COL_BANK_CODE),
                account_number=_get(row, _VEN_COL_ACCOUNT_NO),
                account_name=_get(row, _VEN_COL_ACCOUNT_NAME),
                line_group_id=_get(row, _VEN_COL_LINE_GROUP),
                notes=_get(row, _VEN_COL_NOTES),
            )
    return None


async def upsert_vendor(vendor: "Vendor") -> None:
    """Insert or update a vendor row in 廠商主檔.

    If a row with vendor.name exists, overwrite it. Otherwise append.
    """
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_VENDORS}!A:A",
        ).execute()
    )
    names = [r[0] if r else "" for r in result.get("values", [])]
    row_data = [
        vendor.name,
        vendor.invoice_type,
        vendor.billing_cycle,
        vendor.bank_code,
        vendor.account_number,
        vendor.account_name,
        vendor.line_group_id,
        vendor.notes,
    ]
    try:
        idx = names.index(vendor.name)  # 1-based sheet row
        range_str = f"{SHEET_VENDORS}!A{idx + 1}:H{idx + 1}"
        await asyncio.to_thread(
            lambda: _sheets().values().update(
                spreadsheetId=settings.google_spreadsheet_id,
                range=range_str,
                valueInputOption="RAW",
                body={"values": [row_data]},
            ).execute()
        )
    except ValueError:
        # Not found — append
        await asyncio.to_thread(
            lambda: _sheets().values().append(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_VENDORS}!A:H",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row_data]},
            ).execute()
        )


# ─── AP Records (Sheet11) ─────────────────────────────────────────────

async def append_ap_record(ap: "APRecord") -> int:
    """Append a row to 應付帳款. Returns 1-based row number."""
    row = [
        ap.delivery_date,       # A 到貨日期
        ap.vendor_name,         # B 廠商名
        ap.item_name,           # C 品項
        ap.qty,                 # D 數量
        ap.unit,                # E 單位
        ap.unit_price,          # F 單價
        ap.amount,              # G 金額
        ap.invoice_type,        # H 發票類型
        ap.invoice_number,      # I 單號
        ap.billing_cycle,       # J 請款週期
        ap.status,              # K 狀態
        ap.wire_date,           # L 匯款日期
        ap.notes,               # M 備註
    ]
    return await _append_row(SHEET_AP, row)


async def get_pending_ap(vendor_name: str) -> list["APRecord"]:
    """Return all 待付款 AP rows for the given vendor."""
    from app.models.vendor import APRecord
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_AP}!A:M",
        ).execute()
    )
    rows = result.get("values", [])[1:]  # skip header
    records: list[APRecord] = []
    for row in rows:
        def _g(r, i, default=""):
            return r[i] if len(r) > i else default
        if _g(row, _AP_COL_VENDOR) == vendor_name and _g(row, _AP_COL_STATUS) == "待付款":
            records.append(APRecord(
                delivery_date=_g(row, _AP_COL_DATE),
                vendor_name=_g(row, _AP_COL_VENDOR),
                item_name=_g(row, _AP_COL_ITEM),
                qty=float(_g(row, _AP_COL_QTY) or 0),
                unit=_g(row, _AP_COL_UNIT),
                unit_price=float(_g(row, _AP_COL_UNIT_PRICE) or 0),
                amount=float(_g(row, _AP_COL_AMOUNT) or 0),
                invoice_type=_g(row, _AP_COL_INVOICE_TYPE),
                invoice_number=_g(row, _AP_COL_INVOICE_NO),
                billing_cycle=_g(row, _AP_COL_BILLING_CYCLE),
                status="待付款",
                wire_date=_g(row, _AP_COL_WIRE_DATE),
                notes=_g(row, _AP_COL_NOTES),
            ))
    return records


async def mark_ap_paid(vendor_name: str, wire_date: str) -> int:
    """Mark all 待付款 rows for vendor as 已匯款. Returns count updated."""
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_AP}!A:M",
        ).execute()
    )
    rows = result.get("values", [])[1:]  # skip header row; data rows are 1-indexed from row 2
    updated = 0
    for i, row in enumerate(rows):
        def _g(r, idx, default=""):
            return r[idx] if len(r) > idx else default
        if _g(row, _AP_COL_VENDOR) == vendor_name and _g(row, _AP_COL_STATUS) == "待付款":
            sheet_row = i + 2  # i=0 → sheet row 2 (row 1 is header)
            range_str = f"{SHEET_AP}!K{sheet_row}:L{sheet_row}"
            await asyncio.to_thread(
                lambda rng=range_str: _sheets().values().update(
                    spreadsheetId=settings.google_spreadsheet_id,
                    range=rng,
                    valueInputOption="RAW",
                    body={"values": [["已匯款", wire_date]]},
                ).execute()
            )
            updated += 1
    return updated


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


# ─── E-commerce Orders (Sheet7) ───────────────────────────────────────

async def append_ecommerce_order(order: EcommerceOrder) -> int:
    """Append one e-commerce order row to Sheet7 (電商訂單)."""
    row = [
        order.created_at,           # A 建立時間
        order.order_number,         # B 訂單編號
        order.platform,             # C 平台
        order.customer_name,        # D 客戶
        order.customer_phone,       # E 電話
        order.shipping_address,     # F 地址
        order.items_summary,        # G 品項
        order.subtotal,             # H 商品金額
        order.shipping_fee,         # I 運費
        order.total_amount,         # J 總金額
        order.payment_method,       # K 付款方式
        order.payment_status,       # L 付款狀態
        order.logistics_company,    # M 物流公司
        order.tracking_number,      # N 物流單號
        order.ship_status,          # O 出貨狀態
        order.notes,                # P 備註
        order.created_by,           # Q 建立者
    ]
    return await _append_row(SHEET_ECOMMERCE, row)


async def find_ecommerce_order(order_number: str) -> Optional[EcommerceOrder]:
    """Find an order by order_number in Sheet7."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ECOMMERCE}!A:Q",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        for r in rows:
            if len(r) > 1 and r[1] == order_number:
                return _row_to_ecommerce_order(r)
        return None
    except Exception as e:
        log.error("find_ecommerce_order error: %s", e)
        raise


async def update_ecommerce_order_fields(
    order_number: str, fields: dict
) -> bool:
    """Find the order row and patch specific columns. Returns True if found."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ECOMMERCE}!A:Q",
            ).execute()
        )
        rows = result.get("values", [])
        for i, r in enumerate(rows):
            if len(r) > 1 and r[1] == order_number:
                row_num = i + 1  # 1-based
                updates = []

                col_map = {
                    "payment_status": _EC_COL_PAY_STATUS,
                    "logistics_company": _EC_COL_LOGISTICS,
                    "tracking_number": _EC_COL_TRACKING,
                    "ship_status": _EC_COL_SHIP_STATUS,
                }
                for field, col_idx in col_map.items():
                    if field in fields:
                        col_letter = chr(ord("A") + col_idx)
                        updates.append({
                            "range": f"{SHEET_ECOMMERCE}!{col_letter}{row_num}",
                            "values": [[fields[field]]],
                        })

                # Append to notes column
                if "notes_append" in fields:
                    current_notes = r[_EC_COL_NOTES] if len(r) > _EC_COL_NOTES else ""
                    new_notes = (current_notes + " " + fields["notes_append"]).strip()
                    col_letter = chr(ord("A") + _EC_COL_NOTES)
                    updates.append({
                        "range": f"{SHEET_ECOMMERCE}!{col_letter}{row_num}",
                        "values": [[new_notes]],
                    })

                if updates:
                    await asyncio.to_thread(
                        lambda: _sheets().values().batchUpdate(
                            spreadsheetId=settings.google_spreadsheet_id,
                            body={"valueInputOption": "USER_ENTERED", "data": updates},
                        ).execute()
                    )
                return True
        return False
    except Exception as e:
        log.error("update_ecommerce_order_fields error: %s", e)
        raise


async def get_ecommerce_orders_by_status(
    payment_status: str | None = None,
    ship_status: str | None = None,
) -> list[EcommerceOrder]:
    """Return orders matching the given status filter(s)."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ECOMMERCE}!A:Q",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        orders = []
        for r in rows:
            try:
                o = _row_to_ecommerce_order(r)
            except Exception:
                continue
            if payment_status and o.payment_status != payment_status:
                continue
            if ship_status and o.ship_status != ship_status:
                continue
            orders.append(o)
        return orders
    except Exception as e:
        log.error("get_ecommerce_orders_by_status error: %s", e)
        raise


async def get_ecommerce_orders_by_date(target_date: str) -> list[EcommerceOrder]:
    """Return orders created on *target_date* (YYYY-MM-DD)."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_ECOMMERCE}!A:Q",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        orders = []
        for r in rows:
            if not r or not str(r[0]).startswith(target_date):
                continue
            try:
                orders.append(_row_to_ecommerce_order(r))
            except Exception:
                continue
        return orders
    except Exception as e:
        log.error("get_ecommerce_orders_by_date error: %s", e)
        raise


def _row_to_ecommerce_order(r: list) -> EcommerceOrder:
    def _get(idx: int) -> str:
        return r[idx] if len(r) > idx else ""

    def _float(idx: int) -> float:
        try:
            return float(_get(idx))
        except (ValueError, TypeError):
            return 0.0

    return EcommerceOrder(
        created_at=_get(0),
        order_number=_get(1),
        platform=_get(2) or "其他",           # type: ignore[arg-type]
        customer_name=_get(3),
        customer_phone=_get(4),
        shipping_address=_get(5),
        items_summary=_get(6),
        subtotal=_float(7),
        shipping_fee=_float(8),
        total_amount=_float(9),
        payment_method=_get(10) or "其他",    # type: ignore[arg-type]
        payment_status=_get(11) or "未付款",   # type: ignore[arg-type]
        logistics_company=_get(12),
        tracking_number=_get(13),
        ship_status=_get(14) or "待出貨",       # type: ignore[arg-type]
        notes=_get(15),
        created_by=_get(16),
    )


# ─── Inventory Ledger (Sheet8) ────────────────────────────────────────

async def get_all_inventory_items() -> list[InventoryItem]:
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_INVENTORY}!A:H",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        items = []
        for r in rows:
            if not r or not r[0]:
                continue
            try:
                items.append(_row_to_inventory(r))
            except Exception:
                continue
        return items
    except Exception as e:
        log.error("get_all_inventory_items error: %s", e)
        raise


async def get_inventory_item(name: str) -> Optional[InventoryItem]:
    items = await get_all_inventory_items()
    for it in items:
        if it.name == name:
            return it
    return None


async def update_inventory_stock(
    name: str, delta: float = 0.0, absolute: float | None = None
) -> InventoryItem:
    """Find item row and update current stock (E) and last-updated (F)."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    tz = ZoneInfo(settings.bot_timezone)
    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_INVENTORY}!A:H",
            ).execute()
        )
        rows = result.get("values", [])
        for i, r in enumerate(rows):
            if r and r[0] == name:
                row_num = i + 1
                cur = float(r[_INV_COL_STOCK]) if len(r) > _INV_COL_STOCK and r[_INV_COL_STOCK] else 0.0
                new_stock = absolute if absolute is not None else cur + delta
                await asyncio.to_thread(
                    lambda: _sheets().values().batchUpdate(
                        spreadsheetId=settings.google_spreadsheet_id,
                        body={
                            "valueInputOption": "USER_ENTERED",
                            "data": [
                                {"range": f"{SHEET_INVENTORY}!E{row_num}", "values": [[new_stock]]},
                                {"range": f"{SHEET_INVENTORY}!F{row_num}", "values": [[now_str]]},
                            ],
                        },
                    ).execute()
                )
                item = _row_to_inventory(r)
                item.current_stock = new_stock
                item.last_updated = now_str
                return item

        # Item not found → create a new row
        new_stock = absolute if absolute is not None else max(0.0, delta)
        new_row = [name, "", "", 0, new_stock, now_str, "", ""]
        await _append_row(SHEET_INVENTORY, new_row)
        return InventoryItem(name=name, current_stock=new_stock, last_updated=now_str)

    except Exception as e:
        log.error("update_inventory_stock error: %s", e)
        raise


async def update_inventory_safety_stock(name: str, level: float) -> InventoryItem:
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_INVENTORY}!A:H",
            ).execute()
        )
        rows = result.get("values", [])
        for i, r in enumerate(rows):
            if r and r[0] == name:
                row_num = i + 1
                await asyncio.to_thread(
                    lambda: _sheets().values().update(
                        spreadsheetId=settings.google_spreadsheet_id,
                        range=f"{SHEET_INVENTORY}!D{row_num}",
                        valueInputOption="USER_ENTERED",
                        body={"values": [[level]]},
                    ).execute()
                )
                item = _row_to_inventory(r)
                item.safety_stock = level
                return item

        # New item
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now_str = datetime.now(ZoneInfo(settings.bot_timezone)).strftime("%Y-%m-%d %H:%M")
        new_row = [name, "", "", level, 0, now_str, "", ""]
        await _append_row(SHEET_INVENTORY, new_row)
        return InventoryItem(name=name, safety_stock=level)
    except Exception as e:
        log.error("update_inventory_safety_stock error: %s", e)
        raise


def _row_to_inventory(r: list) -> InventoryItem:
    def _g(i: int) -> str:
        return r[i] if len(r) > i else ""

    def _f(i: int) -> float:
        try:
            return float(_g(i))
        except (ValueError, TypeError):
            return 0.0

    return InventoryItem(
        name=_g(0),
        spec=_g(1),
        unit=_g(2) or "個",
        safety_stock=_f(3),
        current_stock=_f(4),
        last_updated=_g(5),
        category=_g(6),
        supplier=_g(7),
    )


# ─── Stock Movements (Sheet9) ─────────────────────────────────────────

async def append_stock_movement(m: StockMovement) -> int:
    row = [
        m.moved_at,         # A 時間
        m.item_name,        # B 品項
        m.movement_type,    # C 異動類型
        m.quantity,         # D 數量
        m.unit,             # E 單位
        m.store,            # F 店別
        m.ref_order_no,     # G 關聯單號
        m.operator,         # H 操作者
        m.notes,            # I 備註
    ]
    return await _append_row(SHEET_MOVEMENTS, row)


async def get_stock_movements_since(since_date: str) -> list[StockMovement]:
    """Return all movements where moved_at >= since_date (YYYY-MM-DD prefix match)."""
    try:
        result = await asyncio.to_thread(
            lambda: _sheets().values().get(
                spreadsheetId=settings.google_spreadsheet_id,
                range=f"{SHEET_MOVEMENTS}!A:I",
            ).execute()
        )
        rows = result.get("values", [])[1:]
        movements = []
        for r in rows:
            if not r or str(r[0]) < since_date:
                continue
            try:
                movements.append(_row_to_movement(r))
            except Exception:
                continue
        return movements
    except Exception as e:
        log.error("get_stock_movements_since error: %s", e)
        raise


def _row_to_movement(r: list) -> StockMovement:
    def _g(i: int) -> str:
        return r[i] if len(r) > i else ""

    return StockMovement(
        moved_at=_g(0),
        item_name=_g(1),
        movement_type=_g(2) or "叫貨",  # type: ignore[arg-type]
        quantity=float(_g(3) or 0),
        unit=_g(4),
        store=_g(5),
        ref_order_no=_g(6),
        operator=_g(7),
        notes=_g(8),
    )
