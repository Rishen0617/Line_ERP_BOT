# Vendor Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete vendor procurement → AP billing → wire transfer cycle for 明倫餐飲集團, covering vendor master registration, per-delivery AP tracking, cycle-based AP query, and wire transfer confirmation with LINE group push.

**Architecture:** Four new modules layer on top of the existing Sheets/LINE infrastructure — a Vendor model, two new Google Sheet tabs (廠商主檔 + 應付帳款), a vendor service for business logic, and a vendor handler for LINE commands. The existing `/到貨` command is extended to record unit price and auto-create an AP record.

**Tech Stack:** Python 3.11, Pydantic v2, Google Sheets API v4 (via existing `sheets_service.py` helpers), LINE Bot SDK v3 (via existing `push_text`), FastAPI (existing app)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/models/vendor.py` | `Vendor` and `APRecord` Pydantic models |
| Create | `app/services/vendor_service.py` | Business logic: get/upsert vendor, aggregate AP, record wire transfer |
| Create | `app/handlers/vendor_handler.py` | LINE command handlers: `/廠商設定`, `/應付`, `/匯款` |
| Modify | `app/services/sheets_service.py` | Add Sheet10/11 constants + vendor/AP CRUD functions |
| Modify | `app/handlers/inventory_handler.py` | Extend `_cmd_arrival` to accept unit price, write AP row |
| Modify | `app/line/router.py` | Add vendor commands to routing sets |
| Modify | `app/handlers/text_handler.py` | Route `vendor` intent → vendor_handler |

**New Google Sheet tabs (must be created manually in the Spreadsheet before running):**
- `Sheet10 = 廠商主檔` columns: A=廠商名 B=發票類型 C=請款週期 D=銀行代碼 E=帳號 F=戶名 G=LINE群組ID H=備註
- `Sheet11 = 應付帳款` columns: A=到貨日期 B=廠商名 C=品項 D=數量 E=單位 F=單價 G=金額 H=發票類型 I=單號 J=請款週期 K=狀態 L=匯款日期 M=備註

---

## Task 1: Vendor and AP Models

**Files:**
- Create: `app/models/vendor.py`
- Test: `tests/models/test_vendor.py`

- [ ] **Step 1: Create `tests/models/` directory and write failing tests**

```python
# tests/models/test_vendor.py
import pytest
from app.models.vendor import Vendor, APRecord, InvoiceType, BillingCycle


def test_vendor_defaults():
    v = Vendor(name="大成農城")
    assert v.invoice_type == "農產品收據"
    assert v.billing_cycle == "週結"
    assert v.line_group_id == ""


def test_vendor_full():
    v = Vendor(
        name="大成農城",
        invoice_type="農產品收據",
        billing_cycle="週結",
        bank_code="004",
        account_number="123456789",
        account_name="大成農業股份有限公司",
        line_group_id="C1234567890abcdef",
        notes="每週五請款",
    )
    assert v.bank_code == "004"
    assert v.account_name == "大成農業股份有限公司"


def test_ap_record_amount():
    ap = APRecord(
        delivery_date="2026-05-06",
        vendor_name="大成農城",
        item_name="雞蛋",
        qty=30.0,
        unit="箱",
        unit_price=600.0,
    )
    assert ap.amount == 18000.0
    assert ap.status == "待付款"


def test_ap_record_amount_override():
    # Allow manual amount override (e.g. flat-fee invoice)
    ap = APRecord(
        delivery_date="2026-05-06",
        vendor_name="大成農城",
        item_name="清潔費",
        qty=1.0,
        unit="次",
        unit_price=0.0,
        amount=5000.0,
    )
    assert ap.amount == 5000.0


def test_invoice_type_literals():
    with pytest.raises(Exception):
        Vendor(name="X", invoice_type="不存在的類型")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd F:\AI\line-sme-bot
pytest tests/models/test_vendor.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.models.vendor'`

- [ ] **Step 3: Create `app/models/vendor.py`**

