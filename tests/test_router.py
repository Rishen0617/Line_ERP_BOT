"""Tests for the router module."""
from app.line.router import route_text


def test_route_vendor_setup():
    assert route_text("/廠商設定 大成農城 農產品收據 週結 004-123456789 大成農業") == "vendor"


def test_route_ap_query():
    assert route_text("/應付 大成農城") == "vendor"


def test_route_wire_transfer():
    assert route_text("/匯款 大成農城 2026-05-15") == "vendor"


def test_route_existing_commands_unchanged():
    assert route_text("/叫貨 青蔥 5斤") == "inventory"
    assert route_text("/到貨 青蔥 5斤") == "inventory"
    assert route_text("/月報") == "command"
