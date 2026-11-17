"""参数归一化与校验：规则层/模型层输出统一在这里转成可执行参数。"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.modules.agent.skills.definition import (
    DefinitionInvalid,
    parse_any_definition,
    parse_definition,
)
from app.modules.agent.skills.registry import ResolvedSkill, build_args_model

STROKE_LABELS = {
    "自由泳": "freestyle", "蛙泳": "breaststroke", "仰泳": "backstroke",
    "蝶泳": "butterfly", "混合泳": "mixed", "混合": "mixed",
}
SPORT_LABELS = {"健身": "fitness", "游泳": "swim", "舞蹈": "dance"}
BOOL_TRUE = {"是", "true", "1", "yes", "需要", "包含"}
BOOL_FALSE = {"否", "false", "0", "no", "不需要", "不包含"}


def _chinese_date(text: str, today: date) -> date | None:
    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            return date(today.year, month, day)
        except ValueError:
            return None
    return None


def parse_date_value(value: Any, today: date) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text in ("今天", "今日"):
        return today
    if text == "昨天":
        return today - timedelta(days=1)
    if text == "前天":
        return today - timedelta(days=2)
    chinese = _chinese_date(text, today)
    if chinese:
        return chinese
    text = text.replace("/", "-").replace(".", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _field_types(skill: ResolvedSkill) -> dict[str, str]:
    if skill.kind in ("code", "prompt"):
        model = build_args_model(skill)
        types = {}
        for name, field in model.model_fields.items():
            annotation = str(field.annotation)
            if "date" in annotation:
                types[name] = "date"
            elif "int" in annotation:
                types[name] = "int"
            elif "bool" in annotation:
                types[name] = "bool"
            else:
                types[name] = "str"
        return types
    defn = parse_definition(skill.definition)
    return {p.key: p.type for p in defn.params}


def normalize_args(skill: ResolvedSkill, raw: dict, today: date) -> tuple[dict, list[str], list[dict]]:
    """把模型/规则输出清洗成业务格式；错误以 {field, reason} 返回。"""
    warnings: list[str] = []
    errors: list[dict] = []
    result: dict[str, Any] = {}
    types = _field_types(skill)
    raw = raw or {}
    for key, value in raw.items():
        if key not in types:
            warnings.append(f"忽略未声明参数 {key}")
            continue
        if value is None or value == "":
            continue
        value_type = types[key]
        if value_type == "date":
            parsed = parse_date_value(value, today)
            if value not in (None, "") and parsed is None:
                errors.append({"field": key, "reason": "日期格式无效，请用 YYYY-MM-DD 或“这个月”等说法"})
                continue
            result[key] = parsed
        elif value_type == "int":
            if value in (None, ""):
                result[key] = None
                continue
            try:
                result[key] = int(value)
            except (TypeError, ValueError):
                errors.append({"field": key, "reason": "需要整数"})
        elif value_type == "bool":
            if isinstance(value, bool):
                result[key] = value
            elif value is None or value == "":
                result[key] = None
            elif str(value).strip().lower() in BOOL_TRUE:
                result[key] = True
            elif str(value).strip().lower() in BOOL_FALSE:
                result[key] = False
            else:
                errors.append({"field": key, "reason": "需要布尔值"})
        else:
            text = "" if value is None else str(value).strip()
            result[key] = STROKE_LABELS.get(text, SPORT_LABELS.get(text, text))
    return result, warnings, errors


def required_fields(skill: ResolvedSkill) -> list[str]:
    if skill.kind == "prompt":
        return []
    if skill.kind == "code":
        model = build_args_model(skill)
        return [name for name, field in model.model_fields.items() if field.is_required()]
    defn = parse_definition(skill.definition)
    return [p.key for p in defn.params if p.required]


def validate_args(skill: ResolvedSkill, args: dict, today: date) -> tuple[dict, list[dict], list[str], list[str]]:
    """归一化 + 必填检查 + 模型/范围校验；返回 args/errors/warnings/missing。"""
    normalized, warnings, errors = normalize_args(skill, args, today)
    if errors:
        return normalized, errors, warnings, []

    missing = [key for key in required_fields(skill) if normalized.get(key) in (None, "")]
    if missing:
        return normalized, [], warnings, missing

    model = build_args_model(skill)
    try:
        instance = model(**normalized)
    except ValidationError as exc:
        for item in exc.errors():
            field = ".".join(str(p) for p in item.get("loc", ())) or "args"
            errors.append({"field": field, "reason": item.get("msg", "参数无效")})
        return normalized, errors, warnings, []
    dumped = instance.model_dump()
    # 去掉未提供的可选参数，避免工具参数里出现一堆 null
    dumped = {k: v for k, v in dumped.items() if v is not None}
    return dumped, [], warnings, []


def definition_errors(skill: ResolvedSkill) -> tuple[list[dict], list[str]]:
    if skill.kind == "code":
        return [], []
    try:
        parse_any_definition(skill.kind, skill.definition)
        return [], []
    except DefinitionInvalid as exc:
        return exc.errors, []
