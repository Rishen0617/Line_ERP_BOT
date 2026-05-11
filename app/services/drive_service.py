"""Local file storage service (replaces Google Drive).

Images are saved to:
  storage/
    2026/05/receipts/   ← 收據、發票
    2026/05/delivery/   ← 出貨單、送貨單

Served as static files at /storage/... and accessible via PUBLIC_BASE_URL.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)

_DOC_TYPE_FOLDER = {
    "收據": "receipts",
    "發票": "receipts",
    "出貨單": "delivery",
    "送貨單": "delivery",
    "訂購單": "receipts",
    "其他": "receipts",
}


def _resolve_target_dir(doc_type: str, doc_date: Optional[date]) -> Path:
    target_date = doc_date or date.today()
    year = str(target_date.year)
    month = f"{target_date.month:02d}"
    subfolder = _DOC_TYPE_FOLDER.get(doc_type, "receipts")
    base = Path(settings.storage_path) / year / month / subfolder
    base.mkdir(parents=True, exist_ok=True)
    return base


def _build_filename(
    doc_type: str,
    doc_number: Optional[str],
    doc_date: Optional[date],
) -> str:
    target_date = doc_date or date.today()
    date_str = target_date.strftime("%Y%m%d")
    label = doc_number or target_date.strftime("%H%M%S")
    safe_label = label.replace("/", "-").replace(" ", "_")
    return f"{date_str}_{safe_label}_{doc_type}.jpg"


async def upload_image(
    image_bytes: bytes,
    doc_type: str,
    doc_number: Optional[str] = None,
    doc_date: Optional[date] = None,
) -> str:
    """Save image bytes to local storage, return a public URL."""
    target_dir = _resolve_target_dir(doc_type, doc_date)
    filename = _build_filename(doc_type, doc_number, doc_date)
    file_path = target_dir / filename

    file_path.write_bytes(image_bytes)
    log.info("saved %s", file_path)

    # Build relative URL path: storage/2026/05/receipts/filename.jpg
    target_date = doc_date or date.today()
    year = str(target_date.year)
    month = f"{target_date.month:02d}"
    subfolder = _DOC_TYPE_FOLDER.get(doc_type, "receipts")
    rel = f"storage/{year}/{month}/{subfolder}/{filename}"

    base = settings.public_base_url.rstrip("/")
    return f"{base}/{rel}"
