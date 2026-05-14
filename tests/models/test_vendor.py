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
