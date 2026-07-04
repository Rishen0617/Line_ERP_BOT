"""Data models for the scheduling system."""
from __future__ import annotations

from datetime import date, time
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


ShiftType = Literal["早班", "午班", "中班", "晚班", "大夜班", "全天班"]
ShiftStatus = Literal["正常", "請假", "代班", "缺工"]
LeaveType = Literal["特休", "事假", "病假", "婚假", "喪假", "補休", "其他"]
LeaveStatus = Literal["待審", "核准", "拒絕"]


class Shift(BaseModel):
    shift_date: date
    employee_id: str          # LINE user ID
    employee_name: str
    store: str                # 店別（福星店/信義店/中央工廠…）
    start_time: time
    end_time: time
    hours: float = 0.0        # calculated on creation
    shift_type: ShiftType = "早班"
    status: ShiftStatus = "正常"
    notes: Optional[str] = None

    @model_validator(mode="after")
    def calc_hours(self) -> "Shift":
        start_mins = self.start_time.hour * 60 + self.start_time.minute
        end_mins = self.end_time.hour * 60 + self.end_time.minute
        if end_mins <= start_mins:
            end_mins += 24 * 60   # overnight shift
        self.hours = round((end_mins - start_mins) / 60, 2)
        return self


class LeaveRequest(BaseModel):
    apply_time: str           # ISO datetime string
    employee_id: str
    employee_name: str
    leave_date: date
    leave_type: LeaveType = "事假"
    reason: str = ""
    status: LeaveStatus = "待審"
    reviewer: str = ""
    notes: str = ""
