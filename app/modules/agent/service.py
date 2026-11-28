"""AI Agent service：会话 CRUD、归属校验、消息读取、流式回复编排。

- 会话元数据走 agent_conversations（同步 ORM/psycopg2）；消息由 checkpointer 承载，
  通过 graph state 读取，不直接 SQL 框架表。
- 同一会话同时只允许一个生成（进程内 async 锁 + 运行集合），重复 client_msg_id 拒绝。
- 用户可随时停止生成：生成器只把已流出正文写到内存句柄，由停止接口在生成器收尾后
  用独立请求统一的 db/图状态做一次“中断收口”（回滚断在半途的调用、保留半截回答）。
- 硬删除：checkpointer delete_thread + 删 agent_conversations 行，同一编排。
"""
import asyncio
import contextlib
import json
import logging
import time
from datetime import date, datetime
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.ai.models.registry import is_chat_model
from app.core.exceptions import AppError
from app.modules.agent.models import (
    AUTO_TITLE_LEN,
    DEFAULT_TITLE,
    AgentConversation,
    AgentPersona,
    AgentSkill,
    AgentSkillVersion,
)
from app.modules.agent.chat_defaults import default_chat_scope
from app.modules.agent.graph import RUN_MODE_CONTINUE, RUN_MODE_NORMAL
from app.modules.agent.personas.management import bindable_persona
from app.modules.agent.personas.runtime import (
    persona_summary,
    render_persona_block,
    resolve_for_conversation,
)
from app.modules.agent.runtime import graph_for_user
from app.modules.agent.tools.action_definitions import ACTION_TOOLS
from app.modules.agent.tools.interaction import ASK_TOOL_NAME
from app.modules.agent.skills.management import resolved_from_version
from app.modules.agent.skills.parser import build_question, parse_skill_args
from app.modules.agent.skills.pending import PendingSkill, pending_store
from app.modules.agent.skills.registry import (
    ResolvedSkill,
    available_skills,
    find_by_slash,
)

logger = logging.getLogger(__name__)

# 进程内运行态：正在生成的 thread_id；client_msg_id -> thread_id（幂等兜底）
_running: set[str] = set()
_client_msgs: dict[str, str] = {}
# thread_id -> 本次生成句柄：已流出正文、本轮用户原文、中断信号、结束信号与起始时刻。
# 生成器只在内存里写 partial，不碰数据库；停止接口在生成器收尾后用自己请求的 session 收口。
_runs: dict[str, dict] = {}

STOP_WAIT_SECONDS = 8.0    # 停止接口等待生成器收尾的上限
STALE_RUN_SECONDS = 600.0  # 响应头发出前就断连导致运行态滞留时的兜底释放时长


class _Stopped(Exception):
    """用户主动停止：向上透传，不按生成失败处理。"""


def _validate_model(model_name: str | None) -> None:
    if not is_chat_model(model_name):
        raise AppError(400, "不支持该模型")


def conversation_to_dict(row: AgentConversation, persona: AgentPersona | None = None) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "model_name": row.model_name,
        "thread_id": str(row.thread_id),
        "kind": "persona" if row.persona_id else "default",
        "persona_id": row.persona_id,
        "persona_name": persona.name if persona else None,
        "persona_status": persona.status if persona else None,
        "persona_version_no": row.persona_version_no,
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "pinned": bool(row.pinned),
        "created_at": row.created_at.isoformat(),
    }


def list_conversations(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(AgentConversation)
        .filter(AgentConversation.user_id == user_id)
        .order_by(
            AgentConversation.pinned.desc(),
            AgentConversation.last_message_at.desc().nullslast(),
            AgentConversation.id.desc(),
        )
        .all()
    )
    persona_ids = {r.persona_id for r in rows if r.persona_id}
    personas = {
        p.id: p for p in db.query(AgentPersona).filter(AgentPersona.id.in_(persona_ids)).all()
    } if persona_ids else {}
    return [conversation_to_dict(r, personas.get(r.persona_id)) for r in rows]


