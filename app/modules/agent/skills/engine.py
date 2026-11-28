"""声明式技能执行器：按白名单数据源取数，执行聚合步骤与安全表达式。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.access import is_female
from app.modules.agent.skills.definition import DeclarativeDefinition, SkillSource
from app.modules.agent.skills.expression import ExpressionError, evaluate
from app.modules.agent.tools import queries
from app.modules.auth.models import User


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _source_range(source: SkillSource, params: dict) -> tuple[date | None, date | None]:
    def resolve(end: Any) -> date | None:
        if end is None:
            return None
        if isinstance(end, str) and end.startswith("$"):
            return _as_date(params.get(end[1:]))
        return date.fromisoformat(end)

    return resolve(source.range_start), resolve(source.range_end)


def _source_limit(source: SkillSource, params: dict) -> int | None:
    if source.limit is None:
        return None
    if isinstance(source.limit, str) and source.limit.startswith("$"):
        value = params.get(source.limit[1:])
        return int(value) if value is not None else None
    return int(source.limit)


def _load_source(db: Session, user_id: int, source: SkillSource, params: dict) -> tuple[Any, dict]:
    start, end = _source_range(source, params)
    limit = _source_limit(source, params)
    if source.type == "body_metric":
        data = queries.body_measurements(db, user_id, source.metric, start, end)
        return data["points"], {"count": data["sample_count"], "range": data["range"],
                                "label": data["label"], "unit": data["unit"]}
    if source.type == "workout_summary":
        data = queries.workout_summary(db, user_id, start, end, source.sport or "all")
        return data, {"count": data["total"]["records"], "range": data["range"]}
    if source.type == "swim_records":
        data = queries.swim_records(db, user_id, start, end, status="recorded", limit=limit)
        return data["records"], {"count": data["count"], "range": data["range"]}
    if source.type == "fitness_records":
        data = queries.fitness_records(db, user_id, start, end, status="recorded", limit=limit)
        return data["records"], {"count": data["count"], "range": data["range"]}
    if source.type == "dance_records":
        data = queries.dance_records(db, user_id, start, end, status="recorded", limit=limit)
        return data["records"], {"count": data["count"], "range": data["range"]}
    if source.type == "state_records":
        data = queries.state_records(db, user_id, start, end, state_type=source.state_type or "all", limit=limit)
        return data["records"], {"count": data["count"], "range": data["range"]}
    if source.type == "cycle_records":
        user = db.get(User, user_id)
        if user is None or not is_female(user.gender):
            raise ValueError("生理周期数据源仅女性账号可用")
        data = queries.cycle_records(db, user_id, start, end)
        return data, {"count": data["period_count"], "range": data["range"]}
    if source.type == "profile_info":
        data = queries.profile_info(db, user_id)
        return data, {"count": 1, "range": {"start": None, "end": None}}
    raise ValueError("不支持的数据源类型")


def _sorted_records(records: list[dict]) -> list[dict]:
    if records and all("date" in r for r in records if isinstance(r, dict)):
        return sorted(records, key=lambda r: (str(r.get("date") or ""), r.get("id") or 0))
    return records


def _numbers(records: list[dict], field: str) -> list[float]:
    values = []
    for record in records:
        value = record.get(field) if isinstance(record, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _run_step(step, sources: dict, warnings: list[str]) -> Any:
    raw = sources.get(step.source)
    if raw is None:
        warnings.append(f"步骤 {step.key} 的数据源为空")
        return None
    if step.op in ("count", "group_count", "first", "last"):
        records = _sorted_records(raw) if isinstance(raw, list) else None
        if records is None:
            warnings.append(f"步骤 {step.key} 需要列表型数据源")
            return None
        if step.op == "count":
            return len(records)
        if step.op == "first":
            return records[0] if records else None
        if step.op == "last":
            return records[-1] if records else None
        if step.op == "group_count":
            result: dict[str, int] = {}
            for row in records:
                value = row.get(step.field)
                key = "未填写" if value in (None, "") else str(value)
                result[key] = result.get(key, 0) + 1
            return result
    if not isinstance(raw, list):
        warnings.append(f"步骤 {step.key} 需要列表型数据源")
        return None
    records = _sorted_records(raw)
    if step.op == "sum":
        return sum(_numbers(records, step.field))
    if step.op == "avg":
        values = _numbers(records, step.field)
        return round(sum(values) / len(values), 4) if values else None
    if step.op == "min":
        values = _numbers(records, step.field)
        return min(values) if values else None
    if step.op == "max":
        values = _numbers(records, step.field)
        return max(values) if values else None
    raise ValueError("不支持的步骤算子")


def _display_value(value: Any, unit: str | None = None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    elif isinstance(value, dict):
        text = " · ".join(f"{k} {v}" for k, v in value.items())
    else:
        text = str(value)
    return f"{text}{unit or ''}"


def _round_output(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    return value


def execute_declarative(db: Session, user_id: int, defn: DeclarativeDefinition, params: dict) -> dict:
    warnings: list[str] = []
    sources: dict[str, Any] = {}
    source_meta: dict[str, dict] = {}
    for source in defn.sources:
        value, meta = _load_source(db, user_id, source, params)
        sources[source.key] = value
        source_meta[source.key] = meta

    steps: dict[str, Any] = {}
    for step in defn.steps:
        try:
            steps[step.key] = _run_step(step, sources, warnings)
        except ExpressionError as exc:
            warnings.append(f"步骤 {step.key} 计算失败：{exc}")
            steps[step.key] = None

    ctx = {"params": params, "sources": sources, "steps": steps}
    outputs = []
    for output in defn.outputs:
        try:
            value = evaluate(output.value, ctx)
        except ExpressionError as exc:
            warnings.append(f"输出 {output.label} 计算失败：{exc}")
            value = None
        value = _round_output(value)
        if value is None:
            warnings.append(f"输出「{output.label}」样本不足，未能计算")
        outputs.append({
            "key": output.key,
            "label": output.label,
            "value": value,
            "unit": output.unit,
            "display": _display_value(value, output.unit),
        })

    output_map = {o["key"]: o["display"] for o in outputs}
    try:
        summary = defn.summary.format(**output_map)
    except (KeyError, ValueError):
        summary = defn.summary

    list_counts = [m["count"] for m in source_meta.values() if m.get("range") and m.get("count")]
    sample_size = max(list_counts) if list_counts else max((m.get("count", 0) for m in source_meta.values()), default=0)
    if sample_size == 0:
        warnings.append("区间内没有可用记录，无法给出有效结论")

    ranges = [m.get("range") for m in source_meta.values() if m.get("range")]
    starts = [r["start"] for r in ranges if r.get("start")]
    ends = [r["end"] for r in ranges if r.get("end")]
    merged_range = {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
    }
    caveats = list(dict.fromkeys(warnings))
    if 0 < sample_size < 3:
        caveats.append(f"样本仅 {sample_size} 条，趋势仅供参考")

    status = "ok" if sample_size > 0 and any(o["value"] is not None for o in outputs) else "insufficient_data"
    return {
        "status": status,
        "range": merged_range,
        "sample_size": sample_size,
        "outputs": outputs,
        "facts": {
            "sample_size": sample_size,
            "source_counts": {k: v.get("count", 0) for k, v in source_meta.items()},
            "outputs": {o["key"]: o["value"] for o in outputs},
        },
        "summary": summary,
        "caveats": caveats,
    }
