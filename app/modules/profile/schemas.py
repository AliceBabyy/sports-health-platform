"""个人信息 schemas：基本资料更新 / 修改密码请求体。

age 以字符串接收，复用注册口径的解析校验（空串 → None，1~120 整数），
与 GET/POST /register 的错误文案保持一致。
"""
from pydantic import BaseModel


class ProfileUpdateIn(BaseModel):
    display_name: str
    gender: str = ""
    age: str = ""


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str