def get_conversation(db: Session, user_id: int, conversation_id: int) -> AgentConversation:
    row = (
        db.query(AgentConversation)
        .filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise AppError(404, "会话不存在")
    return row


def _empty_conversation(db: Session, user_id: int, persona_id: int | None) -> AgentConversation | None:
    """该用户同类会话里最近一个从未发过消息的空会话。

    口径：标题仍为默认值且没有活动时间——`stream_reply` 一进入本轮就写下
    `last_message_at`，所以发送失败或中途停止的会话都不会被当成空会话复用。
    """
    query = db.query(AgentConversation).filter(
        AgentConversation.user_id == user_id,
        AgentConversation.last_message_at.is_(None),
        AgentConversation.title == DEFAULT_TITLE,
    )
    if persona_id is None:
        query = query.filter(AgentConversation.persona_id.is_(None))
    else:
        query = query.filter(AgentConversation.persona_id == persona_id)
    return query.order_by(AgentConversation.id.desc()).first()


def create_conversation(db: Session, user_id: int, model_name: str | None, persona_id: int | None = None) -> dict:
    _validate_model(model_name)
    persona = None
    persona_version_no = None
    if persona_id is not None:
        persona = bindable_persona(db, user_id, persona_id)
        persona_version_no = persona.current_version_no
    # 同一用户同类会话最多只保留一个空会话：重复新建直接复用，避免列表堆出一排“新会话”
    existing = _empty_conversation(db, user_id, persona.id if persona else None)
    if existing is not None:
        if model_name is not None and existing.model_name != model_name:
            existing.model_name = model_name
            db.commit()
            db.refresh(existing)
        return conversation_to_dict(existing, persona)
    row = AgentConversation(
        user_id=user_id, thread_id=uuid4(), model_name=model_name,
        persona_id=persona.id if persona else None,
        persona_version_no=persona_version_no,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return conversation_to_dict(row, persona)


def rename_conversation(db: Session, user_id: int, conversation_id: int, title: str) -> dict:
    row = get_conversation(db, user_id, conversation_id)
    row.title = title.strip()
    db.commit()
    db.refresh(row)
    persona = db.get(AgentPersona, row.persona_id) if row.persona_id else None
    return conversation_to_dict(row, persona)


def set_conversation_pinned(
    db: Session, user_id: int, conversation_id: int, pinned: bool
) -> dict:
    row = get_conversation(db, user_id, conversation_id)
    row.pinned = bool(pinned)
    db.commit()
    db.refresh(row)
    persona = db.get(AgentPersona, row.persona_id) if row.persona_id else None
    return conversation_to_dict(row, persona)


async def delete_conversation(db: Session, user_id: int, conversation_id: int, runtime: dict) -> None:
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    if thread_id in _running:
        raise AppError(409, "该会话正在生成，暂不能删除")
    await runtime["saver"].adelete_thread(thread_id)
    pending_store.clear(conversation_id)
    db.delete(row)
    db.commit()


def _message_text(content) -> str:
    """AI 消息正文可能是字符串或多段内容块，统一取文本部分。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


def _ask_result(content) -> dict:
    """ask_user 返回的结构化结果：正常答案是文本，用户跳过时 answer 为空、skipped=true。"""
    data = _ask_payload(content)
    text = str(data.get("answer") or "").strip()
    return {"answer": text or None, "skipped": bool(data.get("skipped"))}


def _ask_payload(content) -> dict:
    """ask_user 工具结果的内容（question/answer/skipped）；不可解析时返回空字典。"""
    data = _normalize_tool_content(content)
    return data if isinstance(data, dict) else {}


def _ask_content(question: str, answer: str | None, skipped: bool) -> str:
    """重写 ask_user 工具结果，字段与工具返回保持一致。"""
    return json.dumps(
        {"question": question, "answer": None if skipped else (answer or None), "skipped": skipped},
        ensure_ascii=False,
    )


def _question_for_call(messages, call_id: str) -> str:
    """工具结果缺问题时，从发起该调用的 AI 消息里取回题面。"""
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("id") == call_id:
                return str((call.get("args") or {}).get("question") or "").strip()
    return ""


def _turn_ask_messages(messages) -> list:
    """最近一轮里按顺序排列的 ask_user 工具结果：第 N 题即列表第 N 项。"""
    start = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].type == "human"),
        None,
    )
    if start is None:
        return []
    return [
        m for m in messages[start + 1:]
        if m.type == "tool" and getattr(m, "name", None) == ASK_TOOL_NAME
    ]


def build_turns(
    messages,
    skills: list[ResolvedSkill],
    pending_ask: dict | None = None,
) -> list[dict]:
    """把 checkpointer 消息按一轮问答聚合成前端可直接渲染的结构。

    - `blocks` 保留同一轮内所有正文段（含带 tool_calls 的中转消息正文），按出现顺序
      排列；中途提问以 `{type:"ask"}` 段插在同一位置，答案随 ToolMessage 回填。
    - `tool_runs` 携带工具名、展示标签与类别，按 `call_id` 精确配对工具结果；早期没有
      ToolMessage 的历史数据结果为空，只显示“已查询”。
    - `pending_ask` 来自图状态里的 interrupt，表示这一轮正停在一个等待回答的问题上。
    """
    turns: list[dict] = []
    turn: dict | None = None
    ask_index: dict[str, dict] = {}
    prev_interrupted = False
    for m in messages:
        if m.type == "human":
            # 旧版本遗留：工具调用后会重插一条相同 human（且此前没有产生任何正文）。
            # 内容相同时并入当前轮，避免同一问题被拆成两轮。
            if (turn is not None and not turn["blocks"] and turn["user"] == m.content):
                continue
            turn = {"user": m.content, "blocks": [], "tool_runs": []}
            ask_index = {}
            prev_interrupted = False
            turns.append(turn)
        elif turn is None:
            # 没有以用户消息开头的残缺序列，兜底跳过
            continue
        elif m.type == "ai":
            text = _message_text(m.content)
            interrupted = bool((getattr(m, "additional_kwargs", None) or {}).get("interrupted"))
            if text.strip():
                last = turn["blocks"][-1] if turn["blocks"] else None
                if prev_interrupted and last is not None and last.get("type") == "text":
                    # 续写：接在被中断的片段后面，不另起一段
                    last["content"] += text
                else:
                    turn["blocks"].append({"type": "text", "content": text})
                prev_interrupted = interrupted
                turn["_last_interrupted"] = interrupted
            # 工具调用动作：登记 run，等待 ToolMessage 按 call_id 回填
            for tc in getattr(m, "tool_calls", None) or []:
                if tc.get("name") == ASK_TOOL_NAME:
                    args = tc.get("args") or {}
                    block = {
                        "type": "ask",
                        "question": str(args.get("question") or "").strip(),
                        "options": [str(o).strip() for o in (args.get("options") or []) if str(o).strip()][:4],
                        "multiple": bool(args.get("multiple")),
                        "answer": None,
                        "skipped": False,
                        "call_id": tc.get("id"),
                    }
                    turn["blocks"].append(block)
                    prev_interrupted = False
                    if tc.get("id"):
                        ask_index[tc["id"]] = block
                    continue
                meta = _tool_meta(tc["name"], skills)
                turn["tool_runs"].append({
                    "tool": meta["tool"],
                    "label": meta["label"],
                    "kind": meta["kind"],
                    "args": _safe_args(tc.get("args") or {}),
                    "data": None,
                    "call_id": tc.get("id"),
                })
        elif m.type == "tool":
            call_id = getattr(m, "tool_call_id", None)
            ask_block = ask_index.get(call_id) if call_id else None
            if ask_block is not None:
                result = _ask_result(m.content)
                ask_block["answer"] = result["answer"]
                ask_block["skipped"] = result["skipped"]
                continue
            data = _normalize_tool_content(m.content)
            target = None
            if call_id is not None:
                target = next(
                    (r for r in turn["tool_runs"]
                     if r["call_id"] == call_id and r["data"] is None),
                    None,
                )
            if target is None:
                # 并行/重放等场景按顺序兜底，取第一个未回填的 run
                target = next((r for r in turn["tool_runs"] if r["data"] is None), None)
            if target is not None:
                target["data"] = data
                if getattr(m, "name", None):
                    meta = _tool_meta(m.name, skills)
                    target["tool"] = meta["tool"]
                    target["label"] = meta["label"]
                    target["kind"] = meta["kind"]
            else:
                # 找不到对应调用的异常态，仍保留结果，避免工具数据丢失
                meta = _tool_meta(getattr(m, "name", None) or "unknown", skills)
                turn["tool_runs"].append({
                    "tool": meta["tool"],
                    "label": meta["label"],
                    "kind": meta["kind"],
                    "args": {},
                    "data": data,
                    "call_id": call_id,
                })

    if pending_ask:
        # 只可能有一个问题处于等待态：标记最后一条未回答的 ask 段
        for t in turns:
            block = next(
                (b for b in reversed(t["blocks"])
                 if b["type"] == "ask" and b["answer"] is None),
                None,
            )
            if block is not None:
                block["pending"] = True
                break

    result: list[dict] = []
    for index, item in enumerate(turns):
        interrupted = item.pop("_last_interrupted", False)
        if item["user"] is None and not item["blocks"] and not item["tool_runs"]:
            continue
        # 只有最后一轮还停在中断处才标记：续写或新提问之后，这一轮已经有了后续内容
        if interrupted and index == len(turns) - 1:
            item["interrupted"] = True
        result.append(item)
    return result


def _resolve_chat_scopes(db: Session, row: AgentConversation, user_id: int):
    """返回 (角色人设, 工具/技能 scope)；普通会话的 scope 来自通用对话配置。"""
    persona = resolve_for_conversation(db, row, user_id)
    scope = persona if persona is not None else default_chat_scope(db)
    return persona, scope


async def get_messages(db: Session, user_id: int, conversation_id: int, runtime: dict) -> dict:
    """按一轮问答（turn）聚合历史，正文段、中途提问与工具轨迹一并返回。

    checkpointer 完整存着 HumanMessage、带 tool_calls 的中转 AIMessage、ToolMessage 与
    最终 AIMessage；这里把同一轮的正文按出现顺序收进 `blocks`（含 ask 段），工具调用
    与结果归并进 `tool_runs`，供前端用与流式一致的渲染器重建视图。
    """
    row = get_conversation(db, user_id, conversation_id)
    persona, scope = _resolve_chat_scopes(db, row, user_id)
    config = {"configurable": {"thread_id": str(row.thread_id)}}
    graph = graph_for_user(db, user_id, runtime, scope)
    state = await graph.aget_state(config)
    skills = available_skills(
        db, user_id, scope.key,
        skill_grants=scope.skill_grants,
    )
    return {
        "conversation_id": row.id,
        "generating": _is_generating(str(row.thread_id)),
        "turns": build_turns(
            state.values.get("messages", []), skills, pending_ask=_pending_ask(state),
        ),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _acquire_slot(thread_id: str, client_msg_id: str, row: AgentConversation) -> None:
    """占位：同一会话同时只允许一次生成。

    全在同一个事件循环里同步完成、中途没有 await，因此不需要额外加锁；结束信号已置位
    或已超时的残留运行态先释放，避免断连后会话被永久占用。
    """
    if client_msg_id in _client_msgs:
        raise AppError(409, "请勿重复发送")
    if thread_id in _running:
        run = _runs.get(thread_id)
        alive = (
            run is not None
            and not run["done"].is_set()
            and time.monotonic() - run["started_at"] < STALE_RUN_SECONDS
        )
        if alive:
            raise AppError(409, "该会话正在生成回复")
        _release_slot(thread_id)
    _running.add(thread_id)
    _client_msgs[client_msg_id] = thread_id
    _runs[thread_id] = {
        "conversation_id": row.id,
        "user_id": row.user_id,
        "user": "",
        "partial": "",
        "stop": asyncio.Event(),
        "done": asyncio.Event(),
        "started_at": time.monotonic(),
    }


def _release_slot(thread_id: str, client_msg_id: str | None = None) -> None:
    """释放占位与运行句柄；同步执行，取消中的生成器也能安全收尾。"""
    _running.discard(thread_id)
    _runs.pop(thread_id, None)
    for key, value in list(_client_msgs.items()):
        if key == client_msg_id or value == thread_id:
            _client_msgs.pop(key, None)


async def acquire_reply_slot(db: Session, user_id: int, conversation_id: int, payload):
    """在响应头发送前完成可同步判定的校验与 slot 预占。

    StreamingResponse 会先发 200 头再迭代生成器，若把 400/404/409 留在生成器里，
    头已发出就无法改状态码，只能断连。故提前到构造 StreamingResponse 之前，
    让全局异常处理器返回正确的 JSON 状态码。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    _acquire_slot(thread_id, payload.client_msg_id, row)
    run = _runs.get(thread_id)
    if run is not None:
        run["user"] = getattr(payload, "content", "") or ""
    if payload.model_name is not None:
        row.model_name = payload.model_name
    return row, thread_id


async def prepare_regenerate(db: Session, user_id: int, conversation_id: int, runtime: dict, payload):
    """回滚最近一轮：移除最后一条用户消息及其后的工具中转/AI 回答，返回待重发的用户原文。

    消息由 checkpointer 承载，这里经 graph.update_state + RemoveMessage 按消息 ID 删除，
    不直接写框架表；随后复用 stream_reply 用同一用户原文重新生成，覆盖上一条回答。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    persona, scope = _resolve_chat_scopes(db, row, user_id)
    _acquire_slot(thread_id, payload.client_msg_id, row)
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph_for_user(db, user_id, runtime, scope).aget_state(config)
    msgs = state.values.get("messages", [])

    if _pending_ask(state):
        _release_slot(thread_id, payload.client_msg_id)
        raise AppError(409, "当前有等待回答的问题，请先回答或跳过")

    human_idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].type == "human"), None)
    if human_idx is None:
        _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")
    # 保留最后一条用户消息，仅移除其后的工具中转/上一条 AI 回答；
    # 若把用户消息一并删掉，update_state 后消息为空，条件边会取最后一条而越界。
    removed = msgs[human_idx + 1:]
    has_answer = any(m.type == "ai" and not getattr(m, "tool_calls", None) for m in removed)
    if not has_answer:
        _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")

    try:
        await graph_for_user(db, user_id, runtime, scope).aupdate_state(
            config,
            {"messages": [RemoveMessage(id=m.id) for m in removed if getattr(m, "id", None)]},
        )
        human_content = msgs[human_idx].content
        if payload.model_name is not None:
            row.model_name = payload.model_name
        db.commit()
    except Exception:
        _release_slot(thread_id, payload.client_msg_id)
        raise
    return row, thread_id, human_content


def _unfinished_tail(messages) -> list:
    """尾部断在半途的消息：删掉“工具调用没有配齐结果”的中转消息及其后续。

    已完整执行完的工具轨迹（调用 + 对应 ToolMessage）保留，“继续”时可直接复用结果。
    """
    human_idx = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].type == "human"), None
    )
    if human_idx is None:
        return []
    cut = len(messages)
    for i in range(len(messages) - 1, human_idx, -1):
        calls = getattr(messages[i], "tool_calls", None) or []
        if not calls:
            continue
        answered = {
            getattr(item, "tool_call_id", None)
            for item in messages[i + 1:]
            if item.type == "tool"
        }
        if not {call.get("id") for call in calls}.issubset(answered):
            cut = i
    return messages[cut:]


async def _rollback_unfinished(graph, config, messages) -> bool:
    """按消息 ID 回滚断在半途的尾部；返回是否发生回滚。"""
    removed = _unfinished_tail(messages)
    ids = [RemoveMessage(id=m.id) for m in removed if getattr(m, "id", None)]
    if not ids:
        return False
    await graph.aupdate_state(config, {"messages": ids}, as_node="agent")
    return True


def _is_settled_answer(message) -> bool:
    """最后一条已经是完整回答（不是断在半途、也不是中断残留）。"""
    if message.type != "ai" or getattr(message, "tool_calls", None):
        return False
    return not (getattr(message, "additional_kwargs", None) or {}).get("interrupted")


async def _close_interrupted_turn(graph, config, partial: str) -> bool:
    """停止后的收口：回滚断在半途的调用，把已流出正文作为一条 interrupted 回答留下。

    没有可收口的内容（本轮已完成、或还没产生任何输出）时返回 False。
    """
    state = await graph.aget_state(config)
    messages = list(state.values.get("messages", []))
    if not messages or _is_settled_answer(messages[-1]):
        return False
    rolled = await _rollback_unfinished(graph, config, messages)
    if partial.strip():
        await graph.aupdate_state(
            config,
            {"messages": [AIMessage(content=partial, additional_kwargs={"interrupted": True})]},
            as_node="agent",
        )
        return True
    return rolled


def _stop_payload(row: AgentConversation, stopped: bool, settled: bool, closed: bool, partial: str = "") -> dict:
    return {
        "conversation_id": row.id,
        "stopped": stopped,
        "settled": settled,
        "closed": closed,
        "title": row.title,
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "partial": partial,
    }


async def stop_reply(db: Session, user_id: int, conversation_id: int, runtime: dict) -> dict:
    """中断当前生成：置停止信号 → 等生成器收尾 → 用本请求的 session 做一次状态收口。

    生成器在取消中不能安全写库，所以落库统一放在这里；停止信号只负责让模型流尽快停下。
    """
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    run = _runs.get(thread_id)
    if run is None:
        return _stop_payload(row, stopped=False, settled=True, closed=False)

    run["stop"].set()
    settled = True
    try:
        await asyncio.wait_for(run["done"].wait(), timeout=STOP_WAIT_SECONDS)
    except asyncio.TimeoutError:
        # 生成器没能及时收尾（多见于响应头发出前就断连）：释放占位，避免会话被永久锁住
        settled = False
        _release_slot(thread_id)

    partial = run.get("partial") or ""
    closed = False
    if settled:
        persona, scope = _resolve_chat_scopes(db, row, user_id)
        graph = graph_for_user(db, user_id, runtime, scope)
        try:
            closed = await _close_interrupted_turn(
                graph, {"configurable": {"thread_id": thread_id}}, partial
            )
        except Exception as exc:  # 收口失败不影响停止本身，保留本次已流出内容由前端展示
            logger.warning("agent stop cleanup failed: conv=%s err=%r", row.id, exc)

    now = datetime.now()
    row.last_message_at = now
    user_text = (run.get("user") or "").strip()
    if user_text and row.title == DEFAULT_TITLE:
        row.title = user_text[:AUTO_TITLE_LEN] or DEFAULT_TITLE
    db.commit()
    return _stop_payload(row, stopped=True, settled=settled, closed=closed, partial=partial)


async def prepare_continue(db: Session, user_id: int, conversation_id: int, runtime: dict, payload):
    """续写前置：确认最近一轮停在被中断/未完成处，回滚断在半途的调用后占位。

    真正的生成仍交给 stream_reply：不新增 HumanMessage，只以 run_mode=续写 再跑一次 agent。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    persona, scope = _resolve_chat_scopes(db, row, user_id)
    graph = graph_for_user(db, user_id, runtime, scope)
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)

    if _pending_ask(state):
        raise AppError(409, "当前有等待回答的问题，请先回答或跳过")
    messages = list(state.values.get("messages", []))
    if not messages:
        raise AppError(400, "暂无可继续的回答")
    if _is_settled_answer(messages[-1]):
        raise AppError(400, "当前没有可继续的回答")

    await _rollback_unfinished(graph, config, messages)
    _acquire_slot(thread_id, payload.client_msg_id, row)
    if payload.model_name is not None:
        row.model_name = payload.model_name
    db.commit()
    return row, thread_id


async def update_ask_answer(db: Session, user_id: int, conversation_id: int, runtime: dict, payload) -> dict:
    """回改本轮某一道已答提问（按题号）：原地替换该题的 ToolMessage，不新增消息、不重跑模型。

    只在该轮仍停在另一道题上（存在挂起的 ask_user）时允许。补丁走 `Command(update=...)`：
    既按消息 id 原地替换历史答案，又让工具节点把当前这道题重新挂起，后续作答链路不受影响。
    本轮结束后再改答案不会同步到已落库的业务数据，因此直接拒绝并提示重新执行专项。
    """
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    if _is_generating(thread_id):
        raise AppError(409, "该会话正在生成回复")
    answer = (payload.answer or "").strip()
    if not answer:
        raise AppError(400, "回答不能为空")

    persona, scope = _resolve_chat_scopes(db, row, user_id)
    graph = graph_for_user(db, user_id, runtime, scope)
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)
    if _pending_ask(state) is None:
        raise AppError(409, "本轮问答已结束，无法回改回答；如需更新，请重新发起对应的专项命令")

    messages = list(state.values.get("messages", []))
    asks = _turn_ask_messages(messages)
    if not 1 <= payload.ask_index <= len(asks):
        raise AppError(404, "没有找到这一题的作答记录")
    target = asks[payload.ask_index - 1]

    question = str(_ask_payload(target.content).get("question") or "").strip()
    if not question:
        question = _question_for_call(messages, getattr(target, "tool_call_id", ""))
    patch = ToolMessage(
        content=_ask_content(question, answer, False),
        tool_call_id=target.tool_call_id,
        name=ASK_TOOL_NAME,
        id=target.id,
    )
    async for _ in graph.astream(
        Command(update={"messages": [patch]}), config, stream_mode="updates"
    ):
        pass

    pending = _pending_ask(await graph.aget_state(config))
    return {
        "ok": True,
        "ask_index": payload.ask_index,
        "question": question,
        "answer": answer,
        "skipped": False,
        "pending": pending,
    }


