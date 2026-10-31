"""users 表（认证基线 + 注册基础信息：性别/年龄；身高统一由 body_basic_records 记录）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 男 / 女，注册时填写
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 年龄
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
