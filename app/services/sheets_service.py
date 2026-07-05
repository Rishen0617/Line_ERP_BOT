"""Data service — dual-write facade.

Write path  : xlsx (primary, synchronous) → Google Sheets (secondary, async fire-and-forget)
Read path   : xlsx only (fast, offline-capable)

Google Sheets is now a backup / audit trail.  503 or quota errors on the Sheets side
never block the main flow — they are logged and retried up to _MAX_RETRIES times in the
background task, then silently dropped if still failing.

Sheet layout (single Spreadsheet, multiple tabs):
  Sheet1  = 收據記錄
  Sheet2  = 記帳流水帳
  Sheet3  = 訂單追蹤
  Sheet4  = 月報（公式，不由程式寫入）
  Sheet5  = 班表        (A=日期 B=員工ID C=員工名 D=店別 E=開始 F=結束 G=工時 H=班別 I=狀態 J=備註)
  Sheet6  = 請假記錄    (A=申請時間 B=員工ID C=員工名 D=假日 E=假別 F=原因 G=狀態 H=審核者 I=備註)
  Sheet7  = 電商訂單    (A=建立時間 B=訂單編號 C=平台 D=客戶 E=電話 F=地址 G=品項
                         H=商品金額 I=運費 J=總金額 K=付款方式 L=付款狀態
                         M=物流公司 N=物流單號 O=出貨狀態 P=備註 Q=建立者)
  Sheet8  = 庫存台帳    (A=品項 B=規格 C=單位 D=安全庫存 E=目前庫存 F=最後更新 G=分類 H=供應商)
  Sheet9  = 庫存異動    (A=時間 B=品項 C=異動類型 D=數量 E=單位 F=店別 G=關聯單號 H=操作者 I=備註)
  Sheet10 = 廠商主檔
  Sheet11 = 應付帳款
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
from googleapiclient.errors import HttpError

from app.config import settings
from app.models.ecommerce import EcommerceOrder
from app.models.inventory import InventoryItem, StockMovement
from app.models.order import Order
from app.models.receipt import Receipt
from app.models.shift import LeaveRequest, Shift
from app.models.transaction import Transaction
from app.services import xlsx_service

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_TZ = ZoneInfo(settings.bot_timezone)

# Sheet tab names
SHEET_RECEIPTS  = "收據記錄"
SHEET_LEDGER    = "記帳流水帳"
SHEET_ORDERS    = "訂單追蹤"
SHEET_SCHEDULE  = "班表"
SHEET_LEAVE     = "請假記錄"
SHEET_ECOMMERCE = "電商訂單"
SHEET_INVENTORY = "庫存台帳"
SHEET_MOVEMENTS = "庫存異動"
SHEET_VENDORS   = "廠商主檔"
SHEET_AP        = "應付帳款"

# Vendor master column indices (0-based, Sheet10)
_VEN_COL_NAME         = 0
_VEN_COL_INVOICE_TYPE = 1
_VEN_COL_BILLING_CYCLE = 2
_VEN_COL_BANK_CODE    = 3
_VEN_COL_ACCOUNT_NO   = 4
_VEN_COL_ACCOUNT_NAME = 5
_VEN_COL_LINE_GROUP   = 6
_VEN_COL_NOTES        = 7

# AP column indices (0-based, Sheet11)
_AP_COL_DATE          = 0
_AP_COL_VENDOR        = 1
_AP_COL_ITEM          = 2
_AP_COL_QTY           = 3
_AP_COL_UNIT          = 4
_AP_COL_UNIT_PRICE    = 5
_AP_COL_AMOUNT        = 6
_AP_COL_INVOICE_TYPE  = 7
_AP_COL_INVOICE_NO    = 8
_AP_COL_BILLING_CYCLE = 9
_AP_COL_STATUS        = 10
_AP_COL_WIRE_DATE     = 11
_AP_COL_NOTES         = 12

# Inventory column indices (0-based, Sheet8)
_INV_COL_NAME    = 0
_INV_COL_STOCK   = 4
_INV_COL_SAFETY  = 3
_INV_COL_UPDATED = 5

# Column indices for 電商訂單 (0-based)
_EC_COL_ORDER_NO   = 1
_EC_COL_PAY_STATUS = 11
_EC_COL_LOGISTICS  = 12
_EC_COL_TRACKING   = 13
_EC_COL_SHIP_STATUS = 14
_EC_COL_NOTES      = 15

# Retry settings for Sheets background sync
_RETRY_STATUS   = {429, 500, 502, 503, 504}
_MAX_RETRIES    = 3
_RETRY_BASE_DELAY = 1.0  # seconds


# ─── Google Sheets client ─────────────────────────────────────────────


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


# ─── Background Sheets sync helpers ──────────────────────────────────


async def _gsheets_with_retry(fn, *, label: str) -> Any:
    """Run a Sheets API callable with exponential-backoff retry. Raises on final failure."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await asyncio.to_thread(fn)
        except HttpError as exc:
            if exc.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.warning(
                    "Sheets sync HTTP %s [%s] attempt %d/%d, retry in %.1fs",
                    exc.status_code, label, attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
    raise RuntimeError("unreachable")  # pragma: no cover


async def _gsheets_fire(coro_fn, label: str) -> None:
    """Fire-and-forget coroutine wrapper: catches all errors so Sheets failures
    never surface to the caller."""
    try:
        await coro_fn()
    except Exception as exc:
        log.warning("Sheets background sync failed [%s]: %s", label, exc)


def _bg(coro_fn, label: str) -> None:
    """Schedule *coro_fn* as a background task (fire-and-forget)."""
    asyncio.ensure_future(_gsheets_fire(coro_fn, label))


# ─── Low-level Sheets append (background use only) ────────────────────


async def _gsheets_append_row(sheet_name: str, row: list) -> None:
    str_row = [str(v) if v is not None else "" for v in row]
    await _gsheets_with_retry(
        lambda: _sheets().values().append(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [str_row]},
        ).execute(),
        label=f"append:{sheet_name}",
    )


