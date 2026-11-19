"""健康档案定制问题：多套问题的规范化、落库与答案校验。

由“健康档案测试”角色使用。问题必须声明固定 aspect（见 aspects.py）；
固定题仍由 questions.py 管理。定制题答案 item_key 为 probe_<set_id>_<qN>，
问题定义与答案统一存 health_profile 行，不再使用 JSON 快照。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from uuid import uuid4

from app.core.exceptions import AppError
from app.modules.profile.aspects import ASPECT_KEYS, ASPECT_LABELS, aspect_label

PROBE_PREFIX = "probe_"
PROBE_PERSONA_KEY = "health_profile_test"
DEFAULT_GROUP = ASPECT_LABELS["other"]
MIN_QUESTIONS = 3
MAX_QUESTIONS = 10
MAX_SETS = 20
MIN_ASPECTS = 3
MAX_ASPECT_QUESTIONS = 2
MAX_CYCLE_QUESTIONS = 1
MAX_LABEL_LENGTH = 48
MAX_HINT_LENGTH = 120
MAX_PLACEHOLDER_LENGTH = 120
MIN_ANSWER_LENGTH = 50
MAX_ANSWER_LENGTH = 255

LOCAL_KEY_RE = re.compile(r"^q(?:[1-9]|10)$")


def parse_store(raw) -> dict:
    """把旧 JSON 快照归一为 sets 列表；仅用于迁移兼容，不再作为运行时数据源。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("sets"), list):
        return {"sets": []}
    sets = [
        item for item in raw["sets"]
        if isinstance(item, dict)
        and isinstance(item.get("set_id"), str)
        and item["set_id"]
        and isinstance(item.get("questions"), list)
    ]
    return {"sets": sets[-MAX_SETS:]}


def store_from_entries(entries) -> dict:
    """把 health_profile 行还原成定制问题 store（供页面与 Agent 读取）。

    行按 created_at 升序传入；同一 set 的题按 sort_order 排序。没有 answer 的题也保留，
    这样页面能展示最新一套的未答项，Agent 也能看到用户跳过了什么。
    """
    sets: dict[str, dict] = {}
    for entry in entries or []:
        if getattr(entry, "source", None) != "probe" or not getattr(entry, "set_id", None):
            continue
        set_id = entry.set_id
        item = sets.get(set_id)
        if item is None:
            generated = entry.set_generated_at or entry.created_at
            item = sets[set_id] = {
                "set_id": set_id,
                "persona_key": entry.persona_key or PROBE_PERSONA_KEY,
                "generated_at": generated.isoformat(timespec="seconds") if generated else None,
                "questions": [],
            }
        item_key = entry.item_key
        local_key = item_key[len(PROBE_PREFIX) + len(set_id) + 1 :]
        if not local_key:
            local_key = item_key.rsplit("_", 1)[-1]
        item["questions"].append({
            "key": item_key,
            "local_key": local_key,
            "aspect": entry.aspect,
            "group": aspect_label(entry.aspect),
            "label": entry.label,
            "hint": entry.hint,
            "placeholder": entry.placeholder,
            "max_length": entry.max_length,
            "sort_order": entry.sort_order,
        })
    result = []
    for item in sets.values():
        item["questions"].sort(key=lambda q: q.get("sort_order", 0))
        for question in item["questions"]:
            question.pop("sort_order", None)
        result.append(item)
    return {"sets": result[-MAX_SETS:]}


def latest_set(store: dict) -> dict | None:
    sets = store.get("sets") or []
    return sets[-1] if sets else None


