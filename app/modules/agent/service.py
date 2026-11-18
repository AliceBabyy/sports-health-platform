"""AI Agent service：会话 CRUD、归属校验、消息读取、流式回复编排。

- 会话元数据走 agent_conversations（同步 ORM/psycopg2）；消息由 checkpointer 承载，
  通过 graph state 读取，不直接 SQL 框架表。
- 同一会话同时只允许一个生成（进程内 async 锁 + 运行集合），重复 client_msg_id 拒绝。
- 硬删除：checkpointer delete_thread + 删 agent_conversations 行，同一编排。
"""
import asyncio
import json
import logging
from datetime import date, datetime
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.ai.models.registry import MODELS
from app.core.exceptions import AppError
from app.modules.agent.models import (
    AUTO_TITLE_LEN,
    DEFAULT_TITLE,
    AgentConversation,
    AgentPersona,
    AgentSkill,
    AgentSkillVersion,
)
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
_state_lock = asyncio.Lock()


def _validate_model(model_name: str | None) -> None:
    if model_name is not None and model_name not in MODELS:
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
        "created_at": row.created_at.isoformat(),
    }


def list_conversations(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(AgentConversation)
        .filter(AgentConversation.user_id == user_id)
        .order_by(
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


def create_conversation(db: Session, user_id: int, model_name: str | None, persona_id: int | None = None) -> dict:
    _validate_model(model_name)
    persona = None
    persona_version_no = None
    if persona_id is not None:
        persona = bindable_persona(db, user_id, persona_id)
        persona_version_no = persona.current_version_no
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


def _ask_answer(content) -> str | None:
    """ask_user 工具返回结构化答案；空答案（用户跳过）视为未回答。"""
    data = _normalize_tool_content(content)
    if not isinstance(data, dict):
        return None
    text = str(data.get("answer") or "").strip()
    return text or None


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
    for m in messages:
        if m.type == "human":
            # 旧版本遗留：工具调用后会重插一条相同 human（且此前没有产生任何正文）。
            # 内容相同时并入当前轮，避免同一问题被拆成两轮。
            if (turn is not None and not turn["blocks"] and turn["user"] == m.content):
                continue
            turn = {"user": m.content, "blocks": [], "tool_runs": []}
            ask_index = {}
            turns.append(turn)
        elif turn is None:
            # 没有以用户消息开头的残缺序列，兜底跳过
            continue
        elif m.type == "ai":
            text = _message_text(m.content)
            if text.strip():
                turn["blocks"].append({"type": "text", "content": text})
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
                        "call_id": tc.get("id"),
                    }
                    turn["blocks"].append(block)
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
                ask_block["answer"] = _ask_answer(m.content)
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

    return [t for t in turns
            if t["user"] is not None or t["blocks"] or t["tool_runs"]]


async def get_messages(db: Session, user_id: int, conversation_id: int, runtime: dict) -> dict:
    """按一轮问答（turn）聚合历史，正文段、中途提问与工具轨迹一并返回。

    checkpointer 完整存着 HumanMessage、带 tool_calls 的中转 AIMessage、ToolMessage 与
    最终 AIMessage；这里把同一轮的正文按出现顺序收进 `blocks`（含 ask 段），工具调用
    与结果归并进 `tool_runs`，供前端用与流式一致的渲染器重建视图。
    """
    row = get_conversation(db, user_id, conversation_id)
    persona = resolve_for_conversation(db, row, user_id)
    config = {"configurable": {"thread_id": str(row.thread_id)}}
    graph = graph_for_user(db, user_id, runtime, persona)
    state = await graph.aget_state(config)
    skills = available_skills(db, user_id, persona.key if persona is not None else None)
    return {
        "conversation_id": row.id,
        "turns": build_turns(
            state.values.get("messages", []), skills, pending_ask=_pending_ask(state),
        ),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _acquire_slot(thread_id: str, client_msg_id: str) -> None:
    async with _state_lock:
        if client_msg_id in _client_msgs:
            raise AppError(409, "请勿重复发送")
        if thread_id in _running:
            raise AppError(409, "该会话正在生成回复")
        _running.add(thread_id)
        _client_msgs[client_msg_id] = thread_id


async def _release_slot(thread_id: str, client_msg_id: str) -> None:
    async with _state_lock:
        _running.discard(thread_id)
        _client_msgs.pop(client_msg_id, None)


async def acquire_reply_slot(db: Session, user_id: int, conversation_id: int, payload):
    """在响应头发送前完成可同步判定的校验与 slot 预占。

    StreamingResponse 会先发 200 头再迭代生成器，若把 400/404/409 留在生成器里，
    头已发出就无法改状态码，只能断连。故提前到构造 StreamingResponse 之前，
    让全局异常处理器返回正确的 JSON 状态码。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    await _acquire_slot(thread_id, payload.client_msg_id)
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
    persona = resolve_for_conversation(db, row, user_id)
    await _acquire_slot(thread_id, payload.client_msg_id)
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph_for_user(db, user_id, runtime, persona).aget_state(config)
    msgs = state.values.get("messages", [])

    if _pending_ask(state):
        await _release_slot(thread_id, payload.client_msg_id)
        raise AppError(409, "当前有等待回答的问题，请先回答或跳过")

    human_idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].type == "human"), None)
    if human_idx is None:
        await _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")
    # 保留最后一条用户消息，仅移除其后的工具中转/上一条 AI 回答；
    # 若把用户消息一并删掉，update_state 后消息为空，条件边会取最后一条而越界。
    removed = msgs[human_idx + 1:]
    has_answer = any(m.type == "ai" and not getattr(m, "tool_calls", None) for m in removed)
    if not has_answer:
        await _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")

    try:
        await graph_for_user(db, user_id, runtime, persona).aupdate_state(
            config,
            {"messages": [RemoveMessage(id=m.id) for m in removed if getattr(m, "id", None)]},
        )
        human_content = msgs[human_idx].content
        if payload.model_name is not None:
            row.model_name = payload.model_name
        db.commit()
    except Exception:
        await _release_slot(thread_id, payload.client_msg_id)
        raise
    return row, thread_id, human_content


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


async def _stream_graph(graph, stream_input, config, skills: list[ResolvedSkill]):
    async for mode, data in graph.astream(
        stream_input,
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            message_chunk, metadata = data
            if metadata.get("langgraph_node") == "agent" and message_chunk.content:
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


async def stream_reply(db: Session, row: AgentConversation, thread_id: str, runtime: dict, payload, human_content: str | None = None, replay: bool = False):
    persona = resolve_for_conversation(db, row, row.user_id)
    skill_scope = persona.key if persona is not None else None
    graph = graph_for_user(db, row.user_id, runtime, persona)
    skills = available_skills(db, row.user_id, skill_scope)
    base_config = {
        "configurable": {
            "thread_id": thread_id,
            "model_name": row.model_name,
            "user_id": row.user_id,
            "conversation_id": row.id,
            "persona_id": persona.id if persona else None,
            "persona_version_no": persona.version_no if persona else None,
            "persona_block": render_persona_block(persona),
        },
        "recursion_limit": 10,
    }
    content = human_content or payload.content
    today = date.today()

    try:
        # 上一轮停在 ask_user 等待回答时，本条消息即答案：用 Command(resume) 从同一
        # thread 继续，不新增 HumanMessage，问答都留在原来那一轮里。
        pending_ask = None
        if not replay:
            state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            pending_ask = _pending_ask(state)

        yield _sse("start", {
            "conversation_id": row.id,
            "thread_id": thread_id,
            "resume": pending_ask is not None,
        })

        if pending_ask is not None:
            pending_store.clear(row.id)
            config = {**base_config, "configurable": {
                **base_config["configurable"], "skill_trigger": "answer",
            }}
            async for event in _stream_graph(graph, Command(resume=content), config, skills):
                yield event
            yield _finish(db, row, None, persona)
            return

        if replay:
            config = {**base_config, "configurable": {**base_config["configurable"], "skill_trigger": "model"}}
            async for event in _stream_graph(graph, {"messages": []}, config, skills):
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
                    skill = find_by_slash(db, row.user_id, token, skill_scope)
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
                            async for event in _stream_graph(graph, None, config, skills):
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
                        async for event in _stream_graph(graph, None, config, skills):
                            yield event

            else:
                config = {**base_config, "configurable": {**base_config["configurable"], "skill_trigger": "model"}}
                async for event in _stream_graph(
                    graph, {"messages": [HumanMessage(content=content)]}, config, skills
                ):
                    yield event

        yield _finish(db, row, content, persona)
    except Exception as exc:
        logger.warning("agent stream failed: conv=%s err=%r", row.id, exc)
        db.rollback()
        yield _sse("error", {"message": "生成失败，请稍后重试"})
    finally:
        await _release_slot(thread_id, payload.client_msg_id)
