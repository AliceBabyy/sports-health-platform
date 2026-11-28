"""V2.4 内置角色工具/技能白名单迁移：给 agent_personas 增加两列可空 JSONB。

NULL 表示沿用平台默认范围；非空（含空数组）表示管理员显式勾选的白名单。
幂等执行，可重复运行。
"""
from sqlalchemy import text

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine

DDL = [
    """
    ALTER TABLE agent_personas
    ADD COLUMN IF NOT EXISTS tool_grants jsonb NULL
    """,
    """
    ALTER TABLE agent_personas
    ADD COLUMN IF NOT EXISTS skill_grants jsonb NULL
    """,
]

COMMENTS = [
    "COMMENT ON COLUMN agent_personas.tool_grants IS "
    "'角色可用工具白名单 JSON 数组；NULL=全部已注册工具，空数组=不使用工具'",
    "COMMENT ON COLUMN agent_personas.skill_grants IS "
    "'角色可用平台技能白名单 JSON 数组；NULL=全部平台技能，空数组=不使用技能'",
]


if __name__ == "__main__":
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        for sql in COMMENTS:
            conn.execute(text(sql))
    print("agent_personas.tool_grants / skill_grants 迁移完成")