def _text(value, length: int, field: str, *, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise AppError(400, f"{field}须为文本")
    text = value.strip()
    if required and not text:
        raise AppError(400, f"{field}不能为空")
    if len(text) > length:
        raise AppError(400, f"{field}最多 {length} 字")
    return text


def normalize_questions(raw_questions) -> list[dict]:
    """校验并规范化模型/调用方给出的问题；key 只允许 q1~q10。

    每个问题必须声明固定 aspect。整套问题至少覆盖 3 个方面，单方面最多 2 题，
    生理周期最多 1 题，其他最多 1 题；方面不能由模型自由发明。
    """
    if not isinstance(raw_questions, list) or not MIN_QUESTIONS <= len(raw_questions) <= MAX_QUESTIONS:
        raise AppError(400, f"定制问题须为 {MIN_QUESTIONS}~{MAX_QUESTIONS} 个")

    questions: list[dict] = []
    keys: set[str] = set()
    labels: set[str] = set()
    for item in raw_questions:
        if not isinstance(item, dict):
            raise AppError(400, "定制问题格式不正确")
        key = str(item.get("key") or "").strip().lower()
        if not LOCAL_KEY_RE.fullmatch(key):
            raise AppError(400, "定制问题 key 须为 q1~q10")
        if key in keys:
            raise AppError(400, f"定制问题 key 重复：{key}")
        aspect = str(item.get("aspect") or "").strip().lower()
        if aspect not in ASPECT_KEYS:
            raise AppError(
                400,
                "问题 aspect 必须使用固定模板："
                + "、".join(sorted(ASPECT_KEYS)),
            )
        label = _text(item.get("label"), MAX_LABEL_LENGTH, "问题标题", required=True)
        if label in labels:
            raise AppError(400, f"定制问题标题重复：{label}")
        hint = _text(item.get("hint"), MAX_HINT_LENGTH, "问题提示", required=False)
        placeholder = _text(
            item.get("placeholder"), MAX_PLACEHOLDER_LENGTH, "问题占位文案", required=False
        )
        max_length = item.get("max_length", 200)
        if isinstance(max_length, bool) or not isinstance(max_length, int) or not (
            MIN_ANSWER_LENGTH <= max_length <= MAX_ANSWER_LENGTH
        ):
            raise AppError(400, f"问题答案长度须为 {MIN_ANSWER_LENGTH}~{MAX_ANSWER_LENGTH}")

        keys.add(key)
        labels.add(label)
        questions.append({
            "key": key,
            "aspect": aspect,
            "group": aspect_label(aspect),
            "label": label,
            "hint": hint,
            "placeholder": placeholder,
            "max_length": max_length,
        })

    aspect_counts = Counter(question["aspect"] for question in questions)
    if len(aspect_counts) < MIN_ASPECTS:
        raise AppError(400, f"一套问题至少覆盖 {MIN_ASPECTS} 个不同 aspect")
    too_many = [
        aspect for aspect, count in aspect_counts.items()
        if count > MAX_ASPECT_QUESTIONS
    ]
    if too_many:
        raise AppError(
            400,
            "同一 aspect 最多 "
            f"{MAX_ASPECT_QUESTIONS} 题，超限："
            + "、".join(aspect_label(aspect) for aspect in too_many),
        )
    if aspect_counts.get("cycle", 0) > MAX_CYCLE_QUESTIONS:
        raise AppError(400, "生理周期最多 1 题")
    if aspect_counts.get("other", 0) > 1:
        raise AppError(400, "其他方面最多 1 题")
    return questions


def signature(questions: list[dict]) -> tuple:
    return tuple(
        (
            q.get("local_key") or q.get("key"),
            q.get("aspect"),
            q.get("group"),
            q.get("label"),
            q.get("hint"),
            q.get("placeholder"),
            q.get("max_length"),
        )
        for q in questions
    )


def append_set(store: dict, questions: list[dict]) -> tuple[dict, str, list[str]]:
    """追加一套问题，返回新 store、set_id 与被裁掉的历史 set_id。"""
    set_id = uuid4().hex[:10]
    stored = [
        {
            **q,
            "local_key": q["key"],
            "key": f"{PROBE_PREFIX}{set_id}_{q['key']}",
        }
        for q in questions
    ]
    sets = list(store.get("sets") or [])
    sets.append({
        "set_id": set_id,
        "persona_key": PROBE_PERSONA_KEY,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "questions": stored,
    })
    dropped: list[str] = []
    if len(sets) > MAX_SETS:
        dropped = [item["set_id"] for item in sets[: len(sets) - MAX_SETS]]
        sets = sets[-MAX_SETS:]
    return {"sets": sets}, set_id, dropped


def validate_probe_answers(questions: list[dict], answers) -> dict[str, str]:
    """校验工具传来的本地答案（q1~q10），返回去空白后的本地 key → 文本。"""
    if not isinstance(answers, dict):
        raise AppError(400, "answers 须为对象")
    question_map_local = {q["key"]: q for q in questions}
    cleaned: dict[str, str] = {}
    for key, raw in answers.items():
        question = question_map_local.get(key)
        if question is None:
            raise AppError(400, f"未知定制问题：{key}")
        if not isinstance(raw, str):
            raise AppError(400, f"「{question['label']}」的答案须为文本")
        text = raw.strip()
        if not text:
            continue
        if len(text) > question["max_length"]:
            raise AppError(400, f"「{question['label']}」最多 {question['max_length']} 字")
        cleaned[key] = text
    if not cleaned:
        raise AppError(400, "至少回答一题后才能保存")
    return cleaned


def latest_answers(store: dict, answers: dict) -> dict[str, str]:
    """最新一套的 本地 key → 已存答案；只返回有内容的题。"""
    item = latest_set(store)
    if item is None:
        return {}
    return {
        q["local_key"]: answers[q["key"]]
        for q in item["questions"]
        if answers.get(q["key"])
    }


def latest_payload(store: dict) -> dict | None:
    """对外展示的最新一套问题（隐藏内部 local_key）。"""
    item = latest_set(store)
    if item is None:
        return None
    return {
        "set_id": item["set_id"],
        "persona_key": item.get("persona_key") or PROBE_PERSONA_KEY,
        "generated_at": item.get("generated_at"),
        "questions": [
            {k: v for k, v in q.items() if k != "local_key"}
            for q in item.get("questions") or []
        ],
    }


def latest_qa(store: dict, answers: dict) -> list[dict]:
    """给 Agent 读取的最新定制问答（只列已回答项）。"""
    item = latest_set(store)
    if item is None:
        return []
    return [
        {
            "key": q["key"],
            "aspect": q.get("aspect") or "other",
            "group": q.get("group") or DEFAULT_GROUP,
            "label": q["label"],
            "answer": answers[q["key"]],
        }
        for q in item["questions"]
        if answers.get(q["key"])
    ]


def history_qa(store: dict, answers: dict) -> list[dict]:
    """全部历史定制问答，按生成时间倒序（最新在前）。

    每套包含完整问题列表；未回答的题 answer 为空串，供 Agent 观察历史、
    避免重复提问，也能看到用户曾经跳过什么。
    """
    result: list[dict] = []
    for item in reversed(store.get("sets") or []):
        qa = [
            {
                "key": q["key"],
                "aspect": q.get("aspect") or "other",
                "group": q.get("group") or DEFAULT_GROUP,
                "label": q["label"],
                "answer": answers.get(q["key"], ""),
            }
            for q in item.get("questions") or []
        ]
        result.append({
            "set_id": item["set_id"],
            "generated_at": item.get("generated_at"),
            "answered_count": sum(1 for entry in qa if entry["answer"]),
            "total": len(qa),
            "qa": qa,
        })
    return result


def aspect_coverage(store: dict) -> list[dict]:
    """历史定制问题的方面覆盖统计：aspect、出现题数、涉及套数。

    供 Agent 出题前观察哪些固定方面尚未覆盖。旧数据缺 aspect 时归入 other。
    """
    aspects: dict[str, dict] = {}
    for item in store.get("sets") or []:
        seen_in_set: set[str] = set()
        for question in item.get("questions") or []:
            aspect = str(question.get("aspect") or "other")
            if aspect not in ASPECT_KEYS:
                aspect = "other"
            entry = aspects.setdefault(
                aspect,
                {
                    "aspect": aspect,
                    "label": aspect_label(aspect),
                    "question_count": 0,
                    "set_count": 0,
                },
            )
            entry["question_count"] += 1
            if aspect not in seen_in_set:
                entry["set_count"] += 1
                seen_in_set.add(aspect)
    return sorted(
        aspects.values(),
        key=lambda item: (-item["set_count"], -item["question_count"], item["aspect"]),
    )
