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
        assert not mock_ap.called


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
        # Format: /到貨 品項 數量 單價 廠商名 [店別]
        await handle_inventory_command("/到貨 青蔥 10斤 120 大成農城 福星店", "U001", "G001")
        assert mock_ap.called
        ap_record = mock_ap.call_args[0][0]
        assert ap_record.item_name == "青蔥"
        assert ap_record.qty == 10.0
        assert ap_record.unit_price == 120.0
        assert ap_record.amount == 1200.0
        assert ap_record.vendor_name == "大成農城"