```python
"""Vendor master and accounts-payable record models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, model_validator

InvoiceType = Literal["統一發票", "農產品收據", "一般收據"]
BillingCycle = Literal["週結", "月結"]
APStatus = Literal["待付款", "已匯款"]


class Vendor(BaseModel):
    name: str                                    # 廠商名（主鍵）
    invoice_type: InvoiceType = "農產品收據"      # 發票類型
    billing_cycle: BillingCycle = "週結"          # 請款週期
    bank_code: str = ""                          # 銀行代碼，e.g. "004"
    account_number: str = ""                     # 帳號
    account_name: str = ""                       # 戶名
    line_group_id: str = ""                      # 廠商 LINE 群組 ID
    notes: str = ""                              # 備註


class APRecord(BaseModel):
    delivery_date: str                           # YYYY-MM-DD
    vendor_name: str
    item_name: str
    qty: float
    unit: str = ""
    unit_price: float = 0.0
    amount: float = 0.0                          # qty * unit_price, or manual
    invoice_type: str = ""                       # copied from vendor master
    invoice_number: str = ""                     # 發票/收據號碼
    billing_cycle: str = ""                      # copied from vendor master
    status: APStatus = "待付款"
    wire_date: str = ""                          # 匯款日期 YYYY-MM-DD
    notes: str = ""

    @model_validator(mode="after")
    def _calc_amount(self) -> "APRecord":
        if self.amount == 0.0 and self.unit_price > 0:
            self.amount = round(self.qty * self.unit_price, 2)
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/models/test_vendor.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/vendor.py tests/models/test_vendor.py
git commit -m "feat: add Vendor and APRecord models"
```

---

## Task 2: Sheets Service — Vendor Master and AP Tab

**Files:**
- Modify: `app/services/sheets_service.py`
- Test: `tests/services/test_vendor_sheets.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/services/test_vendor_sheets.py
"""Unit tests for vendor/AP sheets functions using mocked Sheets API."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.vendor import Vendor, APRecord


@pytest.fixture
def mock_sheets(monkeypatch):
    """Patch _sheets() to return a mock that records calls."""
    mock_svc = MagicMock()
    monkeypatch.setattr("app.services.sheets_service._sheets", lambda: mock_svc)
    return mock_svc


@pytest.mark.asyncio
async def test_upsert_vendor_new(mock_sheets):
    """upsert_vendor appends a row when vendor does not exist."""
    # Simulate empty sheet (no existing rows)
    mock_sheets.values().get().execute.return_value = {"values": [["廠商名"]]}
    mock_sheets.values().append().execute.return_value = {"updates": {"updatedRows": 1}}

    from app.services.sheets_service import upsert_vendor
    vendor = Vendor(name="大成農城", bank_code="004", account_number="123456789",
                    account_name="大成農業", billing_cycle="週結")
    await upsert_vendor(vendor)

    assert mock_sheets.values().append.called


@pytest.mark.asyncio
async def test_get_vendor_found(mock_sheets):
    """get_vendor returns Vendor when name matches col A."""
    mock_sheets.values().get().execute.return_value = {
        "values": [
            ["廠商名", "發票類型", "請款週期", "銀行代碼", "帳號", "戶名", "LINE群組ID", "備註"],
            ["大成農城", "農產品收據", "週結", "004", "123456789", "大成農業", "Cabc", ""],
        ]
    }
    from app.services.sheets_service import get_vendor
    v = await get_vendor("大成農城")
    assert v is not None
    assert v.billing_cycle == "週結"
    assert v.account_number == "123456789"


@pytest.mark.asyncio
async def test_get_vendor_not_found(mock_sheets):
    mock_sheets.values().get().execute.return_value = {"values": [["廠商名"]]}
    from app.services.sheets_service import get_vendor
    v = await get_vendor("不存在")
    assert v is None


@pytest.mark.asyncio
async def test_append_ap_record(mock_sheets):
    mock_sheets.values().append().execute.return_value = {"updates": {"updatedRows": 1}}
    from app.services.sheets_service import append_ap_record
    ap = APRecord(delivery_date="2026-05-06", vendor_name="大成農城",
                  item_name="雞蛋", qty=30.0, unit="箱", unit_price=600.0)
    row_num = await append_ap_record(ap)
    assert mock_sheets.values().append.called


@pytest.mark.asyncio
async def test_get_pending_ap(mock_sheets):
    """get_pending_ap returns only 待付款 rows for the given vendor."""
    mock_sheets.values().get().execute.return_value = {
        "values": [
            ["到貨日期","廠商名","品項","數量","單位","單價","金額","發票類型","單號","請款週期","狀態","匯款日期","備註"],
            ["2026-05-06","大成農城","雞蛋","30","箱","600","18000","農產品收據","","週結","待付款","",""],
            ["2026-05-09","大成農城","雞蛋","25","箱","600","15000","農產品收據","","週結","待付款","",""],
            ["2026-05-01","其他廠商","豬肉","10","斤","200","2000","一般收據","","月結","待付款","",""],
        ]
    }
    from app.services.sheets_service import get_pending_ap
    records = await get_pending_ap("大成農城")
    assert len(records) == 2
    assert all(r.vendor_name == "大成農城" for r in records)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/services/test_vendor_sheets.py -v
```
Expected: `ImportError` for `upsert_vendor`, `get_vendor`, etc.