def _normalize_tool_content(content):
    """工具结果可能是 dict 或 JSON 字符串，统一成可序列化对象。"""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return {"text": content}
    return content


BASE_TOOL_LABELS = {
    "get_workout_summary": "运动汇总",
    "get_fitness_records": "健身记录",
    "get_swim_records": "游泳记录",
    "get_dance_records": "舞蹈记录",
    "get_body_measurements": "身材数据",
    "get_state_records": "状态记录",
    "get_cycle_records": "生理周期",
    "get_profile_info": "个人资料",
    "save_today_workout_plan": "保存今日计划",
    "import_sport_records": "导入运动记录",
    "web_search": "联网搜索",
}

ACTION_TOOL_NAMES = {tool.name for tool in ACTION_TOOLS}


def _tool_meta(tool_name: str, skills: list[ResolvedSkill]) -> dict:
    for skill in skills:
        if skill.tool_name == tool_name:
            return {"tool": tool_name, "label": skill.name, "kind": "skill",
                    "origin": skill.origin, "version": f"v{skill.version_no}", "skill": skill.key}
    if tool_name in ACTION_TOOL_NAMES:
        return {"tool": tool_name, "label": BASE_TOOL_LABELS.get(tool_name, tool_name),
                "kind": "action", "origin": "system", "version": None, "skill": None}
    return {"tool": tool_name, "label": BASE_TOOL_LABELS.get(tool_name, tool_name),
            "kind": "base", "origin": "system", "version": None, "skill": None}


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_args(args: dict) -> dict:
    return json.loads(json.dumps(args, default=_json_default, ensure_ascii=False))


