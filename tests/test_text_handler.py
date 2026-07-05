"""Unit tests for text routing and parsing (no network calls)."""
import pytest
from app.line.router import route_text, extract_tracking_numbers


def test_route_command_monthly():
    assert route_text("/月報") == "command"


def test_route_command_query():
    assert route_text("/查 AB-12345678") == "command"


def test_route_order_vendor():
    # 一般訂購（廠商訂單），走 order 意圖
    # 注意：含"叫貨"且後接商品的 NL 格式會走 inventory，此測試改為純訂購語境
    assert route_text("訂購 阿成食品 礦泉水 50箱") == "order"


def test_route_inventory_nl_colon():
    # 叫貨：前綴 → inventory（NL 進貨流程）
    assert route_text("叫貨：青蔥 5斤 雞蛋 2箱") == "inventory"


def test_route_inventory_nl_today():
    # 今日叫貨 → inventory
    assert route_text("今日叫貨 青蔥5斤 蛋2箱") == "inventory"


def test_route_inventory_nl_space_unit():
    # "叫貨：品項 數量 單位" 分開寫也走 inventory
    assert route_text("叫貨：青蔥 5 斤、蛋 2 箱") == "inventory"


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