- [ ] **Step 3: Add constants and functions to `app/services/sheets_service.py`**

At the top of the file, after `SHEET_MOVEMENTS = "庫存異動"`, add:

```python
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
```

Then add the following four functions before the last `_append_row` function:

```python
# ─── Vendor Master (Sheet10) ──────────────────────────────────────────

async def get_vendor(name: str) -> Optional["Vendor"]:
    """Return Vendor from 廠商主檔 by name, or None if not found."""
    from app.models.vendor import Vendor
    result = await asyncio.to_thread(
        lambda: _sheets().values().get(
            spreadsheetId=settings.google_spreadsheet_id,
            range=f"{SHEET_VENDORS}!A:H",
        ).execute()
    )
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
    from app.models.vendor import APRecord as _AP
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
    rows = result.get("values", [])
    updated = 0
    for i, row in enumerate(rows):
        def _g(r, idx, default=""):
            return r[idx] if len(r) > idx else default
        if _g(row, _AP_COL_VENDOR) == vendor_name and _g(row, _AP_COL_STATUS) == "待付款":
            sheet_row = i + 1
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_vendor_sheets.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/sheets_service.py tests/services/test_vendor_sheets.py
git commit -m "feat: add vendor master and AP sheets functions"
```

---

## Task 3: Vendor Service (Business Logic)

**Files:**
- Create: `app/services/vendor_service.py`
- Test: `tests/services/test_vendor_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/services/test_vendor_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.models.vendor import Vendor, APRecord


@pytest.fixture
def sample_vendor():
    return Vendor(
        name="大成農城",
        invoice_type="農產品收據",
        billing_cycle="週結",
        bank_code="004",
        account_number="123456789",
        account_name="大成農業股份有限公司",
        line_group_id="Cabc123",
    )


@pytest.fixture
def sample_ap_records():
    return [
        APRecord(delivery_date="2026-05-06", vendor_name="大成農城",
                 item_name="雞蛋", qty=30.0, unit="箱", unit_price=600.0),
        APRecord(delivery_date="2026-05-09", vendor_name="大成農城",
                 item_name="雞蛋", qty=25.0, unit="箱", unit_price=600.0),
    ]


@pytest.mark.asyncio
async def test_format_ap_summary(sample_vendor, sample_ap_records):
    from app.services.vendor_service import format_ap_summary
    msg = format_ap_summary(sample_vendor, sample_ap_records)
    assert "大成農城" in msg
    assert "NT$18,000" in msg
    assert "NT$15,000" in msg
    assert "NT$33,000" in msg  # total
    assert "004-123456789" in msg  # bank info


@pytest.mark.asyncio
async def test_format_ap_summary_empty(sample_vendor):
    from app.services.vendor_service import format_ap_summary
    msg = format_ap_summary(sample_vendor, [])
    assert "無待付款" in msg


@pytest.mark.asyncio
async def test_build_wire_transfer_push(sample_vendor, sample_ap_records):
    from app.services.vendor_service import build_wire_transfer_push
    msg = build_wire_transfer_push(sample_vendor, sample_ap_records, "2026-05-15")
    assert "明倫餐飲集團" in msg
    assert "NT$33,000" in msg
    assert "2026-05-15" in msg
    assert "雞蛋" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/services/test_vendor_service.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.vendor_service'`

