"""Quick keyword-based routing before calling Claude for intent."""
from __future__ import annotations

import re

# Logistics tracking number patterns (Taiwan carriers)
_TRACKING_RE = re.compile(
    r"\b([A-Z]{2}\d{10,12}|[A-Z]{1}\d{11}|\d{12}|\d{15})\b"
)

# Natural-language 叫貨 patterns (e.g. "叫貨：...", "今日叫貨 ...", "叫貨 ...")
_ORDER_NL_RE = re.compile(r"^(今日叫貨|叫貨[：:﹕]?\s*\S)")

_ORDER_KEYWORDS = {"叫貨", "訂購", "下單", "訂", "進貨", "採購"}
_ACCOUNTING_KEYWORDS = {"收入", "支出", "付款", "收款", "應付", "應收", "記帳"}
_REPORT_COMMANDS = {"/月報", "/查帳", "/報表", "/餘額"}
_QUERY_COMMANDS = {"/查", "/訂單", "/庫存"}
_HELP_COMMANDS = {"/help", "/說明", "/指令"}
_MYID_COMMANDS = {"/myid", "/我的id", "/我的ID"}
_SCHEDULE_COMMANDS = {
    "/查班表", "/我的工時", "/今日班表", "/本週班表",
    "/缺工", "/新增班", "/核假",
}
_LEAVE_KEYWORDS = {"請假"}
_ADMIN_COMMANDS = {"/晨報"}
_ECOMMERCE_COMMANDS = {
    "/新增訂單", "/訂單", "/確認付款", "/出貨",
    "/退款", "/取消訂單", "/未付款", "/未出貨", "/電商日報",
}
_INVENTORY_COMMANDS = {
    "/叫貨", "/到貨", "/消耗", "/盤點",
    "/安全庫存", "/庫存", "/低庫存", "/採購預測",
}
_VENDOR_COMMANDS = {
    "/廠商設定", "/應付", "/匯款",
}


def route_text(text: str) -> str:
    """Return intent category string for quick routing.

    Returns one of:
      'slash_menu' | 'command' | 'order' | 'accounting' | 'logistics' | 'schedule' | 'unknown'
    """
    stripped = text.strip()

    # Bare "/" → show command picker
    if stripped == "/":
        return "slash_menu"

    if any(stripped.startswith(cmd) for cmd in _HELP_COMMANDS):
        return "help"

    if any(stripped.startswith(cmd) for cmd in _MYID_COMMANDS):
        return "myid"

    if any(stripped.startswith(cmd) for cmd in _ADMIN_COMMANDS):
        return "admin"

    if any(stripped.startswith(cmd) for cmd in _ECOMMERCE_COMMANDS):
        return "ecommerce"

    if any(stripped.startswith(cmd) for cmd in _INVENTORY_COMMANDS):
        return "inventory"

    # Natural-language 叫貨 (e.g. "叫貨：青蔥 5斤", "今日叫貨 青蔥5斤 蛋2箱")
    if _ORDER_NL_RE.match(stripped):
        return "inventory"

    if any(stripped.startswith(cmd) for cmd in _VENDOR_COMMANDS):
        return "vendor"

    if any(stripped.startswith(cmd) for cmd in _SCHEDULE_COMMANDS):
        return "schedule"

    if any(stripped.startswith(kw) for kw in _LEAVE_KEYWORDS):
        return "schedule"

    if any(stripped.startswith(cmd) for cmd in _REPORT_COMMANDS | _QUERY_COMMANDS):
        return "command"

    # Accounting keywords take priority — "支出 3200 ... 進貨" is bookkeeping, not an order
    if any(kw in stripped for kw in _ACCOUNTING_KEYWORDS):
        return "accounting"

    if any(kw in stripped for kw in _ORDER_KEYWORDS):
        return "order"

    if _TRACKING_RE.search(stripped):
        return "logistics"

    return "unknown"


def extract_tracking_numbers(text: str) -> list[str]:
    return _TRACKING_RE.findall(text)
