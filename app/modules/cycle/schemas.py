"""生理周期 schemas。"""
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.core.constants import (
    OVULATION_OFFSET,
    REFERENCE_CYCLE_MAX,
    REFERENCE_CYCLE_MIN,
    REFERENCE_PERIOD_MAX,
    REFERENCE_PERIOD_MIN,
)


class SettingsIn(BaseModel):
    """参考值：仅用于当前段、预测段与补推段，不参与真实段推算。"""

    cycle_length: int = Field(ge=REFERENCE_CYCLE_MIN, le=REFERENCE_CYCLE_MAX)
    period_length: int = Field(ge=REFERENCE_PERIOD_MIN, le=REFERENCE_PERIOD_MAX)

    @model_validator(mode="after")
    def validate_lengths(self):
        # 保证按参考值推算时排卵日不落进经期
        if self.period_length + OVULATION_OFFSET + 1 > self.cycle_length:
            raise ValueError("参考经期过长：需满足 经期天数 + 15 ≤ 参考周期")
        return self


class PeriodIn(BaseModel):
    """记录月经：只收起止日期，两个长度由记录自动派生。"""

    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class PeriodUpdateIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class PainIn(BaseModel):
    pain_level: int = Field(ge=0, le=3)