- [ ] **Step 3: Create `app/services/vendor_service.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_vendor_service.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/vendor_service.py tests/services/test_vendor_service.py
git commit -m "feat: add vendor service with AP summary and wire transfer push formatting"
```

---

## Task 4: Vendor Command Handler

**Files:**
- Create: `app/handlers/vendor_handler.py`
- Test: `tests/handlers/test_vendor_handler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/handlers/test_vendor_handler.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_cmd_vendor_setup_too_few_args():
    """Returns usage help if fewer than 5 args given."""
    with patch("app.handlers.vendor_handler.push_text", new_callable=AsyncMock) as mock_push:
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command("/廠商設定 大成農城", "U001", "G001")
        text = mock_push.call_args[0][1]
        assert "格式" in text


@pytest.mark.asyncio
async def test_cmd_vendor_setup_invalid_invoice_type():
    with patch("app.handlers.vendor_handler.push_text", new_callable=AsyncMock) as mock_push:
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command(
            "/廠商設定 大成農城 不存在類型 週結 004-123456789 大成農業", "U001", "G001"
        )
        text = mock_push.call_args[0][1]
        assert "發票類型" in text


@pytest.mark.asyncio
async def test_cmd_vendor_setup_success():
    with patch("app.handlers.vendor_handler.push_text", new_callable=AsyncMock) as mock_push, \
         patch("app.services.sheets_service.upsert_vendor", new_callable=AsyncMock):
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command(
            "/廠商設定 大成農城 農產品收據 週結 004-123456789 大成農業",
            "U001", "G001"
        )
        text = mock_push.call_args[0][1]
        assert "大成農城" in text
        assert "✅" in text


@pytest.mark.asyncio
async def test_cmd_ap_vendor_not_found():
    with patch("app.handlers.vendor_handler.push_text", new_callable=AsyncMock) as mock_push, \
         patch("app.services.sheets_service.get_vendor", return_value=None, new_callable=AsyncMock):
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command("/應付 大成農城", "U001", "G001")
        text = mock_push.call_args[0][1]
        assert "找不到廠商" in text


@pytest.mark.asyncio
async def test_cmd_wire_missing_date():
    with patch("app.handlers.vendor_handler.push_text", new_callable=AsyncMock) as mock_push:
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command("/匯款 大成農城", "U001", "G001")
        text = mock_push.call_args[0][1]
        assert "格式" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/handlers/test_vendor_handler.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.handlers.vendor_handler'`

- [ ] **Step 3: Create `app/handlers/vendor_handler.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/handlers/test_vendor_handler.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/handlers/vendor_handler.py tests/handlers/test_vendor_handler.py
git commit -m "feat: add vendor command handler for /廠商設定, /應付, /匯款"
```

---

## Task 5: Extend `/到貨` with Unit Price and Auto-Create AP Record

