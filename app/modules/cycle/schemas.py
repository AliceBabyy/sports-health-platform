"""生理周期 schemas。"""
from datetime import date

from pydantic import BaseModel, Field, model_validator


class SettingsIn(BaseModel):
    cycle_length: int = Field(ge=10, le=60)
    period_length: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def validate_lengths(self):
        if self.period_length >= self.cycle_length:
            raise ValueError("经期长度须小于周期长度")
        return self


class PeriodIn(BaseModel):
    start_date: date
    end_date: date | None = None
    # 记录月经时可一并更新设置（MC-02）
    cycle_length: int | None = Field(default=None, ge=10, le=60)
    period_length: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        if self.cycle_length and self.period_length and self.period_length >= self.cycle_length:
            raise ValueError("经期长度须小于周期长度")
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
