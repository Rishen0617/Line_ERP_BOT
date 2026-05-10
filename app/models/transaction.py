from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


class Transaction(BaseModel):
    tx_date: date
    category: Literal["收入", "支出", "應付", "應收"]
    description: str
    amount: float
    counter_party: Optional[str] = None
    ref_doc_number: Optional[str] = None
    recorded_by: str = ""
    group_id: str = ""
