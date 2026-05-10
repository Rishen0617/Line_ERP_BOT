"""Claude API service — Vision OCR and text intent parsing."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic

from app.config import settings
from app.models.receipt import Receipt, ReceiptItem

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    log.warning("prompt file not found: %s", path)
    return ""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if Claude wraps JSON in them."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) >= 2 else text
    return text


# ─── Vision OCR ───────────────────────────────────────────────────────

async def vision_ocr(
    image_b64: str,
    media_type: str = "image/jpeg",
    source_hint: str = "",
) -> Receipt:
    """Call Claude Vision to extract structured fields from a document image.

    Returns a Receipt model. On failure, returns a Receipt with confidence='低'.
    """
    prompt_text = _load_prompt("ocr_receipt.txt")
    if source_hint:
        prompt_text = f"[圖片來源提示：{source_hint}]\n\n{prompt_text}"

    try:
        msg = _client().messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
        )
        raw = _strip_fences(msg.content[0].text)
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("OCR JSON parse error: %s", e)
        return Receipt(doc_type="其他", confidence="低", ocr_raw=None)
    except Exception as e:
        log.exception("Claude vision_ocr failed")
        return Receipt(doc_type="其他", confidence="低", ocr_raw=str(e))

    raw_str = json.dumps(data, ensure_ascii=False)
    items = [
        ReceiptItem(
            name=str(it.get("name") or ""),
            qty=_float(it.get("qty")),
            unit=it.get("unit"),
            unit_price=_float(it.get("unit_price")),
            subtotal=_float(it.get("subtotal")),
        )
        for it in (data.get("items") or [])
    ]

    from app.utils.date_parser import parse_date

    doc_date = None
    if date_str := data.get("doc_date"):
        doc_date = parse_date(str(date_str))

    confidence = str(data.get("confidence") or "低")
    # normalise Chinese label returned by Claude
    if "高" in confidence:
        confidence = "高"
    elif "中" in confidence:
        confidence = "中"
    else:
        confidence = "低"

    return Receipt(
        doc_type=str(data.get("doc_type") or "其他"),
        doc_number=data.get("doc_number") or None,
        doc_date=doc_date,
        vendor_name=data.get("vendor_name") or None,
        customer_name=data.get("customer_name") or None,
        items=items,
        total_amount=_float(data.get("total_amount")),
        tax_amount=_float(data.get("tax_amount")),
        notes=data.get("notes") or None,
        confidence=confidence,
        ocr_raw=raw_str,
    )


# ─── Text intent parsing ──────────────────────────────────────────────

async def parse_intent(text: str, context: dict | None = None) -> dict:
    """Ask Claude to classify a text message intent.

    Returns a dict with at least: { "intent": str, ... }
    Intents: accounting | order | query | unknown
    """
    prompt_text = _load_prompt("text_intent.txt")
    user_msg = f"{prompt_text}\n\n用戶訊息：{text}"
    if context:
        user_msg += f"\n\n上下文：{json.dumps(context, ensure_ascii=False)}"

    try:
        msg = _client().messages.create(
            model=settings.claude_model,
            max_tokens=512,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = _strip_fences(msg.content[0].text)
        return json.loads(raw)
    except Exception as e:
        log.warning("parse_intent failed: %s", e)
        return {"intent": "unknown", "error": str(e)}


# ─── helpers ──────────────────────────────────────────────────────────

def _float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