async def _gsheets_batch_update(data: list[dict], label: str) -> None:
    await _gsheets_with_retry(
        lambda: _sheets().values().batchUpdate(
            spreadsheetId=settings.google_spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute(),
        label=label,
    )


# ─── Primary dual-write helper ────────────────────────────────────────


async def _append_row(sheet_name: str, row: list) -> int:
    """Write to xlsx (primary), fire-and-forget to Sheets (secondary)."""
    result = await xlsx_service.append_row(sheet_name, row)
    _bg(lambda r=row: _gsheets_append_row(sheet_name, r), f"sync:{sheet_name}")
    return result


# ─── Receipt (Sheet1) ──────────────────────────────────────────────────


async def append_receipt(
    receipt: Receipt, uploader_name: str, group_name: str
) -> int:
    """Append a receipt row. Returns the new row index (1-based)."""
    row = [
        receipt.doc_date.isoformat() if receipt.doc_date else "",
        _now_str(),
        uploader_name,
        receipt.doc_type,
        receipt.vendor_name or receipt.customer_name or "",
        receipt.items_summary(),
        receipt.total_amount or "",
        receipt.tax_amount or "",
        receipt.doc_number or "",
        receipt.drive_url or "",
        receipt.confidence,
        group_name,
        receipt.notes or "",
    ]
    return await _append_row(SHEET_RECEIPTS, row)


async def find_by_doc_number(doc_number: str) -> Optional[dict[str, Any]]:
    """Search Sheet1 column I (index 8) for an existing doc_number."""
    try:
        row_num = await xlsx_service.find_row_by_col(SHEET_RECEIPTS, 8, doc_number)
        if row_num is not None:
            return {"row": row_num, "doc_number": doc_number}
        return None
    except Exception as e:
        log.error("find_by_doc_number error: %s", e)
        raise


# ─── Transaction (Sheet2) ─────────────────────────────────────────────


async def append_transaction(tx: Transaction, recorder_name: str) -> int:
    row = [
        tx.tx_date.isoformat(),
        tx.category,
        tx.description,
        tx.amount,
        tx.counter_party or "",
        tx.ref_doc_number or "",
        recorder_name,
    ]
    return await _append_row(SHEET_LEDGER, row)


# ─── Order (Sheet3) ───────────────────────────────────────────────────


async def append_order(order: Order, creator_name: str) -> int:
    summary = "、".join(
        f"{it.product_name} {it.qty}{it.unit}" for it in order.items[:3]
    )
    row = [
        order.order_date.isoformat(),
        order.supplier,
        summary,
        order.total_amount or "",
        order.status,
        order.tracking_number or "",
        creator_name,
    ]
    return await _append_row(SHEET_ORDERS, row)


# ─── Monthly summary (reads from xlsx) ───────────────────────────────


async def get_monthly_summary(year: int, month: int) -> dict[str, Any]:
    """Aggregate ledger rows matching year/month from local xlsx."""
    try:
        rows = await xlsx_service.read_all_rows(SHEET_LEDGER)
        prefix = f"{year}-{month:02d}"
        income = expense = payable = receivable = 0.0
        for row in rows:
            if len(row) < 4 or not str(row[0]).startswith(prefix):
                continue
            try:
                amt = float(row[3])
            except (ValueError, TypeError):
                continue
            cat = str(row[1]) if len(row) > 1 else ""
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
        rows = await xlsx_service.read_all_rows(SHEET_LEDGER)
    except Exception as e:
        log.error("get_store_monthly_data error: %s", e)
        raise

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
        except (ValueError, TypeError):
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


# ─── Dashboard reads (from xlsx) ──────────────────────────────────────


async def get_recent_receipts(n: int = 30) -> list[dict[str, Any]]:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_RECEIPTS)
        keys = ["date", "upload_time", "uploader", "doc_type", "vendor",
                "items", "amount", "tax", "doc_number", "drive_url",
                "confidence", "group", "notes"]
        recent = list(reversed(rows[-n:]))
        out = []
        for row in recent:
            padded = list(row) + [""] * (len(keys) - len(row))
            out.append(dict(zip(keys, padded)))
        return out
    except Exception as e:
        log.error("get_recent_receipts error: %s", e)
        raise


