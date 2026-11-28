"""健康档案题号扩容：health_profile.local_key 从 varchar(8) 放宽到 varchar(64)。

页面手工建档不再限制 10 题，套内题号会继续出现 q11、q12...；AI 单批仍只使用
q1~q10。幂等执行，可重复运行。
"""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine

DDL = [
    """
    ALTER TABLE health_profile
    ALTER COLUMN local_key TYPE varchar(64)
    """,
]

COMMENTS = [
    "COMMENT ON COLUMN health_profile.local_key IS "
    "'套内题号 q1、q2...；页面题数不设上限'",
]


if __name__ == "__main__":
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        for sql in COMMENTS:
            conn.execute(text(sql))
    print("health_profile.local_key 迁移完成")
