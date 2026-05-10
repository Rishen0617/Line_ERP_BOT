from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel


class OrderItem(BaseModel):
    product_name: str
    qty: float
    unit: str


class Order(BaseModel):
    order_date: date
    supplier: str
    items: List[OrderItem]
    total_amount: Optional[float] = None
    status: Literal["待確認", "已確認", "出貨中", "已到貨"] = "待確認"
    tracking_number: Optional[str] = None
    created_by: str = ""
    group_id: str = ""
