"""Quick keyword-based routing before calling Claude for intent."""
from __future__ import annotations

import re

# Logistics tracking number patterns (Taiwan carriers)
_TRACKING_RE = re.compile(
    r"\b([A-Z]{2}\d{10,12}|[A-Z]{1}\d{11}|\d{12}|\d{15})\b"
)

_ORDER_KEYWORDS = {"叫貨", "訂購", "下單", "訂", "進貨", "採購"}
_ACCOUNTING_KEYWORDS = {"收入", "支出", "付款", "收款", "應付", "應收", "記帳"}
_REPORT_COMMANDS = {"/月報", "/查帳", "/報表", "/餘額"}
_QUERY_COMMANDS = {"/查", "/訂單", "/庫存"}


def route_text(text: str) -> str:
    """Return intent category string for quick routing.

    Returns one of: 'command' | 'order' | 'accounting' | 'logistics' | 'unknown'
    """
    stripped = text.strip()

    if any(stripped.startswith(cmd) for cmd in _REPORT_COMMANDS | _QUERY_COMMANDS):
        return "command"

    if any(kw in stripped for kw in _ORDER_KEYWORDS):
        return "order"

    if any(kw in stripped for kw in _ACCOUNTING_KEYWORDS):
        return "accounting"

    if _TRACKING_RE.search(stripped):
        return "logistics"

    return "unknown"


def extract_tracking_numbers(text: str) -> list[str]:
    return _TRACKING_RE.findall(text)
