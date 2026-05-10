"""Image message processing — OCR main flow.

Flow:
  1. Download image bytes from LINE
  2. Compress to <5MB if needed (Pillow)
  3. Claude Vision OCR → Receipt model
  4. Duplicate doc number check (Sheets col I)
  5. Amount threshold alert
  6. Upload original to Google Drive
  7. Append to Google Sheets Sheet1
  8. Push confirmation message to LINE group
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import date

from app.config import settings
from app.line.reply import download_image, push_text
from app.models.receipt import Receipt

log = logging.getLogger(__name__)

_MAX_CLAUDE_BYTES = 5 * 1024 * 1024  # 5 MB


def _compress(image_bytes: bytes, quality: int = 75) -> bytes:
    """JPEG-compress image bytes with Pillow until < 5 MB."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    result = buf.getvalue()

    if len(result) > _MAX_CLAUDE_BYTES and quality > 40:
        return _compress(image_bytes, quality - 15)
    return result


def _media_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


async def _fetch_user_name(user_id: str) -> str:
    try:
        from app.line.reply import get_line_api
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id


async def process_image(
    message_id: str,
    reply_token: str,
    user_id: str,
    group_id: str,
) -> None:
    """Entry point called as a BackgroundTask from the webhook."""
    log.info("process_image start: msg=%s user=%s group=%s", message_id, user_id, group_id)

    # ── 1. Download ────────────────────────────────────────────────────
    try:
        raw_bytes = await download_image(message_id)
    except Exception as e:
        log.exception("image download failed: %s", e)
        await push_text(group_id, f"⚠️ 圖片下載失敗：{e}")
        return

    # ── 2. Compress if needed ──────────────────────────────────────────
    if len(raw_bytes) > _MAX_CLAUDE_BYTES:
        log.info("compressing image %.1f MB", len(raw_bytes) / 1e6)
        image_bytes = _compress(raw_bytes)
    else:
        image_bytes = raw_bytes

    media_type = _media_type(image_bytes)

    # ── 3. OCR ────────────────────────────────────────────────────────
    from app.services.claude_service import vision_ocr

    image_b64 = base64.standard_b64encode(image_bytes).decode()
    try:
        receipt = await vision_ocr(image_b64, media_type)
    except Exception as e:
        log.exception("OCR failed: %s", e)
        await push_text(group_id, f"⚠️ 圖片辨識失敗，請稍後再試。\n（{e}）")
        return

    receipt.uploaded_by = user_id
    receipt.group_id = group_id

    # ── 4. Low-confidence early exit ──────────────────────────────────
    if receipt.confidence == "低" and not receipt.total_amount:
        await push_text(
            group_id,
            "⚠️ 無法辨識\n"
            "圖片可能太模糊或不是商業單據。\n"
            "請重新拍攝，注意：\n"
            "• 光線充足\n"
            "• 單據鋪平不折疊\n"
            "• 鏡頭對準，避免模糊",
        )
        return

    # ── 5. Duplicate check ────────────────────────────────────────────
    from app.utils.duplicate_check import is_duplicate

    if receipt.doc_number and await is_duplicate(receipt.doc_number):
        await push_text(
            group_id,
            f"⚠️ 此單號已存在\n"
            f"單號 {receipt.doc_number} 之前已記錄過。\n"
            f"如需更新，請輸入：更新 {receipt.doc_number}",
        )
        return

    # ── 6. Amount alert ───────────────────────────────────────────────
    from app.utils.amount_validator import check_and_alert

    await check_and_alert(
        receipt.total_amount, receipt.doc_type, receipt.doc_number, group_id
    )

    # ── 7. Upload to Drive ────────────────────────────────────────────
    from app.services.drive_service import upload_image

    try:
        drive_url = await upload_image(
            raw_bytes, receipt.doc_type, receipt.doc_number, receipt.doc_date
        )
        receipt.drive_url = drive_url
    except Exception as e:
        log.warning("Drive upload failed: %s", e)
        receipt.drive_url = ""

    # ── 8. Write to Sheets ────────────────────────────────────────────
    from app.services.sheets_service import append_receipt

    uploader_name = await _fetch_user_name(user_id)
    sheet_row = 0
    try:
        sheet_row = await append_receipt(receipt, uploader_name, group_id)
    except Exception as e:
        log.error("Sheets write failed: %s", e)

    # ── 9. Reply ──────────────────────────────────────────────────────
    await push_text(group_id, _format_success(receipt, sheet_row))


def _format_success(receipt: Receipt, sheet_row: int) -> str:
    lines = ["✅ 單據已歸檔"]
    lines.append(f"📄 類型：{receipt.doc_type}")
    if receipt.doc_date:
        lines.append(f"📅 日期：{receipt.doc_date}")
    if receipt.vendor_name:
        lines.append(f"🏢 廠商：{receipt.vendor_name}")
    if receipt.customer_name and not receipt.vendor_name:
        lines.append(f"👤 客戶：{receipt.customer_name}")
    if receipt.total_amount is not None:
        lines.append(f"💰 金額：NT${receipt.total_amount:,.0f}")
    if receipt.doc_number:
        lines.append(f"🔢 單號：{receipt.doc_number}")
    if sheet_row:
        lines.append(f"📊 已寫入：收據記錄表 第 {sheet_row} 列")
    if receipt.drive_url:
        lines.append("🖼 圖片：已存入 Drive")
    if receipt.confidence != "高":
        lines.append(f"⚠️ 信心度：{receipt.confidence}（請人工核對）")
    return "\n".join(lines)
