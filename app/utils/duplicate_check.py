"""Check Google Sheets column I for existing doc numbers before writing."""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


async def is_duplicate(doc_number: Optional[str]) -> bool:
    """Return True if doc_number already exists in Sheet1 column I.

    Returns False if doc_number is None/empty (no check needed).
    """
    if not doc_number:
        return False

    from app.services.sheets_service import find_by_doc_number
    try:
        existing = await find_by_doc_number(doc_number)
        return existing is not None
    except Exception as e:
        log.warning("duplicate_check failed for %s: %s", doc_number, e)
        return False
