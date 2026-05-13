"""E-commerce order data models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


Platform = Literal["LINE購物", "蝦皮", "91App", "官網", "電話", "其他"]
PaymentMethod = Literal["信用卡", "ATM轉帳", "貨到付款", "LINE Pay", "街口支付", "其他"]
PaymentStatus = Literal["未付款", "已付款", "退款中", "已退款"]
ShipStatus = Literal["待出貨", "出貨中", "已送達", "退貨中", "已退貨", "取消"]


class EcommerceOrder(BaseModel):
    created_at: str                        # ISO datetime
    order_number: str                      # 訂單編號（平台單號或自訂）
    platform: Platform = "其他"
    customer_name: str = ""
    customer_phone: str = ""
    shipping_address: str = ""
    items_summary: str = ""                # 品項摘要
    subtotal: float = 0.0                  # 商品金額
    shipping_fee: float = 0.0             # 運費
    total_amount: float = 0.0             # 總金額
    payment_method: PaymentMethod = "其他"
    payment_status: PaymentStatus = "未付款"
    logistics_company: str = ""            # 黑貓 / 7-11 / 郵局
    tracking_number: str = ""             # 物流單號
    ship_status: ShipStatus = "待出貨"
    notes: str = ""
    created_by: str = ""                   # LINE user ID

    @field_validator("total_amount", mode="before")
    @classmethod
    def calc_total(cls, v: float) -> float:
        return v  # caller responsible for setting correct total