async def get_recent_orders(n: int = 30) -> list[dict[str, Any]]:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_ORDERS)
        keys = ["date", "supplier", "items", "amount", "status", "tracking", "creator"]
        recent = list(reversed(rows[-n:]))
        out = []
        for row in recent:
            padded = list(row) + [""] * (len(keys) - len(row))
            out.append(dict(zip(keys, padded)))
        return out
    except Exception as e:
        log.error("get_recent_orders error: %s", e)
        raise


# ─── Schedule / Shift (Sheet5) ───────────────────────────────────────


async def append_shift(shift: Shift) -> int:
    row = [
        shift.shift_date.isoformat(),
        shift.employee_id,
        shift.employee_name,
        shift.store,
        shift.start_time.strftime("%H:%M"),
        shift.end_time.strftime("%H:%M"),
        shift.hours,
        shift.shift_type,
        shift.status,
        shift.notes or "",
    ]
    return await _append_row(SHEET_SCHEDULE, row)


async def get_shifts_by_date(target_date: date) -> list[Shift]:
    return await get_shifts_by_date_range(target_date, target_date)


async def get_shifts_by_date_range(from_date: date, to_date: date) -> list[Shift]:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_SCHEDULE)
        shifts: list[Shift] = []
        for r in rows:
            if len(r) < 6:
                continue
            try:
                d = date.fromisoformat(str(r[0]))
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
    all_shifts = await get_shifts_by_date_range(from_date, to_date)
    return [s for s in all_shifts if s.employee_id == employee_id]


