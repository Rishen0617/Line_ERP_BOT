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
