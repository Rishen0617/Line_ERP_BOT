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