def _slash_parts(content: str) -> tuple[str, str] | None:
    content = content.strip()
    if not content.startswith("/"):
        return None
    body = content[1:].strip()
    parts = body.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def _commands_text(skills: list[ResolvedSkill]) -> str:
    lines = [f"/{s.name}" for s in skills]
    return "、".join(lines) if lines else "当前没有可用技能"


def _pending_skill(db: Session, pending: PendingSkill, user_id: int) -> ResolvedSkill | None:
    row = db.get(AgentSkill, pending.skill_id)
    if row is None or row.status != "active" or row.current_version_no != pending.version_no:
        return None
    if row.scope == "user" and row.owner_user_id != user_id:
        return None
    version = db.query(AgentSkillVersion).filter(
        AgentSkillVersion.skill_id == row.id,
        AgentSkillVersion.version_no == pending.version_no,
    ).first()
    return resolved_from_version(row, version) if version else None


def _pending_ask(state) -> dict | None:
    """从图状态里取出等待回答的提问；没有挂起的 interrupt 时返回 None。"""
    for item in getattr(state, "interrupts", ()) or ():
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value.get("question"):
            return value
    return None


def _is_generating(thread_id: str) -> bool:
    """该会话是否正在本进程生成：有运行句柄且结束信号尚未置位。

    进程重启后内存态清空，读到的就是 False；此时库里可能停在半途，由“继续”入口处理。
    """
    run = _runs.get(thread_id)
    return run is not None and not run["done"].is_set()


