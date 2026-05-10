"""Unit tests for text routing and parsing (no network calls)."""
import pytest
from app.line.router import route_text, extract_tracking_numbers


def test_route_command_monthly():
    assert route_text("/月報") == "command"


def test_route_command_query():
    assert route_text("/查 AB-12345678") == "command"


def test_route_order():
    assert route_text("叫貨 阿成食品 礦泉水 50箱") == "order"


def test_route_accounting():
    assert route_text("支出 3200 王老吉 進貨礦泉水") == "accounting"


def test_route_logistics_tcat():
    assert route_text("包裹單號 AB1234567890") == "logistics"


def test_route_logistics_711():
    assert route_text("貨到了嗎 123456789012") == "logistics"


def test_route_unknown():
    assert route_text("今天天氣真好") == "unknown"


def test_extract_tracking_numbers():
    text = "幫我查一下 AB1234567890 和 123456789012 的包裹"
    nums = extract_tracking_numbers(text)
    assert "AB1234567890" in nums
    assert "123456789012" in nums
