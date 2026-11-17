"""斜杠技能参数解析：规则层优先，模型层兜底，统一 normalize + validate。"""
from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.ai.runtime.invoke import AIServiceError, ainvoke_structured
from app.modules.agent.skills.argument import (
    STROKE_LABELS,
    parse_date_value,
    required_fields,
    validate_args,
)
from app.modules.agent.skills.registry import ResolvedSkill, build_args_model
from config import settings

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass
class ParseResult:
    args: dict
    errors: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    should_ask: bool = False


def _num(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text in CN_NUM:
        return CN_NUM[text]
    if text == "半":
        return 1
    return None


def _month_bounds(today: date, offset: int = 0) -> tuple[date, date]:
    year, month = today.year, today.month + offset
    if month < 1:
        year, month = year - 1, 12
    elif month > 12:
        year, month = year + 1, 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def time_hint(text: str, today: date) -> tuple[date | None, date | None, int | None, int | None, bool]:
    """解析时间线索：起止日期、回看天数、次数、是否只说了“最近”。"""
    start = end = None
    days = limit = None
    ambiguous = False

    m = re.search(r"(?:最近|近)\s*(\d+|[一二两三四五六七八九十])\s*天", text)
    if m and (n := _num(m.group(1))):
        days = n
        end = today
        start = today - timedelta(days=n - 1)
    m = re.search(r"(?:最近|近)\s*(\d+|[一二两三四五六七八九十])\s*周", text)
    if m and (n := _num(m.group(1))):
        days = n * 7
        end = today
        start = today - timedelta(days=days - 1)
    m = re.search(r"(?:最近|近)\s*(\d+|一|二|两|三)\s*个?月", text)
    if m and (n := _num(m.group(1))):
        days = n * 30
        end = today
        start = today - timedelta(days=days - 1)
    m = re.search(r"(?:最近|近)\s*(\d+|[一二两三四五六七八九十])\s*次", text)
    if m and (n := _num(m.group(1))):
        limit = n

    if "这个月" in text or "本月" in text:
        start, end = _month_bounds(today)[0], today
    elif "上个月" in text or "上月" in text:
        start, end = _month_bounds(today, -1)
    elif "本周" in text or "这周" in text:
        start = today - timedelta(days=today.weekday())
        end = today
    elif "上周" in text:
        this_monday = today - timedelta(days=today.weekday())
        start, end = this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    elif "前天" in text:
        start = end = today - timedelta(days=2)
    elif "昨天" in text:
        start = end = today - timedelta(days=1)
    elif "今天" in text or "今日" in text:
        start = end = today

    # 显式区间：2026-10-01 到 2026-10-31 / 10月1日到10月31日
    m = re.search(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*(?:到|至|~)\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", text)
    if m:
        start, end = parse_date_value(m.group(1), today), parse_date_value(m.group(2), today)
    else:
        m = re.search(r"(\d{1,2}月\d{1,2}日?)\s*(?:到|至|~)\s*(\d{1,2}月\d{1,2}日?)", text)
        if m:
            start, end = parse_date_value(m.group(1), today), parse_date_value(m.group(2), today)

    if start is None and end is None:
        single = re.search(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", text)
        if single:
            start = end = parse_date_value(single.group(1), today)

    if start is None and days is None and limit is None and re.search(r"最近|近", text):
        ambiguous = True
    return start, end, days, limit, ambiguous


def _param_keys(skill: ResolvedSkill) -> set[str]:
    return set(build_args_model(skill).model_fields)


def _enum_hint(skill: ResolvedSkill, text: str) -> dict:
    result = {}
    keys = _param_keys(skill)
    if "main_stroke" in keys:
        for label, value in STROKE_LABELS.items():
            if label in text:
                result["main_stroke"] = value
                break
    if skill.kind == "declarative":
        from app.modules.agent.skills.definition import parse_definition
        defn = parse_definition(skill.definition)
        for p in defn.params:
            if p.type == "enum":
                for value in p.values:
                    if value and value in text:
                        result[p.key] = value
                        break
    return result


def rule_args(skill: ResolvedSkill, text: str, today: date) -> tuple[dict, bool]:
    keys = _param_keys(skill)
    args: dict = {}
    start, end, days, limit, ambiguous = time_hint(text, today)
    if "start_date" in keys and start is not None:
        args["start_date"] = start
    if "end_date" in keys and end is not None:
        args["end_date"] = end
    if "days_back" in keys:
        if days is not None:
            args["days_back"] = days
        elif start is not None and end is not None:
            args["days_back"] = max((end - start).days + 1, 1)
    if "limit" in keys and limit is not None:
        args["limit"] = limit
    args.update(_enum_hint(skill, text))
    if "include_workout" in keys:
        if re.search(r"不含运动|不看运动|只要体重|无需运动", text):
            args["include_workout"] = False
        elif re.search(r"含运动|包含运动|加上运动", text):
            args["include_workout"] = True

    for key, value in re.findall(r"([a-z_]{2,32})\s*[=:：]\s*([^\s，,。]+)", text):
        if key in keys:
            args[key] = value
    return args, ambiguous


def _param_json(skill: ResolvedSkill) -> str:
    schema = build_args_model(skill).model_json_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = []
    for key, item in props.items():
        bits = [f"- {key}：类型 {item.get('type', 'string')}"]
        bits.append("必填" if key in required else "可选")
        if item.get("enum"):
            bits.append("枚举 " + "/".join(str(v) for v in item["enum"]))
        if item.get("default") is not None:
            bits.append("默认 " + str(item["default"]))
        if item.get("description"):
            bits.append(str(item["description"]))
        lines.append("；".join(bits))
    return "\n".join(lines)


async def parse_skill_args(skill: ResolvedSkill, text: str, today: date) -> ParseResult:
    started = time.perf_counter()
    if skill.kind == "prompt":
        # 提示词技能不抽参数、不追问；用户原文保留在对话消息中
        return ParseResult(
            args={},
            meta={"strategy": "prompt", "model": None, "prompt_version": None,
                  "elapsed_ms": int((time.perf_counter() - started) * 1000), "warnings": []},
        )
    rule, ambiguous = rule_args(skill, text, today)
    required = required_fields(skill)
    warnings: list[str] = []
    strategy = "rule"
    model_args: dict = {}

    # 规则层已经覆盖全部必填且没有“最近”歧义时，不调用模型
    need_model = bool(ambiguous or any(key not in rule for key in required))
    if need_model:
        try:
            schema = build_args_model(skill)
            variables = {
                "today": today.isoformat(),
                "weekday": "周" + "一二三四五六日"[today.weekday()],
                "skill_name": skill.name,
                "skill_description": skill.description,
                "params_json": _param_json(skill),
            }
            parsed = await ainvoke_structured(
                model_name=settings.ai_default_model,
                prompt_id="skill_arg_parse.v1",
                schema=schema,
                input_text=text or "（用户没有补充参数）",
                variables=variables,
                strict=False,
            )
            model_args = parsed.model_dump(exclude_none=True)
            strategy = "model" if not rule else "rule+model"
        except (AIServiceError, Exception) as exc:
            warnings.append(f"模型参数抽取失败：{exc}")

    merged = {**model_args, **rule}
    args, errors, norm_warnings, missing = validate_args(skill, merged, today)
    warnings.extend(norm_warnings)

    # “最近”没说时长，或用户完全没写参数：必须追问，不能拿默认值静默执行
    force_missing = []
    if ambiguous or (not text.strip() and not merged):
        for key in ("limit", "days_back", "start_date", "end_date"):
            if key in _param_keys(skill):
                force_missing.append(key)
                break
    all_missing = list(dict.fromkeys(missing + force_missing))
    should_ask = bool(all_missing or errors)
    if errors:
        strategy = "invalid"

    meta = {
        "model": settings.ai_default_model if strategy != "rule" else None,
        "prompt_version": "skill_arg_parse.v1" if strategy != "rule" else None,
        "strategy": strategy,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "warnings": warnings,
    }
    return ParseResult(args=args, errors=errors, missing=all_missing,
                       warnings=warnings, meta=meta, should_ask=should_ask)


def field_label(skill: ResolvedSkill, key: str) -> str:
    labels = {
        "start_date": "开始日期", "end_date": "结束日期", "days_back": "回看时长",
        "limit": "次数", "main_stroke": "泳姿", "include_workout": "是否附带运动",
    }
    if skill.kind == "declarative":
        from app.modules.agent.skills.definition import parse_definition
        for p in parse_definition(skill.definition).params:
            labels[p.key] = p.label
    return labels.get(key, key)


def build_question(skill: ResolvedSkill, missing: list[str], errors: list[dict]) -> str:
    if errors:
        detail = "；".join(f"{field_label(skill, e['field'])}：{e['reason']}" for e in errors[:3])
        return f"「{skill.name}」的参数需要调整：{detail}。"
    labels = "、".join(field_label(skill, key) for key in missing)
    examples = []
    keys = _param_keys(skill)
    if "start_date" in keys or "end_date" in keys:
        examples.append("“这个月”“最近两周”或“2026-11-01 到 2026-11-16”")
    if "days_back" in keys:
        examples.append("“最近 14 天”")
    if "limit" in keys:
        examples.append("“最近 10 次”")
    if "main_stroke" in keys:
        examples.append("“自由泳”")
    example = f" 可以说{examples[0]}。" if examples else ""
    return f"调用「{skill.name}」还缺{labels}。{example}"


def build_question_for_empty(skill: ResolvedSkill) -> str:
    keys = _param_keys(skill)
    if "start_date" in keys or "end_date" in keys:
        return f"「{skill.name}」要分析哪段时间？可以说“这个月”“最近两周”或具体起止日期。"
    if "limit" in keys:
        return f"「{skill.name}」要复盘最近几次？可以说“最近 10 次”。"
    if "days_back" in keys:
        return f"「{skill.name}」要回看多久？可以说“最近 14 天”。"
    return f"请补充「{skill.name}」需要的参数。"
