"""健康/运动档案（health_profile）：用户 1:1 的开放式问答档案。

只存最新一份，不做版本历史：档案不是审计对象，随时可改、可清空。
answers 的题目 key 由 app/modules/profile/questions.py 定义，
本表不存题目文案，改题目文案不影响已存答案。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class HealthProfile(Base):
    """健康/运动档案：一个用户一行。"""

    __tablename__ = "health_profile"
    __table_args__ = ({"comment": "健康/运动档案（1:1 用户，开放式问答答案）"},)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        comment="用户主键 + FK，删除账号时级联删除",
    )
    answers: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="题目 key → 用户文本答案（题目定义见 questions.py）",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="达到完成题数（≥3 项）的时间；不足时为空",
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