async def _stream_graph(graph, stream_input, config, skills: list[ResolvedSkill], run: dict | None = None):
    """逐帧转发图执行结果；带 run 时可被停止信号打断，并把已流出正文记进 run。

    停止用“下一帧”和“停止信号”竞速：信号先到就取消这一帧的 await，连带关闭底层
    模型流；半截回答不进 checkpointer，由停止接口在随后的一次性收口里落库。
    """
    stop_event = run["stop"] if run else None
    iterator = graph.astream(
        stream_input,
        config=config,
        stream_mode=["messages", "updates"],
    ).__aiter__()

    try:
        while True:
            next_task = asyncio.ensure_future(iterator.__anext__())
            if stop_event is None:
                try:
                    mode, data = await next_task
                except StopAsyncIteration:
                    break
            else:
                stop_task = asyncio.ensure_future(stop_event.wait())
                done, _ = await asyncio.wait(
                    {next_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_task not in done:
                    next_task.cancel()
                    with contextlib.suppress(BaseException):
                        await next_task
                    raise _Stopped()
                stop_task.cancel()
                with contextlib.suppress(BaseException):
                    await stop_task
                try:
                    mode, data = next_task.result()
                except StopAsyncIteration:
                    break

            if mode == "messages":
                message_chunk, metadata = data
                if metadata.get("langgraph_node") == "agent" and message_chunk.content:
                    if run is not None:
                        run["partial"] += _message_text(message_chunk.content)
                    yield _sse("delta", {"content": message_chunk.content})
            elif mode == "updates":
                for node, update in data.items():
                    if node == "__interrupt__":
                        for item in update:
                            value = getattr(item, "value", None)
                            if isinstance(value, dict) and value.get("question"):
                                yield _sse("ask", {
                                    "question": value.get("question", ""),
                                    "options": value.get("options") or [],
                                    "multiple": bool(value.get("multiple")),
                                })
                        continue
                    if not isinstance(update, dict):
                        continue
                    for msg in update.get("messages", []):
                        if node == "agent" and getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                if tc["name"] == ASK_TOOL_NAME:
                                    continue
                                meta = _tool_meta(tc["name"], skills)
                                yield _sse("tool_start", {
                                    **meta, "args": tc["args"], "call_id": tc.get("id"),
                                })
                        elif node == "tools":
                            name = getattr(msg, "name", None)
                            if name == ASK_TOOL_NAME:
                                # 提问的答案由 ask 段承载，不再作为工具行展示
                                continue
                            meta = _tool_meta(name, skills)
                            yield _sse("tool_result", {
                                **meta,
                                "data": _normalize_tool_content(msg.content),
                                "call_id": getattr(msg, "tool_call_id", None),
                            })
    finally:
        # 主动停止/断连时把底层迭代器关掉，避免模型流悬挂
        with contextlib.suppress(Exception):
            await iterator.aclose()


async def _persist(graph, config, human: str, assistant: str) -> None:
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=human), AIMessage(content=assistant)]},
        as_node="agent",
    )


