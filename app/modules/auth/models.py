"""users 表（认证基线 + 注册基础信息：性别/年龄；身高统一由 body_basic_records 记录）。"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('启用', '停用')", name="ck_users_status"), {"comment": "用户账号（认证 + 注册基础信息）"})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录名，唯一（注册：3~32 字符）")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希（注册：密码 ≥6 位）")
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="展示昵称（注册必填）")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别：男 / 女（注册下拉，可选）")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="年龄（注册校验 1~120 整数，可选）")
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="启用", server_default="启用", comment="启用状态：启用 / 停用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")
