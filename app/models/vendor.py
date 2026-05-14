"""Vendor master and accounts-payable record models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, model_validator

InvoiceType = Literal["統一發票", "農產品收據", "一般收據"]
BillingCycle = Literal["週結", "月結"]
APStatus = Literal["待付款", "已匯款"]


class Vendor(BaseModel):
    name: str                                    # 廠商名（主鍵）
    invoice_type: InvoiceType = "農產品收據"      # 發票類型
    billing_cycle: BillingCycle = "週結"          # 請款週期
    bank_code: str = ""                          # 銀行代碼，e.g. "004"
    account_number: str = ""                     # 帳號
    account_name: str = ""                       # 戶名
    line_group_id: str = ""                      # 廠商 LINE 群組 ID
    notes: str = ""                              # 備註


class APRecord(BaseModel):
    delivery_date: str                           # YYYY-MM-DD
    vendor_name: str
    item_name: str
    qty: float
    unit: str = ""
    unit_price: float = 0.0
    amount: float = 0.0                          # qty * unit_price, or manual
    invoice_type: str = ""                       # copied from vendor master
    invoice_number: str = ""                     # 發票/收據號碼
    billing_cycle: str = ""                      # copied from vendor master
    status: APStatus = "待付款"
    wire_date: str = ""                          # 匯款日期 YYYY-MM-DD
    notes: str = ""

    @model_validator(mode="after")
    def _calc_amount(self) -> APRecord:
        if self.amount == 0.0 and self.unit_price > 0:
            self.amount = round(self.qty * self.unit_price, 2)
        return self