def _row_to_shift(r: list) -> Shift:
    from datetime import time as dt_time

    def _t(s: str) -> dt_time:
        h, m = str(s).split(":")
        return dt_time(int(h), int(m))

    return Shift(
        shift_date=date.fromisoformat(str(r[0])),
        employee_id=r[1] if len(r) > 1 else "",
        employee_name=r[2] if len(r) > 2 else "",
        store=r[3] if len(r) > 3 else "",
        start_time=_t(r[4]) if len(r) > 4 else __import__("datetime").time(0, 0),
        end_time=_t(r[5]) if len(r) > 5 else __import__("datetime").time(0, 0),
        shift_type=r[7] if len(r) > 7 else "早班",    # type: ignore[arg-type]
        status=r[8] if len(r) > 8 else "正常",         # type: ignore[arg-type]
        notes=r[9] if len(r) > 9 else None,
    )


# ─── Leave Request (Sheet6) ──────────────────────────────────────────


async def append_leave_request(req: LeaveRequest) -> int:
    row = [
        req.apply_time,
        req.employee_id,
        req.employee_name,
        req.leave_date.isoformat(),
        req.leave_type,
        req.reason,
        req.status,
        req.reviewer,
        req.notes,
    ]
    return await _append_row(SHEET_LEAVE, row)


async def approve_leave_request(
    employee_name: str, leave_date: date, reviewer: str
) -> bool:
    """Find a pending leave row in xlsx and update status to 核准."""
    try:
        rows = await xlsx_service.read_all_rows(SHEET_LEAVE)
        for i, r in enumerate(rows):
            if len(r) < 7:
                continue
            name_match = (str(r[2]) == employee_name)
            date_match = (str(r[3]) == leave_date.isoformat())
            pending   = (str(r[6]) == "待審")
            if name_match and date_match and pending:
                row_num = i + 2  # +1 for 0→1-based, +1 for header
                # 6=狀態(G), 7=審核者(H)
                await xlsx_service.update_cells(
                    SHEET_LEAVE, row_num, {6: "核准", 7: reviewer}
                )
                # Sync to Sheets in background
                _bg(
                    lambda rn=row_num: _gsheets_batch_update(
                        [{"range": f"{SHEET_LEAVE}!G{rn}:H{rn}",
                          "values": [["核准", reviewer]]}],
                        label=f"approve_leave:{rn}",
                    ),
                    label="approve_leave",
                )
                return True
        return False
    except Exception as e:
        log.error("approve_leave_request error: %s", e)
        raise


# ─── Vendor Master (Sheet10) ──────────────────────────────────────────


async def get_vendor(name: str) -> Optional["Vendor"]:
    from app.models.vendor import Vendor
    try:
        rows = await xlsx_service.read_all_rows(SHEET_VENDORS)
    except Exception as e:
        log.error("get_vendor error: %s", e)
        raise
    for row in rows:
        if row and str(row[_VEN_COL_NAME]) == name:
            def _get(r: list, i: int, default: str = "") -> str:
                return str(r[i]) if len(r) > i and r[i] != "" else default
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
    """Insert or update a vendor row in 廠商主檔."""
    row_data = [
        vendor.name, vendor.invoice_type, vendor.billing_cycle,
        vendor.bank_code, vendor.account_number, vendor.account_name,
        vendor.line_group_id, vendor.notes,
    ]
    rows = await xlsx_service.read_all_rows(SHEET_VENDORS)
    names = [str(r[0]) if r else "" for r in rows]
    try:
        idx = names.index(vendor.name)
        row_num = idx + 2  # +1 for 0→1-based, +1 for header
        await xlsx_service.update_cells(
            SHEET_VENDORS, row_num,
            {i: v for i, v in enumerate(row_data)},
        )
        _bg(
            lambda rn=row_num: _gsheets_batch_update(
                [{"range": f"{SHEET_VENDORS}!A{rn}:H{rn}", "values": [row_data]}],
                label=f"upsert_vendor:{vendor.name}",
            ),
            label="upsert_vendor",
        )
    except ValueError:
        await _append_row(SHEET_VENDORS, row_data)


