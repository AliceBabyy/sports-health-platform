"""认证 schemas：登录表单模型。"""
from pydantic import BaseModel


class LoginForm(BaseModel):
    username: str
    password: str
