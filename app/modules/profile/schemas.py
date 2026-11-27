"""个人信息 schemas：基本资料更新 / 修改密码 / 健康档案逐题保存请求体。"""
from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdateIn(BaseModel):
    display_name: str
    gender: str = ""
    age: str = ""


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class AccountDeleteIn(BaseModel):
    mode: str
    current_password: str


class HealthProfileItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: str = Field(min_length=1, max_length=16, description="档案套 id")
    local_key: str = Field(pattern=r"^q[1-6]$", description="套内题号 q1~q6")
    answer: str = Field(default="", max_length=255, description="文本答案，可空")


class HealthProfileIn(BaseModel):
    """页面保存：按 (set_id, local_key) 逐题更新已存储档案，空串表示清空该题。"""

    model_config = ConfigDict(extra="forbid")

    items: list[HealthProfileItemIn] = Field(default_factory=list, max_length=200)
