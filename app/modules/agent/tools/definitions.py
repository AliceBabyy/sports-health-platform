"""Agent 工具定义：@tool 包装、参数护栏、身份注入。

- user_id 从 RunnableConfig 读取（服务端注入，模型不可填、不可伪造）。
- 每个工具内部用独立短 session 只读查询，自包含、不依赖请求 db 生命周期。
- 安全上限在此强制；工具全部只读，不接受模型生成的 SQL。
"""
from datetime import date, timedelta
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.core.exceptions import AppError
from database import SessionLocal
from . import queries

MAX_RANGE_DAYS = 366
MAX_SWIM_LIMIT = 20


def _resolve_range(start_date, end_date, days_back, today) -> tuple[date, date]:
    if days_back is not None:
        if not 1 <= days_back <= MAX_RANGE_DAYS:
            raise AppError(400, "days_back 需在 1~366 之间")
        return today - timedelta(days=days_back - 1), today
    if start_date is None or end_date is None:
        raise AppError(400, "需提供 start_date 与 end_date，或提供 days_back")
    if start_date > end_date:
        raise AppError(400, "start_date 不能晚于 end_date")
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise AppError(400, "日期跨度不能超过 366 天")
    return start_date, end_date


def _user_id(config: RunnableConfig) -> int:
    uid = config.get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法查询个人数据")
    return uid


@tool
async def get_workout_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    sport: Literal["all", "fitness", "swim", "dance"] = "all",
    config: RunnableConfig = None,
) -> dict:
    """按时间范围统计已完成运动（次数、时长、热量；计划与记录分开计数）。需要用户真实运动数据时调用。

    可直接给 start_date 与 end_date，或给 days_back 表示最近 N 天。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    with SessionLocal() as db:
        return queries.workout_summary(db, uid, start, end, sport)


@tool
async def get_recent_swims(
    limit: int = 10,
    config: RunnableConfig = None,
) -> dict:
    """取最近 N 次已完成游泳记录（距离、时长、配速、划频，按日期倒序）。问游泳表现时调用。"""
    uid = _user_id(config)
    if not 1 <= limit <= MAX_SWIM_LIMIT:
        raise AppError(400, "limit 需在 1~20 之间")
    with SessionLocal() as db:
        return queries.recent_swims(db, uid, limit)


@tool
async def get_body_measurements(
    metric: Literal["weight", "body_fat", "arm", "chest", "waist", "hip", "thigh", "calf"],
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """按时间范围取某项身材实测指标的趋势点。问体重、围度等变化时调用。"""
    uid = _user_id(config)
    if metric not in queries.BODY_METRIC_WHITELIST:
        raise AppError(400, "不支持该身材指标")
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    with SessionLocal() as db:
        return queries.body_measurements(db, uid, metric, start, end)


ALL_TOOLS = [get_workout_summary, get_recent_swims, get_body_measurements]
