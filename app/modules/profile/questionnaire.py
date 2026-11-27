"""健康档案专项问答的通用校验与视图组装。

只做轻量结构约束，不写死题库、不强制覆盖多个 aspect：
- 每套 3~6 题，题号 q1~q6；
- 每题的 aspect 必须在该专项 skill 允许的范围内（由调用方传入 allowed_aspects）；
- 至少 1 题有答案；答案长度受每题 max_length 限制；
- 同一用户同一专项保留最近 3 套，页面只展示最近一套。

题目内容始终由 AI 在专项提示词约束下现场生成，本模块不提供固定题。
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from typing import Any, Iterable

MIN_QUESTIONS = 3
MAX_QUESTIONS = 6
MAX_SETS_PER_SKILL = 3
MAX_LABEL_LENGTH = 48
MAX_HINT_LENGTH = 120
MAX_PLACEHOLDER_LENGTH = 120
MIN_ANSWER_LENGTH = 50
MAX_ANSWER_LENGTH = 255
LOCAL_KEY_RE = re.compile(r"^q[1-6]$")


def _value(item: Any, name: str, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def new_set_id() -> str:
    return secrets.token_hex(6)


def normalize_questions(raw_questions: Iterable[Any], allowed_aspects: frozenset[str]) -> list[dict]:
    """校验 AI 生成的一套问题；返回可直接落库的题目列表。"""
    items = list(raw_questions or [])
    if not MIN_QUESTIONS <= len(items) <= MAX_QUESTIONS:
        raise ValueError(f"一套题需要 {MIN_QUESTIONS}~{MAX_QUESTIONS} 道")

    normalized: list[dict] = []
    seen_keys: set[str] = set()
    seen_labels: set[str] = set()
    for index, raw in enumerate(items):
        key = str(_value(raw, "key") or _value(raw, "local_key") or "").strip().lower()
        if not LOCAL_KEY_RE.fullmatch(key):
            raise ValueError("题号只能使用 q1~q6")
        if key in seen_keys:
            raise ValueError(f"题号重复：{key}")
        seen_keys.add(key)

        aspect = str(_value(raw, "aspect") or "").strip()
        if aspect not in allowed_aspects:
            allowed = "、".join(sorted(allowed_aspects))
            raise ValueError(f"aspect“{aspect}”不属于本专项，可选：{allowed}")

        label = str(_value(raw, "label") or "").strip()
        if not 1 <= len(label) <= MAX_LABEL_LENGTH:
            raise ValueError(f"第 {index + 1} 题标题需为 1~{MAX_LABEL_LENGTH} 字")
        if label in seen_labels:
            raise ValueError(f"题目标题重复：{label}")
        seen_labels.add(label)

        hint = str(_value(raw, "hint") or "").strip()
        placeholder = str(_value(raw, "placeholder") or "").strip()
        if len(hint) > MAX_HINT_LENGTH:
            raise ValueError(f"第 {index + 1} 题填写提示最多 {MAX_HINT_LENGTH} 字")
        if len(placeholder) > MAX_PLACEHOLDER_LENGTH:
            raise ValueError(f"第 {index + 1} 题占位文案最多 {MAX_PLACEHOLDER_LENGTH} 字")

        max_length = _value(raw, "max_length", 200)
        try:
            max_length = int(max_length)
        except (TypeError, ValueError):
            raise ValueError(f"第 {index + 1} 题答案长度上限必须是整数") from None
        if not MIN_ANSWER_LENGTH <= max_length <= MAX_ANSWER_LENGTH:
            raise ValueError(
                f"第 {index + 1} 题答案长度上限需在 {MIN_ANSWER_LENGTH}~{MAX_ANSWER_LENGTH} 之间"
            )

        normalized.append({
            "local_key": key,
            "aspect": aspect,
            "label": label,
            "hint": hint,
            "placeholder": placeholder,
            "max_length": max_length,
            "sort_order": index,
        })
    return normalized


def validate_answers(questions: list[dict], answers: dict[str, str] | None) -> dict[str, str]:
    """校验用户答案；只保留有内容的题，至少 1 题有答案。"""
    raw = answers or {}
    if not isinstance(raw, dict):
        raise ValueError("answers 必须是题号到文本的对象")
    question_map = {q["local_key"]: q for q in questions}
    unknown = sorted(set(raw) - set(question_map))
    if unknown:
        raise ValueError(f"答案包含未知题号：{'、'.join(unknown)}")

    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} 的答案必须是文本")
        text = value.strip()
        if not text:
            continue
        if len(text) > question_map[key]["max_length"]:
            raise ValueError(
                f"{key} 的答案最多 {question_map[key]['max_length']} 字"
            )
        cleaned[key] = text
    if not cleaned:
        raise ValueError("至少需要 1 题有答案")
    return cleaned


def question_signature(questions: list[dict]) -> str:
    payload = [
        {
            "key": q["local_key"],
            "aspect": q["aspect"],
            "label": q["label"],
            "hint": q["hint"],
            "placeholder": q["placeholder"],
            "max_length": q["max_length"],
        }
        for q in sorted(questions, key=lambda item: item["local_key"])
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _entry_dict(entry) -> dict:
    return {
        "local_key": entry.local_key,
        "aspect": entry.aspect,
        "group": entry.aspect,
        "label": entry.label,
        "hint": entry.hint,
        "placeholder": entry.placeholder,
        "max_length": entry.max_length,
        "answer": (entry.answer or "").strip(),
        "sort_order": entry.sort_order,
    }


def sets_from_entries(entries: Iterable[Any]) -> list[dict]:
    """把行式存储聚合成套装视图；只聚合同 skill_key + set_id 的新档案。"""
    grouped: dict[str, dict] = {}
    for entry in entries:
        set_id = getattr(entry, "set_id", None)
        skill_key = getattr(entry, "skill_key", None)
        if not set_id or not skill_key:
            continue
        group = grouped.get(set_id)
        if group is None:
            generated_at = getattr(entry, "set_generated_at", None) or getattr(entry, "created_at", None)
            if not isinstance(generated_at, datetime):
                continue
            group = {
                "set_id": set_id,
                "skill_key": skill_key,
                "generated_at": generated_at,
                "questions": [],
            }
            grouped[set_id] = group
        group["questions"].append(_entry_dict(entry))

    sets = list(grouped.values())
    for item in sets:
        item["questions"].sort(key=lambda q: (q["sort_order"], q["local_key"]))
        for question in item["questions"]:
            from app.modules.profile.aspects import aspect_label
            question["group"] = aspect_label(question["aspect"])
    sets.sort(key=lambda item: (item["generated_at"], item["set_id"]))
    return sets


def latest_set(sets: list[dict], skill_key: str | None = None) -> dict | None:
    candidates = [s for s in sets if skill_key is None or s["skill_key"] == skill_key]
    return candidates[-1] if candidates else None


def latest_sets_by_skill(sets: list[dict]) -> list[dict]:
    """每个专项只取最近一套，并按专项固定顺序返回。"""
    from app.modules.profile.aspect_skills import ASPECT_SKILLS

    latest = {s["skill_key"]: s for s in sets}
    order = {item["key"]: item["sort_order"] for item in ASPECT_SKILLS}
    return sorted(
        latest.values(),
        key=lambda item: (order.get(item["skill_key"], 999), item["set_id"]),
    )


def history_for_skill(sets: list[dict], skill_key: str) -> list[dict]:
    return [s for s in sets if s["skill_key"] == skill_key][-MAX_SETS_PER_SKILL:]


def set_qa(question_set: dict, *, answered_only: bool = False) -> list[dict]:
    rows = question_set["questions"]
    if answered_only:
        rows = [q for q in rows if q["answer"]]
    return [
        {
            "local_key": q["local_key"],
            "aspect": q["aspect"],
            "group": q["group"],
            "label": q["label"],
            "answer": q["answer"],
        }
        for q in rows
    ]


def question_count(question_set: dict) -> int:
    return len(question_set["questions"])


def answered_count(question_set: dict) -> int:
    return sum(1 for q in question_set["questions"] if q["answer"])