# ─── AP Records (Sheet11) ─────────────────────────────────────────────


async def append_ap_record(ap: "APRecord") -> int:
    row = [
        ap.delivery_date, ap.vendor_name, ap.item_name,
        ap.qty, ap.unit, ap.unit_price, ap.amount,
        ap.invoice_type, ap.invoice_number, ap.billing_cycle,
        ap.status, ap.wire_date, ap.notes,
    ]
    return await _append_row(SHEET_AP, row)


async def get_pending_ap(vendor_name: str) -> list["APRecord"]:
    from app.models.vendor import APRecord
    rows = await xlsx_service.read_all_rows(SHEET_AP)
    records: list[APRecord] = []
    for row in rows:
        def _g(r: list, i: int, default: str = "") -> str:
            return str(r[i]) if len(r) > i and r[i] != "" else default
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
    rows = await xlsx_service.read_all_rows(SHEET_AP)
    updated = 0
    for i, row in enumerate(rows):
        def _g(r: list, idx: int, default: str = "") -> str:
            return str(r[idx]) if len(r) > idx and r[idx] != "" else default
        if _g(row, _AP_COL_VENDOR) == vendor_name and _g(row, _AP_COL_STATUS) == "待付款":
            sheet_row = i + 2
            await xlsx_service.update_cells(
                SHEET_AP, sheet_row,
                {_AP_COL_STATUS: "已匯款", _AP_COL_WIRE_DATE: wire_date},
            )
            _bg(
                lambda rn=sheet_row: _gsheets_batch_update(
                    [{"range": f"{SHEET_AP}!K{rn}:L{rn}",
                      "values": [["已匯款", wire_date]]}],
                    label=f"mark_ap_paid:{rn}",
                ),
                label="mark_ap_paid",
            )
            updated += 1
    return updated


# ─── E-commerce Orders (Sheet7) ───────────────────────────────────────


async def append_ecommerce_order(order: EcommerceOrder) -> int:
    row = [
        order.created_at, order.order_number, order.platform,
        order.customer_name, order.customer_phone, order.shipping_address,
        order.items_summary, order.subtotal, order.shipping_fee,
        order.total_amount, order.payment_method, order.payment_status,
        order.logistics_company, order.tracking_number, order.ship_status,
        order.notes, order.created_by,
    ]
    return await _append_row(SHEET_ECOMMERCE, row)


async def find_ecommerce_order(order_number: str) -> Optional[EcommerceOrder]:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_ECOMMERCE)
        for r in rows:
            if len(r) > 1 and str(r[1]) == order_number:
                return _row_to_ecommerce_order(r)
        return None
    except Exception as e:
        log.error("find_ecommerce_order error: %s", e)
        raise


