"""Unit tests for OCR-related utilities (no live API calls)."""
import pytest
from app.utils.date_parser import parse_date
from app.models.receipt import Receipt, ReceiptItem


def test_parse_date_iso():
    assert str(parse_date("2026-05-10")) == "2026-05-10"


def test_parse_date_slash():
    assert str(parse_date("2026/5/10")) == "2026-05-10"


def test_parse_date_roc():
    # 民國115年05月10日 → 2026-05-10
    d = parse_date("民國115年05月10日")
    assert d is not None
    assert d.year == 2026


def test_parse_date_none():
    assert parse_date("沒有日期的文字") is None


def test_receipt_items_summary_empty():
    r = Receipt(doc_type="收據")
    assert r.items_summary() == ""


def test_receipt_items_summary():
    r = Receipt(
        doc_type="收據",
        items=[
            ReceiptItem(name="礦泉水"),
            ReceiptItem(name="茶葉蛋"),
            ReceiptItem(name="便當"),
            ReceiptItem(name="飲料"),  # should not appear (max 3)
        ],
    )
    assert r.items_summary() == "礦泉水、茶葉蛋、便當"


def test_receipt_confidence_normalised():
    r = Receipt(doc_type="收據", confidence="超高")
    assert r.confidence == "低"  # invalid → default to 低
