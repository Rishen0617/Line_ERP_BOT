"""Normalize various date string formats to ISO YYYY-MM-DD."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2})\b")),
    ("%Y/%m/%d", re.compile(r"\b(\d{4}/\d{1,2}/\d{1,2})\b")),
    ("%d/%m/%Y", re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")),
    ("%m/%d/%Y", re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")),
    # ROC calendar: 民國 115/05/10 → 2026-05-10
    ("ROC", re.compile(r"民?國?\s*(\d{2,3})[年/](\d{1,2})[月/](\d{1,2})日?")),
]


def parse_date(text: str) -> Optional[date]:
    """Try to extract a date from arbitrary text. Returns None if not found."""
    for fmt, pattern in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        if fmt == "ROC":
            try:
                year = int(m.group(1)) + 1911
                month = int(m.group(2))
                day = int(m.group(3))
                return date(year, month, day)
            except ValueError:
                continue
        try:
            return datetime.strptime(m.group(1), fmt).date()
        except ValueError:
            continue
    return None


def today_iso() -> str:
    return date.today().isoformat()
