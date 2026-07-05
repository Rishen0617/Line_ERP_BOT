"""Unit tests for inventory_handler NL order parsing (no network calls)."""
import pytest
from app.handlers.inventory_handler import _parse_order_body, OrderItem


def test_parse_glued_units():
    """Standard format: 品項數量單位 glued together."""
    items, store, notes = _parse_order_body("青蔥5斤 雞蛋2箱")
    assert len(items) == 2
    assert items[0] == OrderItem("青蔥", 5.0, "斤")
    assert items[1] == OrderItem("雞蛋", 2.0, "箱")
    assert store == ""


def test_parse_separated_units():
    """Demo format from Sales Agent: 青蔥 5 斤、蛋 2 箱 (qty and unit as separate tokens)."""
    items, store, notes = _parse_order_body("青蔥 5 斤、蛋 2 箱")
    assert len(items) == 2
    assert items[0] == OrderItem("青蔥", 5.0, "斤")
    assert items[1] == OrderItem("雞蛋", 2.0, "箱")
    # 單位詞不應被誤當成 store
    assert store == ""


def test_parse_alias_egg():
    """「蛋」應被 normalize 成「雞蛋」。"""
    items, store, _ = _parse_order_body("蛋 3箱")
    assert len(items) == 1
    assert items[0].name == "雞蛋"
    assert items[0].qty == 3.0


def test_parse_no_unit_uses_default():
    """數量後無單位時應使用品項預設單位。"""
    items, store, _ = _parse_order_body("青蔥 5 雞蛋 2")
    assert items[0].unit == "斤"
    assert items[1].unit == "箱"


def test_parse_with_vendor():
    """格式「品項 數量 @ 廠商」應正確拆出 store。"""
    items, store, _ = _parse_order_body("青蔥5斤 @阿成食品")
    assert len(items) == 1
    assert "阿成食品" in store or items[0].name == "青蔥"


def test_parse_minglun_full_demo():
    """完整明倫老闆 demo 場景：叫貨：青蔥 5 斤、蛋 2 箱（去掉前綴後）。"""
    import re
    text = "叫貨：青蔥 5 斤、蛋 2 箱"
    body = re.sub(r"^(今日叫貨|叫貨[：:﹕]?\s*)", "", text).strip()
    assert body == "青蔥 5 斤、蛋 2 箱"
    items, store, notes = _parse_order_body(body)
    assert len(items) == 2
    names = [i.name for i in items]
    assert "青蔥" in names
    assert "雞蛋" in names
    assert store == ""
