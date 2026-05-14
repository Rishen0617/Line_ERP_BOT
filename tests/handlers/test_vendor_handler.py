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
