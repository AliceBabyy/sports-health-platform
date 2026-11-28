"""Agent 运行时资源：AsyncConnectionPool + AsyncPostgresSaver + 编译图的生命周期。

框架表建在独立 schema（settings.agent_checkpointer_schema）：先显式创建 schema，
再让池内连接通过 search_path 固定到该 schema，PostgresSaver 无 schema 前缀的
建表迁移即落到该 schema。

V2.4：系统图常驻；用户有私有技能、角色显式工具/技能白名单或角色专用工具时，按
(user_id, 技能版本指纹, 角色指纹) 编译并缓存独立图。
"""
import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.orm import Session

from app.modules.agent.chat_defaults import default_chat_scope
from app.modules.agent.graph import build_graph, default_capabilities
from app.modules.agent.skills.registry import ResolvedSkill, available_skills, skill_capabilities
from app.modules.agent.tools import ALL_TOOLS, ask_user
from app.modules.agent.tools.action_definitions import ACTION_TOOLS
from app.modules.agent.tools.policy import persona_graph_fingerprint, tools_for_persona
from app.modules.agent.tools.skill_definitions import build_skill_tool
from app.modules.agent.tools.web_search import web_search, web_search_available
from config import settings
from database import SessionLocal

MAX_CACHED_GRAPHS = 32


def _pg_conn_string() -> str:
    # postgresql+psycopg2://... -> postgresql://...（psycopg3 原生连接串）
    return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.database_url)


def _capabilities(skills: list[ResolvedSkill], tools=None) -> str:
    text = default_capabilities(tools or ALL_TOOLS)
    if skills:
        text += "\n\n## 技能（可通过自然语言或 /技能名 触发）\n" + skill_capabilities(skills)
    else:
        text += "\n\n## 技能\n当前没有已发布的技能。"
    return text


def build_user_graph(saver, skills: list[ResolvedSkill], persona=None):
    tools = [
        *ALL_TOOLS,
        ask_user,
        *ACTION_TOOLS,
        *(build_skill_tool(skill) for skill in skills),
    ]
    tools = tools_for_persona(tools, persona)
    # 联网工具不受角色白名单裁剪：它由每轮会话开关控制，开启时所有会话/角色都可用
    if web_search_available():
        tools.append(web_search)
    return build_graph(saver, tools, _capabilities(skills, tools))


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
        scope = default_chat_scope(db)
        system_skills = available_skills(
            db, 0, scope.key, skill_grants=scope.skill_grants,
        )
        system_fp = persona_graph_fingerprint(scope)
    system_graph = build_user_graph(saver, system_skills, scope)
    return {
        "pool": pool,
        "saver": saver,
        "graph": system_graph,
        "system_graph": system_graph,
        "system_default_fp": system_fp,
        "graphs": {},
    }


def graph_for_user(db: Session, user_id: int, runtime: dict, persona=None):
    """返回该用户当前技能集（及角色/通用对话工具范围）对应的编译图；无差异时复用系统图。"""
    scope = persona if persona is not None else default_chat_scope(db)
    skills = available_skills(
        db, user_id, scope.key,
        skill_grants=scope.skill_grants,
    )
    user_skills = [s for s in skills if s.scope == "user"]
    scope_fp = persona_graph_fingerprint(scope)
    if not user_skills and scope_fp == runtime.get("system_default_fp", ""):
        return runtime["system_graph"]

    fingerprint = ",".join(f"{s.id}:{s.version_no}:{s.kind}" for s in skills)
    key = (user_id, fingerprint, scope_fp)
    cached = runtime["graphs"].get(key)
    if cached is not None:
        return cached
    graph = build_user_graph(runtime["saver"], skills, scope)
    if len(runtime["graphs"]) >= MAX_CACHED_GRAPHS:
        runtime["graphs"].pop(next(iter(runtime["graphs"])))
    runtime["graphs"][key] = graph
    return graph


def refresh_system_graph(runtime: dict) -> None:
    """平台技能或通用对话配置变更后重建常驻图并清空按用户图缓存。

    系统图在启动时只编译一次；管理员在 ``/system/skills`` 或 ``/system/personas``
    修改平台技能/通用对话后调用本函数，让下一次提问直接使用最新配置，无需重启服务。
    """
    with SessionLocal() as db:
        scope = default_chat_scope(db)
        system_skills = available_skills(
            db, 0, scope.key, skill_grants=scope.skill_grants,
        )
        system_fp = persona_graph_fingerprint(scope)
    graph = build_user_graph(runtime["saver"], system_skills, scope)
    runtime["system_graph"] = graph
    runtime["graph"] = graph
    runtime["system_default_fp"] = system_fp
    runtime["graphs"].clear()


async def close_agent_runtime(runtime: dict) -> None:
    await runtime["pool"].close()
