"""FastAPI entry point.

Endpoints
---------
POST /webhook          LINE Webhook 主入口
GET  /health           健康檢查（Railway 用）
GET  /report/monthly   月報摘要（內部管理）
POST /admin/test-ocr   測試 OCR（傳圖片 base64 回傳解析結果）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
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


@app.get("/api/dashboard/data")
async def dashboard_data(months: int = 6) -> dict[str, Any]:
    """Aggregate data for dashboard: monthly summaries + recent rows."""
    from datetime import date
    from app.services.sheets_service import (
        get_monthly_summary, get_recent_receipts, get_recent_orders
    )
    today = date.today()
    monthly = []
    for i in range(months - 1, -1, -1):
        offset = today.month - 1 - i
        y = today.year + offset // 12
        m = offset % 12 + 1
        # proper month/year rollback
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        try:
            s = await get_monthly_summary(y, m)
        except Exception:
            s = {"year": y, "month": m, "income": 0, "expense": 0,
                 "payable": 0, "receivable": 0, "net": 0}
        monthly.append(s)

    try:
        receipts = await get_recent_receipts(30)
    except Exception:
        receipts = []
    try:
        orders = await get_recent_orders(30)
    except Exception:
        orders = []

    return {"ok": True, "monthly": monthly, "receipts": receipts, "orders": orders}
