"""FastAPI entry point.

Endpoints
---------
POST /webhook                   LINE Webhook 主入口
GET  /health                    健康檢查（Railway 用）
GET  /report/monthly            月報摘要（內部管理）
POST /admin/test-ocr            測試 OCR（傳圖片 base64 回傳解析結果）
POST /api/morning-report/send   觸發晨報（Railway Cron 用，需 Bearer token）
GET  /api/morning-report/preview 預覽晨報內容（不發送）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.line.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("sme-bot")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

STORAGE_DIR = Path(settings.storage_path)
STORAGE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="LINE 中小企業智慧助理", version="1.0.0")
app.include_router(webhook_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "model": settings.claude_model}


class TestOcrRequest(BaseModel):
    image_b64: str
    media_type: str = "image/jpeg"
    source_hint: str = ""


@app.post("/admin/test-ocr")
async def test_ocr(body: TestOcrRequest) -> dict[str, Any]:
    """Upload a base64 image and return the OCR result (for debugging)."""
    from app.services.claude_service import vision_ocr
    try:
        receipt = await vision_ocr(body.image_b64, body.media_type, body.source_hint)
        return {"ok": True, "result": receipt.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/monthly")
async def monthly_report(year: int, month: int) -> dict[str, Any]:
    """Return monthly summary from Google Sheets."""
    from app.services.sheets_service import get_monthly_summary
    try:
        summary = await get_monthly_summary(year, month)
        return {"ok": True, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


_dashboard_cache: dict[str, Any] = {}
_dashboard_cache_time: float = 0.0
_CACHE_TTL = 60.0  # seconds


@app.get("/api/dashboard/data")
async def dashboard_data(months: int = 6, bust: bool = False) -> dict[str, Any]:
    """Aggregate data for dashboard: financial + inventory + ecommerce + schedule.

    Results are cached for 60 s to keep the dashboard snappy.
    Pass ?bust=true to force a fresh fetch.
    """
    import asyncio
    import time
    from datetime import date
    from app.services.sheets_service import (
        get_monthly_summary, get_recent_receipts, get_recent_orders,
        get_all_inventory_items, get_ecommerce_orders_by_status,
        get_shifts_by_date, get_shifts_by_date_range,
        get_store_monthly_data,
    )

    global _dashboard_cache, _dashboard_cache_time
    cache_key = str(months)
    now = time.monotonic()
    if not bust and _dashboard_cache.get(cache_key) and now - _dashboard_cache_time < _CACHE_TTL:
        cached = dict(_dashboard_cache[cache_key])
        cached["cached"] = True
        return cached
    from app.services.schedule_service import week_range

    today = date.today()

    # ── Monthly summaries ────────────────────────────────────────────
    monthly = []
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        try:
            s = await get_monthly_summary(y, m)
        except Exception:
            s = {"year": y, "month": m, "income": 0, "expense": 0,
                 "payable": 0, "receivable": 0, "net": 0}
        monthly.append(s)

    # ── Sequential fetch (httplib2 is not thread-safe; avoid concurrent to_thread) ──
    async def safe(coro, default):
        try:
            return await coro
        except Exception as e:
            log.error("dashboard safe() caught: %s: %s", type(e).__name__, e)
            return default

    monday, sunday = week_range(today)

    receipts      = await safe(get_recent_receipts(30), [])
    proc_orders   = await safe(get_recent_orders(30), [])
    inventory     = await safe(get_all_inventory_items(), [])
    ec_unpaid     = await safe(get_ecommerce_orders_by_status(payment_status="未付款"), [])
    ec_unshipped  = await safe(get_ecommerce_orders_by_status(ship_status="待出貨"), [])
    today_shifts  = await safe(get_shifts_by_date(today), [])
    week_shifts   = await safe(get_shifts_by_date_range(monday, sunday), [])
    store_monthly = await safe(get_store_monthly_data(months), [])

    # Serialize inventory items
    inv_data = [
        {
            "name": it.name, "unit": it.unit,
            "current": it.current_stock, "safety": it.safety_stock,
            "is_low": it.is_low, "category": it.category,
            "supplier": it.supplier,
        }
        for it in inventory
    ]

    # Serialize ecommerce orders
    def ec_to_dict(o):
        return {
            "created_at": o.created_at, "order_number": o.order_number,
            "platform": o.platform, "customer": o.customer_name,
            "items": o.items_summary, "total": o.total_amount,
            "payment_status": o.payment_status, "ship_status": o.ship_status,
            "tracking": o.tracking_number,
        }

    # Serialize shifts
    def shift_to_dict(s):
        return {
            "date": s.shift_date.isoformat(),
            "name": s.employee_name, "store": s.store,
            "start": s.start_time.strftime("%H:%M"),
            "end": s.end_time.strftime("%H:%M"),
            "hours": s.hours, "type": s.shift_type, "status": s.status,
        }

    result = {
        "ok": True,
        "cached": False,
        "monthly": monthly,
        "store_monthly": store_monthly,
        "receipts": receipts,
        "orders": proc_orders,
        "inventory": inv_data,
        "ecommerce_unpaid": [ec_to_dict(o) for o in ec_unpaid],
        "ecommerce_unshipped": [ec_to_dict(o) for o in ec_unshipped],
        "today_shifts": [shift_to_dict(s) for s in today_shifts],
        "week_shifts": [shift_to_dict(s) for s in week_shifts],
    }
    _dashboard_cache[cache_key] = result
    _dashboard_cache_time = time.monotonic()
    return result


# ─── Morning report endpoints ─────────────────────────────────────────

def _verify_report_token(authorization: str | None) -> None:
    """Raise 403 if the Bearer token doesn't match MORNING_REPORT_SECRET."""
    secret = settings.morning_report_secret
    if not secret:
        return   # no secret configured → open access (dev mode)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != secret:
        raise HTTPException(status_code=403, detail="Invalid token")


@app.post("/api/morning-report/send")
async def morning_report_send(
    authorization: str | None = Header(default=None),
    date_str: str | None = None,
) -> dict[str, Any]:
    """Trigger morning report push to ADMIN_LINE_USER_ID.

    Called by Railway Cron:
      Method: POST
      URL: https://<your-app>/api/morning-report/send
      Header: Authorization: Bearer <MORNING_REPORT_SECRET>

    Optional query param ?date_str=YYYY-MM-DD to send report for a specific date.
    """
    _verify_report_token(authorization)
    from datetime import date
    from app.services.morning_report_service import send_morning_report

    ref: date | None = None
    if date_str:
        try:
            ref = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_str must be YYYY-MM-DD")

    ok = await send_morning_report(ref)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send report (check ADMIN_LINE_USER_ID)")
    return {"ok": True, "message": "morning report sent"}


@app.get("/api/morning-report/preview")
async def morning_report_preview(
    authorization: str | None = Header(default=None),
    date_str: str | None = None,
) -> dict[str, Any]:
    """Return the morning report text without sending it — useful for testing."""
    _verify_report_token(authorization)
    from datetime import date
    from app.services.morning_report_service import build_report

    ref: date | None = None
    if date_str:
        try:
            ref = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_str must be YYYY-MM-DD")

    report = await build_report(ref)
    return {"ok": True, "report": report}
