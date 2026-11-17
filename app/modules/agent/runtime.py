"""Agent 运行时资源：AsyncConnectionPool + AsyncPostgresSaver + 编译图的生命周期。

框架表建在独立 schema（settings.agent_checkpointer_schema）：先显式创建 schema，
再让池内连接通过 search_path 固定到该 schema，PostgresSaver 无 schema 前缀的
建表迁移即落到该 schema。

V2.4：系统图常驻；用户有私有技能时，按 (user_id, 技能版本指纹) 编译并缓存独立图。
"""
import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.orm import Session

from app.modules.agent.graph import build_graph, default_capabilities
from app.modules.agent.skills.registry import ResolvedSkill, available_skills, skill_capabilities
from app.modules.agent.tools import ALL_TOOLS
from app.modules.agent.tools.action_definitions import ACTION_TOOLS
from app.modules.agent.tools.skill_definitions import build_skill_tool
from config import settings
from database import SessionLocal

MAX_CACHED_GRAPHS = 32


def _pg_conn_string() -> str:
    # postgresql+psycopg2://... -> postgresql://...（psycopg3 原生连接串）
    return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.database_url)


def _capabilities(skills: list[ResolvedSkill]) -> str:
    text = default_capabilities(ALL_TOOLS)
    if skills:
        text += "\n\n## 技能（可通过自然语言或 /技能名 触发）\n" + skill_capabilities(skills)
    else:
        text += "\n\n## 技能\n当前没有已发布的技能。"
    return text


def build_user_graph(saver, skills: list[ResolvedSkill]):
    tools = [
        *ALL_TOOLS,
        *ACTION_TOOLS,
        *(build_skill_tool(skill) for skill in skills),
    ]
    return build_graph(saver, tools, _capabilities(skills))


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
        kwargs={
            "autocommit": True,
            "options": f"-c search_path={schema}",
        },
    )
    await pool.open(wait=True)

    saver = AsyncPostgresSaver(pool)
    await saver.setup()

    with SessionLocal() as db:
        system_skills = available_skills(db, 0)
    system_graph = build_user_graph(saver, system_skills)
    return {
        "pool": pool,
        "saver": saver,
        "graph": system_graph,
        "system_graph": system_graph,
        "graphs": {},
    }


def graph_for_user(db: Session, user_id: int, runtime: dict):
    """返回该用户当前技能集对应的编译图；无私有技能时复用系统图。"""
    skills = available_skills(db, user_id)
    user_skills = [s for s in skills if s.scope == "user"]
    if not user_skills:
        return runtime["system_graph"]

    fingerprint = ",".join(f"{s.id}:{s.version_no}:{s.kind}" for s in skills)
    key = (user_id, fingerprint)
    cached = runtime["graphs"].get(key)
    if cached is not None:
        return cached
    graph = build_user_graph(runtime["saver"], skills)
    if len(runtime["graphs"]) >= MAX_CACHED_GRAPHS:
        runtime["graphs"].pop(next(iter(runtime["graphs"])))
    runtime["graphs"][key] = graph
    return graph


async def close_agent_runtime(runtime: dict) -> None:
    await runtime["pool"].close()
