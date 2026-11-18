"""健康/运动档案表迁移（幂等）：health_profile 表与中文 COMMENT。

用法：
    python scripts/migrate_health_profile.py

说明：只新增一张表，不改动已有表；可重复执行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS health_profile (
        user_id      integer   PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
        answers      jsonb     NOT NULL DEFAULT '{}'::jsonb,
        completed_at timestamp NULL,
        created_at   timestamp NOT NULL DEFAULT now(),
        updated_at   timestamp NOT NULL DEFAULT now()
    )
    """,
]

COMMENTS = [
    "COMMENT ON TABLE health_profile IS '健康/运动档案（1:1 用户，开放式问答答案）'",
    "COMMENT ON COLUMN health_profile.user_id IS '用户主键 + FK，删除账号时级联删除'",
    "COMMENT ON COLUMN health_profile.answers IS '题目 key → 用户文本答案（题目定义见 questions.py）'",
    "COMMENT ON COLUMN health_profile.completed_at IS '达到完成题数（≥3 项）的时间；不足时为空'",
    "COMMENT ON COLUMN health_profile.created_at IS '创建时间'",
    "COMMENT ON COLUMN health_profile.updated_at IS '更新时间（ORM onupdate 自动刷新）'",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        for sql in COMMENTS:
            conn.execute(text(sql))
    print("health_profile 表迁移完成")


if __name__ == "__main__":
    main()
