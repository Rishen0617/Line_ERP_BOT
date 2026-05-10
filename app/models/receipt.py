from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, field_validator


class ReceiptItem(BaseModel):
    name: str
    qty: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    subtotal: Optional[float] = None


class Receipt(BaseModel):
    doc_type: str                          # 收據|發票|出貨單|送貨單|訂購單|其他
    doc_number: Optional[str] = None
    doc_date: Optional[date] = None
    vendor_name: Optional[str] = None
    customer_name: Optional[str] = None
    items: List[ReceiptItem] = []
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    drive_url: Optional[str] = None
    uploaded_by: str = ""
    group_id: str = ""
    confidence: str = "低"                 # 高|中|低
    ocr_raw: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: str) -> str:
        if v not in ("高", "中", "低"):
            return "低"
        return v

    def items_summary(self, max_items: int = 3) -> str:
        """Return first N item names joined by comma."""
        names = [it.name for it in self.items[:max_items] if it.name]
        return "、".join(names) if names else ""
