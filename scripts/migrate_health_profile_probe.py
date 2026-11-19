"""健康/运动档案定制问题迁移（幂等）：health_profile 增加 custom_questions 列。

用法：
    python scripts/migrate_health_profile_probe.py

说明：只新增一列，不改动已有数据；可重复执行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine

DDL = [
    """
    ALTER TABLE health_profile
    ADD COLUMN IF NOT EXISTS custom_questions jsonb NOT NULL DEFAULT '{}'::jsonb
    """,
]

COMMENTS = [
    "COMMENT ON COLUMN health_profile.custom_questions IS "
    "'角色定制的多套问题（sets：set_id、persona_key、generated_at、questions），仅最新一套展示'",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        for sql in COMMENTS:
            conn.execute(text(sql))
    print("health_profile.custom_questions 迁移完成")


if __name__ == "__main__":
    main()