async def update_ecommerce_order_fields(
    order_number: str, fields: dict
) -> bool:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_ECOMMERCE)
        for i, r in enumerate(rows):
            if len(r) > 1 and str(r[1]) == order_number:
                row_num = i + 2
                col_map = {
                    "payment_status": _EC_COL_PAY_STATUS,
                    "logistics_company": _EC_COL_LOGISTICS,
                    "tracking_number": _EC_COL_TRACKING,
                    "ship_status": _EC_COL_SHIP_STATUS,
                }
                updates: dict[int, Any] = {}
                for field, col_idx in col_map.items():
                    if field in fields:
                        updates[col_idx] = fields[field]

                if "notes_append" in fields:
                    current_notes = str(r[_EC_COL_NOTES]) if len(r) > _EC_COL_NOTES else ""
                    updates[_EC_COL_NOTES] = (current_notes + " " + fields["notes_append"]).strip()

                if updates:
                    await xlsx_service.update_cells(SHEET_ECOMMERCE, row_num, updates)
                    gsheets_data = [
                        {"range": f"{SHEET_ECOMMERCE}!{chr(ord('A') + col)}{row_num}",
                         "values": [[val]]}
                        for col, val in updates.items()
                    ]
                    _bg(
                        lambda d=gsheets_data: _gsheets_batch_update(
                            d, label=f"ec_order:{order_number}"
                        ),
                        label="ec_order_update",
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
    try:
        rows = await xlsx_service.read_all_rows(SHEET_ECOMMERCE)
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
    try:
        rows = await xlsx_service.read_all_rows(SHEET_ECOMMERCE)
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
        return str(r[idx]) if len(r) > idx and r[idx] != "" else ""

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
        rows = await xlsx_service.read_all_rows(SHEET_INVENTORY)
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
    now_str = datetime.now(ZoneInfo(settings.bot_timezone)).strftime("%Y-%m-%d %H:%M")
    try:
        rows = await xlsx_service.read_all_rows(SHEET_INVENTORY)
        for i, r in enumerate(rows):
            if r and str(r[0]) == name:
                row_num = i + 2
                try:
                    cur = float(r[_INV_COL_STOCK]) if len(r) > _INV_COL_STOCK and r[_INV_COL_STOCK] != "" else 0.0
                except (ValueError, TypeError):
                    cur = 0.0
                new_stock = absolute if absolute is not None else cur + delta
                await xlsx_service.update_cells(
                    SHEET_INVENTORY, row_num,
                    {_INV_COL_STOCK: new_stock, _INV_COL_UPDATED: now_str},
                )
                _bg(
                    lambda rn=row_num, ns=new_stock: _gsheets_batch_update(
                        [{"range": f"{SHEET_INVENTORY}!E{rn}", "values": [[ns]]},
                         {"range": f"{SHEET_INVENTORY}!F{rn}", "values": [[now_str]]}],
                        label=f"inv_stock:{name}",
                    ),
                    label="inv_stock_update",
                )
                item = _row_to_inventory(r)
                item.current_stock = new_stock
                item.last_updated = now_str
                return item

        # Item not found → create new row
        new_stock = absolute if absolute is not None else max(0.0, delta)
        new_row = [name, "", "", 0, new_stock, now_str, "", ""]
        await _append_row(SHEET_INVENTORY, new_row)
        return InventoryItem(name=name, current_stock=new_stock, last_updated=now_str)

    except Exception as e:
        log.error("update_inventory_stock error: %s", e)
        raise


async def update_inventory_safety_stock(name: str, level: float) -> InventoryItem:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_INVENTORY)
        for i, r in enumerate(rows):
            if r and str(r[0]) == name:
                row_num = i + 2
                await xlsx_service.update_cells(
                    SHEET_INVENTORY, row_num, {_INV_COL_SAFETY: level}
                )
                _bg(
                    lambda rn=row_num: _gsheets_batch_update(
                        [{"range": f"{SHEET_INVENTORY}!D{rn}", "values": [[level]]}],
                        label=f"inv_safety:{name}",
                    ),
                    label="inv_safety_update",
                )
                item = _row_to_inventory(r)
                item.safety_stock = level
                return item

        # New item
        now_str = datetime.now(ZoneInfo(settings.bot_timezone)).strftime("%Y-%m-%d %H:%M")
        new_row = [name, "", "", level, 0, now_str, "", ""]
        await _append_row(SHEET_INVENTORY, new_row)
        return InventoryItem(name=name, safety_stock=level)
    except Exception as e:
        log.error("update_inventory_safety_stock error: %s", e)
        raise


def _row_to_inventory(r: list) -> InventoryItem:
    def _g(i: int) -> str:
        return str(r[i]) if len(r) > i and r[i] != "" else ""

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
        m.moved_at, m.item_name, m.movement_type,
        m.quantity, m.unit, m.store,
        m.ref_order_no, m.operator, m.notes,
    ]
    return await _append_row(SHEET_MOVEMENTS, row)


async def get_stock_movements_since(since_date: str) -> list[StockMovement]:
    try:
        rows = await xlsx_service.read_all_rows(SHEET_MOVEMENTS)
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
        return str(r[i]) if len(r) > i and r[i] != "" else ""

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
