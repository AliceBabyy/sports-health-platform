"""健康/运动档案（health_profile）：一个用户多条档案记录（行式存储）。

- 每行是一条档案记录，主键 id；user_id 普通外键 + 索引，实现一用户多行。
- aspect 只能来自 app/modules/profile/aspects.py 的固定模板。
- item_key 在用户内唯一：固定题使用 questions.py 的 key，定制题使用
  probe_<set_id>_<qN>。
- answer 为空的行用于保存“已生成但尚未回答”的定制问题；固定题空答案不落行。
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
_SOURCE_CHECK = "source IN ('fixed', 'probe', 'user')"


class HealthProfile(Base):
    """健康/运动档案：一个用户多行，每行一个 aspect 下的一条记录。"""

    __tablename__ = "health_profile"
    __table_args__ = (
        UniqueConstraint("user_id", "item_key", name="uq_health_profile_user_item"),
        Index("idx_health_profile_user_aspect", "user_id", "aspect"),
        CheckConstraint(_ASPECT_CHECK, name="ck_health_profile_aspect"),
        CheckConstraint(_SOURCE_CHECK, name="ck_health_profile_source"),
        {"comment": "健康/运动档案（一用户多行，按 aspect 记录开放式答案）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户主键 + FK，删除账号时级联删除",
    )
    aspect: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="档案方面，固定模板见 app/modules/profile/aspects.py",
    )
    item_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="用户内稳定题目 key：固定题见 questions.py，定制题为 probe_<set_id>_<qN>",
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
        Integer, nullable=False, default=200, server_default="200", comment="答案最大字数"
    )
    answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="用户文本答案；为空表示题目已生成但未回答"
    )
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="fixed",
        server_default="fixed",
        comment="来源：fixed 固定问卷 / probe 角色定制 / user 用户自建",
    )
    set_id: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="定制问题所属套 id；固定题为空"
    )
    persona_key: Mapped[str | None] = mapped_column(
        String(48), nullable=True, comment="生成定制问题的角色 key"
    )
    set_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="定制问题套生成时间"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="同套/同方面的展示顺序"
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
