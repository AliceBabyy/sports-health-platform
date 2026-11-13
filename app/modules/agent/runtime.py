"""Agent 运行时资源：AsyncConnectionPool + AsyncPostgresSaver + 编译图的生命周期。

框架表建在独立 schema（settings.agent_checkpointer_schema）：先显式创建 schema，
再让池内连接通过 search_path 固定到该 schema，PostgresSaver 无 schema 前缀的
建表迁移即落到该 schema。
"""
import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.modules.agent.graph import build_graph
from config import settings


def _pg_conn_string() -> str:
    # postgresql+psycopg2://... -> postgresql://...（psycopg3 原生连接串）
    return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.database_url)


async def init_agent_runtime() -> dict:
    conn_string = _pg_conn_string()
    schema = settings.agent_checkpointer_schema

    async with await AsyncConnection.connect(conn_string, autocommit=True) as conn:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    pool = AsyncConnectionPool(
        conn_string,
        open=False,
        min_size=settings.agent_pool_min_size,
        max_size=settings.agent_pool_max_size,
        # autocommit：迁移含 CREATE INDEX CONCURRENTLY，不能在事务块内运行
        kwargs={
            "autocommit": True,
            "options": f"-c search_path={schema}",
        },
    )
    await pool.open(wait=True)

    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    graph = build_graph(saver)
    return {"pool": pool, "saver": saver, "graph": graph}


async def close_agent_runtime(runtime: dict) -> None:
    await runtime["pool"].close()
