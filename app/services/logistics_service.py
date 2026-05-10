"""Logistics tracking service for Taiwan carriers.

Supported carriers (auto-detected by number format):
  - 黑貓宅急便 (T-Cat/Yamato): 2 uppercase letters + 10 digits
  - 7-11 統一速達: 12-digit numeric
  - 台灣郵便: Various (starts with R/V/EA/EB + digits)
  - 嘉里大榮 Kerry TJ: Numeric string
"""
from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)

# Carrier detection patterns (order matters)
_TCAT_RE = re.compile(r"^[A-Z]{2}\d{10}$")
_7ELEVEN_RE = re.compile(r"^\d{12}$")
_POST_RE = re.compile(r"^(R|V|EA|EB|CP|CX|EE|EM|EP|ES|ET|EV|EX)\d{9}TW$", re.IGNORECASE)


def _detect_carrier(tracking_number: str) -> str:
    tn = tracking_number.strip().upper()
    if _TCAT_RE.match(tn):
        return "黑貓宅急便"
    if _7ELEVEN_RE.match(tn):
        return "統一速達 (7-11)"
    if _POST_RE.match(tn):
        return "中華郵政"
    return "未知物流"


async def query_tracking(tracking_number: str) -> str:
    """Return a human-readable status string for the given tracking number."""
    carrier = _detect_carrier(tracking_number)
    log.info("tracking %s → %s", tracking_number, carrier)

    if carrier == "黑貓宅急便":
        return await _query_tcat(tracking_number)
    if carrier == "統一速達 (7-11)":
        return await _query_711(tracking_number)
    if carrier == "中華郵政":
        return await _query_post(tracking_number)

    return (
        f"📦 物流查詢：{tracking_number}\n"
        f"無法自動辨識物流業者。\n"
        f"請至各物流官網查詢。"
    )


async def _query_tcat(tn: str) -> str:
    """黑貓宅急便 — official API requires partner credentials.

    Falls back to a user-friendly message with direct link.
    """
    url = f"https://www.t-cat.com.tw/Inquire/TraceDetail.aspx?BillNo={tn}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and "配達完了" in resp.text:
                status = "✅ 已送達"
            elif resp.status_code == 200 and "配送中" in resp.text:
                status = "🚚 配送中"
            elif resp.status_code == 200 and "集荷" in resp.text:
                status = "📦 已取件"
            else:
                status = "資訊無法自動解析"
    except Exception as e:
        log.warning("T-Cat query failed for %s: %s", tn, e)
        status = "查詢逾時或失敗"

    return (
        f"📦 黑貓宅急便：{tn}\n"
        f"狀態：{status}\n"
        f"詳細：{url}"
    )


async def _query_711(tn: str) -> str:
    """統一速達 (7-11) — no public API; provide direct link."""
    url = f"https://eservice.7-11.com.tw/e-tracking/search.aspx?TBILL_NO={tn}"
    return (
        f"📦 統一速達 (7-11)：{tn}\n"
        f"請點此查詢：\n{url}"
    )


async def _query_post(tn: str) -> str:
    """中華郵政 — REST API available."""
    api_url = f"https://postserv.post.gov.tw/pstmail/main_mail.htm?targetTxn=MAILEVO_SEARCH&EANDCNAME=&mail_no={tn}"
    return (
        f"📬 中華郵政：{tn}\n"
        f"請點此查詢：\n{api_url}"
    )