def _finish(db: Session, row: AgentConversation, content: str | None, persona) -> str:
    now = datetime.now()
    row.last_message_at = now
    if content and row.title == DEFAULT_TITLE:
        row.title = content.strip()[:AUTO_TITLE_LEN] or DEFAULT_TITLE
    db.commit()
    return _sse("done", {
        "conversation_id": row.id,
        "title": row.title,
        "last_message_at": now.isoformat(),
        "persona": persona_summary(persona),
    })


async def stream_reply(db: Session, row: AgentConversation, thread_id: str, runtime: dict, payload, human_content: str | None = None, replay: bool = False, continuation: bool = False):
    # 走进这一轮就记活动时间：只有「新建后从没发过消息」的会话才算空会话，
    # 失败、中断或续写都不会让它退回空会话被「新建」复用；同时让会话列表
    # 按最近一次真实对话排序，而不是等模型回答结束才更新。
    activity_at = datetime.now()
    row.last_message_at = activity_at
    db.commit()
    persona, scope = _resolve_chat_scopes(db, row, row.user_id)
    graph = graph_for_user(db, row.user_id, runtime, scope)
    skills = available_skills(
        db, row.user_id, scope.key,
        skill_grants=scope.skill_grants,
    )
    base_config = {
        "configurable": {
            "thread_id": thread_id,
            "model_name": row.model_name,
            "user_id": row.user_id,
            "conversation_id": row.id,
            "persona_id": persona.id if persona else None,
            "persona_version_no": persona.version_no if persona else None,
            "persona_block": render_persona_block(persona),
            "run_mode": RUN_MODE_NORMAL,
            # 联网开关只作用于本轮生成，默认关闭；由前端每次请求显式传入
            "web_search": bool(getattr(payload, "web_search", False)),
        },
        "recursion_limit": 30,
    }
    content = human_content or getattr(payload, "content", "") or ""
    run = _runs.get(thread_id)
    if run is not None and content:
        run["user"] = content
    today = date.today()

    try:
        # 上一轮停在 ask_user 等待回答时，本条消息即答案：用 Command(resume) 从同一
        # thread 继续，不新增 HumanMessage，问答都留在原来那一轮里。
        pending_ask = None
        if not replay and not continuation:
            state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            pending_ask = _pending_ask(state)

        yield _sse("start", {
            "conversation_id": row.id,
            "thread_id": thread_id,
            "resume": pending_ask is not None,
            "last_message_at": activity_at.isoformat(),
        })

        if continuation:
            # 续写：不新增用户消息，直接在既有状态上再跑一次 agent；提示词按 run_mode 要求接续
            config = {**base_config, "configurable": {
                **base_config["configurable"],
                "skill_trigger": "model",
                "run_mode": RUN_MODE_CONTINUE,
            }}
            async for event in _stream_graph(graph, {"messages": []}, config, skills, run):
                yield event
            yield _finish(db, row, None, persona)
            return

        if pending_ask is not None:
            pending_store.clear(row.id)
            config = {**base_config, "configurable": {
                **base_config["configurable"], "skill_trigger": "answer",
            }}
            resume_value = (
                {"answer": None, "skipped": True}
                if getattr(payload, "skip_ask", False)
                else {"answer": content, "skipped": False}
            )
            async for event in _stream_graph(graph, Command(resume=resume_value), config, skills, run):
                yield event
            yield _finish(db, row, None, persona)
            return

        if replay:
            config = {**base_config, "configurable": {**base_config["configurable"], "skill_trigger": "model"}}
            async for event in _stream_graph(graph, {"messages": []}, config, skills, run):
                yield event
        else:
            slash = _slash_parts(content)
            pending = pending_store.get(row.id, row.user_id)

            if slash is not None:
                pending_store.clear(row.id)
                token, rest = slash
                if not token:
                    reply = "用法：`/技能名 自然语言`。可用技能：" + _commands_text(skills)
                    await _persist(graph, base_config, content, reply)
                    yield _sse("delta", {"content": reply})
                else:
                    skill = find_by_slash(
                        db, row.user_id, token, scope.key,
                        skill_grants=scope.skill_grants,
                    )
                    if skill is None:
                        reply = f"没有找到 `/{token}` 技能。可用技能：" + _commands_text(skills)
                        await _persist(graph, base_config, content, reply)
                        yield _sse("delta", {"content": reply})
                    else:
                        parse = await parse_skill_args(skill, rest, today)
                        if parse.should_ask:
                            pending_store.set(PendingSkill(
                                conversation_id=row.id, user_id=row.user_id, skill_id=skill.id,
                                version_no=skill.version_no, original_text=content,
                                missing=parse.missing or [e["field"] for e in parse.errors],
                            ))
                            reply = build_question(skill, parse.missing, parse.errors)
                            await _persist(graph, base_config, content, reply)
                            yield _sse("delta", {"content": reply})
                        else:
                            config = {**base_config, "configurable": {
                                **base_config["configurable"],
                                "skill_trigger": "slash",
                                "skill_parse": parse.meta,
                            }}
                            safe_args = _safe_args(parse.args)
                            ai = AIMessage(content="", tool_calls=[{
                                "name": skill.tool_name,
                                "args": safe_args,
                                "id": f"call_{uuid4().hex}",
                                "type": "tool_call",
                            }])
                            await graph.aupdate_state(
                                config,
                                {"messages": [HumanMessage(content=content), ai]},
                                as_node="agent",
                            )
                            yield _sse("tool_start", {**_tool_meta(skill.tool_name, skills),
                                                      "args": safe_args})
                            async for event in _stream_graph(graph, None, config, skills, run):
                                yield event

            elif pending is not None:
                skill = _pending_skill(db, pending, row.user_id)
                if skill is None:
                    pending_store.clear(row.id)
                    reply = "待补充的技能已停用或版本已更新，请重新发送 `/技能名 自然语言`。"
                    await _persist(graph, base_config, content, reply)
                    yield _sse("delta", {"content": reply})
                else:
                    parse = await parse_skill_args(skill, pending.original_text + " " + content, today)
                    if parse.should_ask:
                        if not pending_store.bump(pending):
                            pending_store.clear(row.id)
                            reply = "追问次数已达上限，请重新发送完整命令，例如 `/减重分析 最近两周`。"
                            await _persist(graph, base_config, content, reply)
                            yield _sse("delta", {"content": reply})
                        else:
                            pending.missing = parse.missing or [e["field"] for e in parse.errors]
                            pending_store.set(pending)
                            reply = build_question(skill, parse.missing, parse.errors)
                            await _persist(graph, base_config, content, reply)
                            yield _sse("delta", {"content": reply})
                    else:
                        pending_store.clear(row.id)
                        config = {**base_config, "configurable": {
                            **base_config["configurable"],
                            "skill_trigger": "slash",
                            "skill_parse": parse.meta,
                        }}
                        safe_args = _safe_args(parse.args)
                        ai = AIMessage(content="", tool_calls=[{
                            "name": skill.tool_name,
                            "args": safe_args,
                            "id": f"call_{uuid4().hex}",
                            "type": "tool_call",
                        }])
                        await graph.aupdate_state(
                            config,
                            {"messages": [HumanMessage(content=content), ai]},
                            as_node="agent",
                        )
                        yield _sse("tool_start", {**_tool_meta(skill.tool_name, skills), "args": safe_args})
                        async for event in _stream_graph(graph, None, config, skills, run):
                            yield event

            else:
                config = {**base_config, "configurable": {**base_config["configurable"], "skill_trigger": "model"}}
                async for event in _stream_graph(
                    graph, {"messages": [HumanMessage(content=content)]}, config, skills, run
                ):
                    yield event

        yield _finish(db, row, content, persona)
    except _Stopped:
        # 用户主动停止：模型流已关闭，状态收口交给停止接口；正常结束本次流，不写 done/error
        return
    except Exception as exc:
        logger.warning("agent stream failed: conv=%s err=%r", row.id, exc)
        db.rollback()
        yield _sse("error", {"message": "生成失败，请稍后重试"})
    finally:
        if run is not None:
            run["done"].set()
        _release_slot(thread_id, payload.client_msg_id)