**Files:**
- Modify: `app/handlers/inventory_handler.py` — `_cmd_arrival` accepts `unit_price`
- Test: `tests/handlers/test_inventory_arrival.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/handlers/test_inventory_arrival.py
"""Tests for /到貨 command with unit price and AP record creation."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def mock_fetch_name():
    with patch("app.handlers.inventory_handler._fetch_name",
               new_callable=AsyncMock, return_value="測試員工"):
        yield


@pytest.mark.asyncio
async def test_arrival_usage_hint():
    with patch("app.handlers.inventory_handler.push_text", new_callable=AsyncMock) as mock_push:
        from app.handlers.inventory_handler import handle_inventory_command
        await handle_inventory_command("/到貨 青蔥", "U001", "G001")
        text = mock_push.call_args[0][1]
        assert "格式" in text


@pytest.mark.asyncio
async def test_arrival_no_unit_price_no_ap():
    """When no unit price given, arrival succeeds but no AP row created."""
    mock_item = MagicMock()
    mock_item.__str__ = lambda self: "青蔥 10斤"
    with patch("app.handlers.inventory_handler.push_text", new_callable=AsyncMock) as mock_push, \
         patch("app.services.inventory_service.confirm_arrival",
               new_callable=AsyncMock, return_value=mock_item), \
         patch("app.services.inventory_service.format_item", return_value="青蔥 10斤"), \
         patch("app.services.sheets_service.append_ap_record",
               new_callable=AsyncMock) as mock_ap:
        from app.handlers.inventory_handler import handle_inventory_command
        await handle_inventory_command("/到貨 青蔥 10斤 福星店", "U001", "G001")
        assert mock_ap.not_called


@pytest.mark.asyncio
async def test_arrival_with_unit_price_creates_ap():
    """When unit price given and vendor found, AP record is written."""
    from app.models.vendor import Vendor
    mock_item = MagicMock()
    vendor = Vendor(name="大成農城", billing_cycle="週結", invoice_type="農產品收據")
    with patch("app.handlers.inventory_handler.push_text", new_callable=AsyncMock) as mock_push, \
         patch("app.services.inventory_service.confirm_arrival",
               new_callable=AsyncMock, return_value=mock_item), \
         patch("app.services.inventory_service.format_item", return_value="青蔥 10斤"), \
         patch("app.services.sheets_service.get_vendor",
               new_callable=AsyncMock, return_value=vendor), \
         patch("app.services.sheets_service.append_ap_record",
               new_callable=AsyncMock, return_value=5) as mock_ap:
        from app.handlers.inventory_handler import handle_inventory_command
        # Format: /到貨 品項 數量 單價 [廠商名] [店別]
        await handle_inventory_command("/到貨 青蔥 10斤 120 大成農城 福星店", "U001", "G001")
        assert mock_ap.called
        ap_record = mock_ap.call_args[0][0]
        assert ap_record.item_name == "青蔥"
        assert ap_record.qty == 10.0
        assert ap_record.unit_price == 120.0
        assert ap_record.amount == 1200.0
        assert ap_record.vendor_name == "大成農城"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/handlers/test_inventory_arrival.py -v
```
Expected: `test_arrival_with_unit_price_creates_ap` FAIL (AP not yet created)

- [ ] **Step 3: Update `_cmd_arrival` in `app/handlers/inventory_handler.py`**

Replace the existing `_cmd_arrival` function (lines 96–117) with:

```python
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
                unit=unit or item.unit if hasattr(item, "unit") else unit,
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/handlers/test_inventory_arrival.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/handlers/inventory_handler.py tests/handlers/test_inventory_arrival.py
git commit -m "feat: extend /到貨 to accept unit price and auto-create AP record"
```

---

## Task 6: Router and Text Handler Wiring

**Files:**
- Modify: `app/line/router.py`
- Modify: `app/handlers/text_handler.py`
- Test: `tests/test_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_router.py (add to existing file or create new)
from app.line.router import route_text


def test_route_vendor_setup():
    assert route_text("/廠商設定 大成農城 農產品收據 週結 004-123456789 大成農業") == "vendor"


def test_route_ap_query():
    assert route_text("/應付 大成農城") == "vendor"


def test_route_wire_transfer():
    assert route_text("/匯款 大成農城 2026-05-15") == "vendor"


def test_route_existing_commands_unchanged():
    assert route_text("/叫貨 青蔥 5斤") == "inventory"
    assert route_text("/到貨 青蔥 5斤") == "inventory"
    assert route_text("/月報") == "command"
```

- [ ] **Step 2: Run tests to verify vendor routes fail**

```
pytest tests/test_router.py -v
```
Expected: `test_route_vendor_setup`, `test_route_ap_query`, `test_route_wire_transfer` FAIL with `assert 'unknown' == 'vendor'`

- [ ] **Step 3: Update `app/line/router.py`**

After `_INVENTORY_COMMANDS = {...}`, add:

```python
_VENDOR_COMMANDS = {
    "/廠商設定", "/應付", "/匯款",
}
```

Inside `route_text()`, after the `_INVENTORY_COMMANDS` check, add:

```python
    if any(stripped.startswith(cmd) for cmd in _VENDOR_COMMANDS):
        return "vendor"
```

- [ ] **Step 4: Update `app/handlers/text_handler.py`**

After the `elif intent == "inventory":` block, add:

