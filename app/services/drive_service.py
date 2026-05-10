"""Google Drive image archiving service.

Folder structure:
  SME-Bot-Files/
    2026/05/receipts/   ← 收據、發票
    2026/05/delivery/   ← 出貨單、送貨單

Image naming: {YYYYMMDD}_{doc_number_or_timestamp}_{doc_type}.jpg
"""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import date
from functools import lru_cache
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from app.config import settings

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]

_DOC_TYPE_FOLDER = {
    "收據": "receipts",
    "發票": "receipts",
    "出貨單": "delivery",
    "送貨單": "delivery",
    "訂購單": "receipts",
    "其他": "receipts",
}


@lru_cache(maxsize=1)
def _get_service():
    creds = service_account.Credentials.from_service_account_info(
        settings.google_service_account_info, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive():
    return _get_service()


async def _find_folder(name: str, parent_id: str) -> Optional[str]:
    """Return folder ID if it exists under parent, else None."""
    result = await asyncio.to_thread(
        lambda: _drive().files().list(
            q=f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)",
            spaces="drive",
        ).execute()
    )
    files = result.get("files", [])
    return files[0]["id"] if files else None


async def _get_or_create_folder(name: str, parent_id: str) -> str:
    fid = await _find_folder(name, parent_id)
    if fid:
        return fid
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    result = await asyncio.to_thread(
        lambda: _drive().files().create(body=meta, fields="id").execute()
    )
    return result["id"]


async def _resolve_target_folder(doc_type: str, doc_date: Optional[date]) -> str:
    """Return the Drive folder ID for a given doc_type and date."""
    target_date = doc_date or date.today()
    year = str(target_date.year)
    month = f"{target_date.month:02d}"
    subfolder = _DOC_TYPE_FOLDER.get(doc_type, "receipts")

    root_id = settings.google_drive_folder_id
    year_id = await _get_or_create_folder(year, root_id)
    month_id = await _get_or_create_folder(month, year_id)
    target_id = await _get_or_create_folder(subfolder, month_id)
    return target_id


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
    """Upload image bytes to Drive, return the webViewLink URL."""
    folder_id = await _resolve_target_folder(doc_type, doc_date)
    filename = _build_filename(doc_type, doc_number, doc_date)

    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg")
    file_meta = {"name": filename, "parents": [folder_id]}

    result = await asyncio.to_thread(
        lambda: _drive().files().create(
            body=file_meta,
            media_body=media,
            fields="id,webViewLink",
        ).execute()
    )

    file_id = result.get("id", "")
    web_link = result.get("webViewLink", "")

    # Make file readable by anyone with the link
    await asyncio.to_thread(
        lambda: _drive().permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()
    )

    log.info("uploaded %s → %s", filename, web_link)
    return web_link
