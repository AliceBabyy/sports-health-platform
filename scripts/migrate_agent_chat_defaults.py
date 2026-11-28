"""V2.22 通用对话配置迁移（幂等）：agent_chat_defaults 单行表。

用法：
    python scripts/migrate_agent_chat_defaults.py

说明：只新增一张单行配置表、初始化 id=1 并写入 COMMENT；不改动角色/会话/技能表，可重复执行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS agent_chat_defaults (
        id integer PRIMARY KEY,
        tool_grants jsonb NULL,
        skill_grants jsonb NULL,
        updated_by integer NULL REFERENCES users (id) ON DELETE SET NULL,
        created_at timestamp NOT NULL DEFAULT now(),
        updated_at timestamp NOT NULL DEFAULT now(),
        CONSTRAINT ck_agent_chat_defaults_singleton CHECK (id = 1)
    )
    """,
    """
    INSERT INTO agent_chat_defaults (id)
    VALUES (1)
    ON CONFLICT (id) DO NOTHING
    """,
    """
    COMMENT ON TABLE agent_chat_defaults IS '普通会话默认工具/技能配置（单行，id=1；不是角色）'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.id IS '固定主键 1'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.tool_grants IS '普通会话可用工具白名单 JSON；NULL=全部工具，空数组=不使用工具'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.skill_grants IS '普通会话可用平台技能白名单 JSON；NULL=全部平台技能，空数组=不使用技能'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.updated_by IS '最后修改的管理员 user_id'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.created_at IS '创建时间'
    """,
    """
    COMMENT ON COLUMN agent_chat_defaults.updated_at IS '更新时间'
    """,
    """
    COMMENT ON COLUMN agent_personas.tool_grants IS '角色可用工具白名单 JSON 数组；NULL=全部已注册工具，空数组=不使用工具'
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
    print("agent_chat_defaults 迁移完成")


if __name__ == "__main__":
    main()
