"""个人信息 schemas：基本资料更新 / 修改密码 / 健康档案保存请求体。

age 以字符串接收，复用注册口径的解析校验（空串 → None，1~120 整数），
与 GET/POST /register 的错误文案保持一致。
"""
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


class HealthProfileIn(BaseModel):
    """健康/运动档案保存：只接受 `answers`（题目 key → 文本）。

    未知 key、超长答案由 service 校验并返回 400；未出现的 key 保持原值，
    显式传空串表示清空该题（便于逐题修改）。
    """

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str] = Field(default_factory=dict)