```python
    elif intent == "vendor":
        from app.handlers.vendor_handler import handle_vendor_command
        await handle_vendor_command(text, user_id, group_id)
```

- [ ] **Step 5: Run all tests**

```
pytest tests/test_router.py tests/handlers/test_vendor_handler.py -v
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/line/router.py app/handlers/text_handler.py
git commit -m "feat: wire vendor commands into router and text handler"
```

---

## Task 7: Help Text and Quick Reply Menu Updates

**Files:**
- Modify: `app/handlers/command_handler.py` — add 廠商功能 to `/help 電商` or new `/help 廠商` section
- Modify: `app/handlers/text_handler.py` — add vendor quick reply buttons

- [ ] **Step 1: Update `/help 電商` block in `app/handlers/command_handler.py`**

In the `elif cat in ("電商",):` block, append vendor commands after the last line before `+ footer`:

```python
            f"\n🏭 廠商管理\n"
            f"  {prefix}/廠商設定 大成農城 農產品收據 週結 004-帳號 戶名\n"
            f"  {prefix}/應付 大成農城     查詢待付款明細\n"
            f"  {prefix}/匯款 大成農城 2026-05-15  記錄匯款＋通知廠商"
```

- [ ] **Step 2: Add vendor buttons to the Quick Reply menu in `_handle_slash_menu`**

In `app/handlers/text_handler.py`, in the `inventory_ecommerce` list, append after `("🚚 出貨…", ...)`:

```python
        ("🏭 廠商設定…", f"{p}/廠商設定 "),
        ("📋 應付…",    f"{p}/應付 "),
        ("💸 匯款…",    f"{p}/匯款 "),
```

- [ ] **Step 3: Restart the server and smoke-test via LINE**

```
cd F:\AI\line-sme-bot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Send these messages in LINE and verify responses:
1. `/廠商設定 大成農城 農產品收據 週結 004-123456789 大成農業` → ✅ 廠商已設定
2. `/到貨 雞蛋 30箱 600 大成農城 逢甲店` → ✅ 到貨已確認 + 📋 應付帳款已記錄
3. `/應付 大成農城` → shows per-delivery table + 合計 + 匯款帳號
4. `/匯款 大成農城 2026-05-15` → ✅ 已記錄匯款 + (if group set) push to vendor group

- [ ] **Step 4: Create the two Google Sheet tabs manually**

In the Google Spreadsheet, add two new tabs:
- Tab name: `廠商主檔` — add header row: `廠商名	發票類型	請款週期	銀行代碼	帳號	戶名	LINE群組ID	備註`
- Tab name: `應付帳款` — add header row: `到貨日期	廠商名	品項	數量	單位	單價	金額	發票類型	單號	請款週期	狀態	匯款日期	備註`

- [ ] **Step 5: Commit final wiring**

```bash
git add app/handlers/command_handler.py app/handlers/text_handler.py
git commit -m "feat: add vendor commands to help text and quick reply menu"
```

---

## Self-Review

### Spec Coverage Check

| Requirement | Task |
|-------------|------|
| 廠商主檔（名稱/發票類型/請款週期/帳號/LINE群組） | Task 1 + Task 2 + Task 4 |
| 到貨照片 OCR → 歸檔 | Existing image handler (out of scope for this plan) |
| `/到貨` 含單價 → 自動建應付帳款 | Task 5 |
| 請款週期加總 `/應付` | Task 3 + Task 4 |
| `/匯款` 記錄 + 廠商群組推播 | Task 4 |
| 路由更新 | Task 6 |
| Help/Quick Reply 更新 | Task 7 |

### Known Omissions (out of scope / not confirmed)

- **OCR → AP auto-create on image upload**: The full image→vendor→AP path requires the operator to be in a "vendor context". This is complex UX and was not confirmed in the flowchart. The simpler `/到貨 品項 數量 單價 廠商名` text command covers the confirmed use case.
- **Wire transfer photo upload → AP**: LINE does not support attaching photos to push messages. The push notification confirms the transfer; the photo is stored separately via the normal image handler.
- **Invoice number capture (統一發票花號)**: Not wired into `/到貨` for now. Operator can add via notes field.
