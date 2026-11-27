"""平台内置技能（代码实现）：减重分析、游泳复盘、10 个健康档案专项。

平台技能只读、不接受用户改定义；输入参数经 Pydantic 校验，查询复用只读工具层。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.modules.agent.tools import queries
from app.modules.body.models import BodyBasicGoalRecord
from app.modules.profile.aspect_skills import ASPECT_SKILLS
from app.modules.profile.skill_runtime import run_profile_aspect


class LoseWeightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = Field(default=None, description="开始日期，可空")
    end_date: date | None = Field(default=None, description="结束日期，可空")
    days_back: int = Field(default=28, ge=1, le=3650, description="未给起止日期时回看的天数")
    include_workout: bool = Field(default=True, description="是否附带运动消耗")

    @model_validator(mode="after")
    def check_range(self):
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date 与 end_date 必须同时提供或同时为空")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class RecentSwimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=50, description="最近 N 次游泳记录")
    main_stroke: str | None = Field(default=None, description="泳姿：freestyle/breaststroke/backstroke/butterfly/mixed")
    days_back: int | None = Field(default=None, ge=1, le=3650, description="可选回看天数")

    @model_validator(mode="after")
    def check_stroke(self):
        if self.main_stroke not in (None, "freestyle", "breaststroke", "backstroke", "butterfly", "mixed"):
            raise ValueError("泳姿不合法")
        return self


class ProfileAspectIn(BaseModel):
    """档案专项 skill 参数：只决定补缺口还是复核更新，不接收题目内容。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["补齐", "更新"] = Field(
        default="补齐",
        description="补齐=只问未答或不足的题；更新=逐题复核已有答案，只问需要修正或新增的题",
    )


def _resolve_period(start: date | None, end: date | None, days_back: int) -> tuple[date, date]:
    if start and end:
        return start, end
    end = date.today()
    return end - timedelta(days=days_back - 1), end


def _output(key: str, label: str, value, unit: str | None = None) -> dict:
    if isinstance(value, float):
        value = round(value, 2)
    display = "—" if value is None else (f"{value}{unit}" if unit else _fmt(value))
    return {"key": key, "label": label, "value": value, "unit": unit, "display": display}


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def run_lose_weight(db: Session, user_id: int, args: LoseWeightIn) -> dict:
    start, end = _resolve_period(args.start_date, args.end_date, args.days_back)
    points_data = queries.body_measurements(db, user_id, "weight", start, end)
    points = points_data["points"]
    baseline_data = queries.body_measurements(db, user_id, "weight", None, start - timedelta(days=1))
    baseline_points = baseline_data["points"]
    baseline = baseline_points[-1]["value"] if baseline_points else (points[0]["value"] if points else None)
    target_row = (
        db.query(BodyBasicGoalRecord)
        .filter(BodyBasicGoalRecord.user_id == user_id, BodyBasicGoalRecord.target_weight_kg.isnot(None))
        .order_by(BodyBasicGoalRecord.record_date.desc(), BodyBasicGoalRecord.id.desc())
        .first()
    )
    target = float(target_row.target_weight_kg) if target_row and target_row.target_weight_kg is not None else None
    fat_points = queries.body_measurements(db, user_id, "body_fat", start, end)["points"]
    workout = queries.workout_summary(db, user_id, start, end, "all") if args.include_workout else None

    if not points:
        return {
            "status": "insufficient_data",
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "sample_size": 0,
            "outputs": [],
            "facts": {"sample_size": 0},
            "summary": f"{start.isoformat()} ~ {end.isoformat()} 没有体重记录，无法分析减重趋势。",
            "caveats": ["区间内没有体重实测点；请先记录体重，或放宽日期范围"],
        }

    latest = points[-1]["value"]
    change = latest - baseline if baseline is not None else None
    pct = (change / baseline * 100) if baseline not in (None, 0) and change is not None else None
    span_days = (date.fromisoformat(points[-1]["date"]) - date.fromisoformat(points[0]["date"])).days
    weekly = (change / max(span_days / 7, 1)) if change is not None else None
    fat_change = (fat_points[-1]["value"] - fat_points[0]["value"]) if len(fat_points) >= 2 else None
    outputs = [
        _output("baseline_weight", "基线体重", baseline, "kg"),
        _output("latest_weight", "最新体重", latest, "kg"),
        _output("weight_change", "区间变化", change, "kg"),
        _output("weight_change_pct", "变化幅度", pct, "%"),
        _output("weekly_rate", "周均变化", weekly, "kg/周"),
        _output("fat_change", "体脂变化", fat_change, "%"),
        _output("sample_count", "体重测量次数", len(points), "次"),
    ]
    if target is not None:
        outputs.append(_output("target_gap", "距目标体重", latest - target, "kg"))
    if workout:
        outputs.append(_output("workout_minutes", "运动时长", workout["total"]["minutes"], "分钟"))
        outputs.append(_output("workout_kcal", "运动消耗", workout["total"]["kcal"], "千卡"))

    caveats = []
    if len(points) < 3:
        caveats.append(f"体重仅 {len(points)} 个实测点，趋势仅供参考")
    if baseline_points:
        caveats.append("基线取开始日期之前最近一次体重")
    else:
        caveats.append("开始日期前无体重记录，基线改用区间首个实测点")
    if fat_change is None:
        caveats.append("区间内体脂测量不足 2 次，未计算体脂变化")

    summary = (
        f"体重由 {_fmt(baseline)}kg 变为 {_fmt(latest)}kg，"
        f"变化 {_fmt(change)}kg（{_fmt(pct)}%），周均 {_fmt(weekly)}kg。"
        if baseline is not None and change is not None else
        f"区间内体重最新为 {_fmt(latest)}kg，基线数据不足。"
    )
    if target is not None:
        summary += f" 距目标体重还差 {_fmt(latest - target)}kg。"
    return {
        "status": "ok",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "sample_size": len(points),
        "outputs": outputs,
        "facts": {
            "sample_size": len(points),
            "fat_sample_size": len(fat_points),
            "workout": workout["total"] if workout else None,
            "target_weight_kg": target,
        },
        "summary": summary,
        "caveats": caveats,
    }


