"""健康档案（health_profile）：一个专项 skill 生成的一套问题，按“套 + 题”行式存储。

- 每行是一套专项问题中的一道题；同一套由 set_id 关联。
- ``skill_key`` 指向生成这套题的档案专项 skill（profile_goal / profile_diet ...）。
- ``aspect`` 只能是该 skill 允许的固定方面，见 app/modules/profile/aspect_skills.py。
- 同一用户同一套内的 local_key（q1~q10）唯一；不同套之间互不影响。
- answer 为空表示题目已生成但尚未回答，页面仍展示为空输入框。
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.profile.aspects import ASPECT_KEYS
from database import Base

_ASPECT_CHECK = "aspect IN (" + ", ".join(f"'{key}'" for key in sorted(ASPECT_KEYS)) + ")"
_MAX_LENGTH_CHECK = "max_length BETWEEN 50 AND 255"


class HealthProfile(Base):
    """健康档案：一套专项问题对应多行，一行一道题。"""

    __tablename__ = "health_profile"
    __table_args__ = (
        UniqueConstraint("user_id", "set_id", "local_key", name="uq_health_profile_user_set_local"),
        Index(
            "idx_health_profile_user_skill",
            "user_id",
            "skill_key",
            "set_generated_at",
        ),
        CheckConstraint(_ASPECT_CHECK, name="ck_health_profile_aspect"),
        CheckConstraint(_MAX_LENGTH_CHECK, name="ck_health_profile_max_length"),
        {"comment": "健康档案（按专项 skill 分套，一行一道题的开放式答案）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户主键 + FK，删除账号时级联删除",
    )
    set_id: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="一套专项问题的 id；同一用户内唯一标识一套"
    )
    skill_key: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        comment="生成这套题的档案专项 skill key，见 app/modules/profile/aspect_skills.py",
    )
    aspect: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="档案方面，必须是该 skill 允许的 aspect，见 app/modules/profile/aspect_skills.py",
    )
    local_key: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="套内题号 q1~q10"
    )
    label: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default="", comment="题目标题"
    )
    hint: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default="", comment="填写提示"
    )
    placeholder: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default="", comment="占位文案"
    )
    max_length: Mapped[int] = mapped_column(
        Integer, nullable=False, default=200, server_default="200", comment="答案最大字数（50~255）"
    )
    answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="用户文本答案；为空表示题目已生成但未回答"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="同一套内的展示顺序"
    )
    set_generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="这套问题的生成时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间（ORM onupdate 自动刷新）",
    )
