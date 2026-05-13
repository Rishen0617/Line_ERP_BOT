"""Inventory data models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


MovementType = Literal["叫貨", "到貨", "消耗", "盤點", "報廢"]


class InventoryItem(BaseModel):
    name: str                          # 品項名稱（主鍵）
    spec: str = ""                     # 規格（如 500g/箱）
    unit: str = "個"                   # 單位
    safety_stock: float = 0.0          # 安全庫存量
    current_stock: float = 0.0         # 目前庫存量
    last_updated: str = ""             # 最後更新時間
    category: str = ""                 # 分類（蔬菜/肉類/醬料/包材…）
    supplier: str = ""                 # 主要供應商

    @property
    def is_low(self) -> bool:
        return self.safety_stock > 0 and self.current_stock <= self.safety_stock

    @property
    def stock_days(self) -> float | None:
        """Placeholder; filled by service after computing avg consumption."""
        return None


class StockMovement(BaseModel):
    moved_at: str                      # ISO datetime
    item_name: str
    movement_type: MovementType
    quantity: float                    # positive = in, negative = out
    unit: str = ""
    store: str = ""                    # 店別
    ref_order_no: str = ""             # 關聯叫貨單號
    operator: str = ""                 # 操作者（LINE display name）
    notes: str = ""