def run_recent_swim(db: Session, user_id: int, args: RecentSwimIn) -> dict:
    end = date.today()
    start = end - timedelta(days=args.days_back - 1) if args.days_back else None
    fetch_limit = args.limit * 5 if args.main_stroke else args.limit
    data = queries.swim_records(db, user_id, start, end, status="recorded", limit=fetch_limit)
    records = data["records"]
    if args.main_stroke:
        records = [r for r in records if r.get("main_stroke") == args.main_stroke][: args.limit]

    if not records:
        return {
            "status": "insufficient_data",
            "range": {"start": start.isoformat() if start else None, "end": end.isoformat()},
            "sample_size": 0,
            "outputs": [],
            "facts": {"sample_size": 0},
            "summary": "没有符合条件的游泳记录，无法复盘。",
            "caveats": ["最近区间内没有已完成的游泳记录；可放宽次数或泳姿条件"],
        }

    total_distance = sum(r.get("distance_m") or 0 for r in records)
    total_duration = sum(r.get("duration_s") or 0 for r in records)
    paces = [r["pace"] for r in records if isinstance(r.get("pace"), (int, float)) and r["pace"]]
    weighted_pace = round((total_duration / 60) / (total_distance / 100), 2) if total_distance else None
    best, worst = (min(paces), max(paces)) if paces else (None, None)
    hearts = [r["avg_heart_rate"] for r in records if isinstance(r.get("avg_heart_rate"), (int, float))]
    kcal = sum(r.get("calories") or 0 for r in records)
    stroke_labels = {r.get("main_stroke"): r.get("main_stroke_label") for r in records}
    stroke_counts: dict[str, int] = {}
    for r in records:
        label = r.get("main_stroke_label") or "未填写"
        stroke_counts[label] = stroke_counts.get(label, 0) + 1

    outputs = [
        _output("sample_count", "记录次数", len(records), "次"),
        _output("total_distance", "总距离", total_distance, "米"),
        _output("total_duration", "总时长", round(total_duration / 60, 1), "分钟"),
        _output("weighted_pace", "加权配速", weighted_pace, "分/100米"),
        _output("best_pace", "最好配速", best, "分/100米"),
        _output("worst_pace", "最差配速", worst, "分/100米"),
        _output("avg_heart_rate", "平均心率", round(sum(hearts) / len(hearts), 0) if hearts else None, "次/分"),
        _output("calories", "总消耗", round(kcal, 1), "千卡"),
    ]
    if args.main_stroke:
        outputs.append(_output("stroke_mix", "泳姿分布", list(stroke_counts.keys())[0] if stroke_counts else "—"))

    first_date = min(r["date"] for r in records)
    last_date = max(r["date"] for r in records)
    caveats = []
    if len(records) < 3:
        caveats.append(f"仅 {len(records)} 次记录，配速波动可能不代表稳定水平")
    if len(paces) < len(records):
        caveats.append("部分记录缺少配速，已按有值记录计算最好/最差配速")
    if not hearts:
        caveats.append("记录中没有平均心率，未给出心率对比")

    summary = (
        f"最近 {len(records)} 次游泳共 {_fmt(total_distance)} 米、{_fmt(round(total_duration / 60, 1))} 分钟，"
        f"加权配速 {_fmt(weighted_pace)} 分/100米。"
    )
    if best is not None:
        summary += f" 最好 {_fmt(best)}，最差 {_fmt(worst)}。"
    return {
        "status": "ok",
        "range": {"start": first_date, "end": last_date},
        "sample_size": len(records),
        "outputs": outputs,
        "facts": {
            "sample_size": len(records),
            "total_distance_m": total_distance,
            "total_duration_s": total_duration,
            "stroke_counts": stroke_counts,
            "stroke_labels": stroke_labels,
        },
        "summary": summary,
        "caveats": caveats,
    }


@dataclass(frozen=True)
class CodeSkill:
    key: str
    name: str
    description: str
    category: str
    version: int
    input_model: type[BaseModel]
    run: Callable[[Session, int, BaseModel], dict]
    slash_alias: str | None = None


CODE_SKILLS: dict[str, CodeSkill] = {
    "lose_weight_analyse": CodeSkill(
        "lose_weight_analyse", "减重分析",
        "分析指定区间体重变化、体脂变化、周均速度与运动消耗，并给出目标体重差距。",
        "body", 1, LoseWeightIn, run_lose_weight,
    ),
    "recent_swim_review": CodeSkill(
        "recent_swim_review", "游泳复盘",
        "复盘最近 N 次已完成的游泳记录：距离、时长、加权配速、最好/最差配速、心率与泳姿分布。",
        "swim", 1, RecentSwimIn, run_recent_swim,
    ),
}


def _profile_runner(skill_key: str):
    def run(db: Session, user_id: int, args: ProfileAspectIn) -> dict:
        return run_profile_aspect(db, user_id, skill_key, args.mode)
    return run


for _item in ASPECT_SKILLS:
    CODE_SKILLS[_item["key"]] = CodeSkill(
        key=_item["key"],
        name=_item["name"],
        description=_item["description"],
        category="profile",
        version=1,
        input_model=ProfileAspectIn,
        run=_profile_runner(_item["key"]),
        slash_alias=_item["slash_alias"],
    )
