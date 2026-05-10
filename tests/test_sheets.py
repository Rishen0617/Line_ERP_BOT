"""Smoke tests for Sheets models (no live Google API calls)."""
import pytest
from datetime import date
from app.models.receipt import Receipt, ReceiptItem
from app.models.transaction import Transaction
from app.models.order import Order, OrderItem


def test_transaction_model():
    tx = Transaction(
        tx_date=date.today(),
        category="支出",
        description="進貨礦泉水",
        amount=3200.0,
        counter_party="王老吉食品",
        recorded_by="U123",
        group_id="G456",
    )
    assert tx.amount == 3200.0
    assert tx.category == "支出"


def test_order_model():
    order = Order(
        order_date=date.today(),
        supplier="阿成食品",
        items=[OrderItem(product_name="礦泉水", qty=50, unit="箱")],
        created_by="U123",
        group_id="G456",
    )
    assert order.status == "待確認"
    assert len(order.items) == 1


def test_receipt_full():
    r = Receipt(
        doc_type="發票",
        doc_number="AB-12345678",
        vendor_name="全聯實業",
        total_amount=12500.0,
        confidence="高",
        uploaded_by="U123",
        group_id="G456",
    )
    assert r.total_amount == 12500.0
    assert r.confidence == "高"
