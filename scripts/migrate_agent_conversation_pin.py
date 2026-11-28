"""V2.19 会话置顶迁移：给 agent_conversations 增加 pinned 布尔列与排序索引。

pinned 默认 false；置顶会话排在未置顶之前，再按最近消息时间倒序。
幂等执行，可重复运行。
"""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine

DDL = [
    """
    ALTER TABLE agent_conversations
    ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_agent_conversations_user_pinned_last
    ON agent_conversations (user_id, pinned DESC, last_message_at DESC)
    """,
]

COMMENTS = [
    "COMMENT ON COLUMN agent_conversations.pinned IS "
    "'是否置顶；置顶会话排在未置顶之前'",
]


if __name__ == "__main__":
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        for sql in COMMENTS:
            conn.execute(text(sql))
    print("agent_conversations.pinned 迁移完成")
