"""Agent 工具定义：@tool 包装、身份注入、只读边界。

边界（代码强制，不依赖提示词）：
- user_id 从 RunnableConfig 读取，模型不可填、不可伪造；每个工具内部用独立短 session。
- 工具全部只读，不接受模型生成的 SQL，也不暴露表名 / 列名参数。
- 参数只保留“查什么、查多大范围”：日期范围与条数均可选，不设跨度 / 条数上限。
  - 不传任何范围参数 = 全部历史数据（供用户明确要求全量时使用）。
  - 具体拉多少由模型按用户意图决定（最近 N 天 / 指定区间 / 最近 N 条 / 全量）。
"""
from datetime import date, timedelta
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.core.exceptions import AppError
from database import SessionLocal
from . import queries

BODY_METRIC = Literal[
    "all",
    "height", "weight", "body_fat",
    "neck", "shoulder_width", "arm", "chest", "waist", "hip", "thigh", "calf",
    "target_weight", "target_body_fat",
    "target_arm", "target_chest", "target_waist", "target_hip", "target_thigh", "target_calf",
]
SPORT = Literal["all", "fitness", "swim", "dance"]
STATUS = Literal["all", "planned", "recorded"]
STATE_TYPE = Literal["all", "appetite", "myalgia", "inflammation"]


def _resolve_range(
    start_date: date | None,
    end_date: date | None,
    days_back: int | None,
    today: date,
) -> tuple[date | None, date | None]:
    """统一解析范围：都不传 = 全量（None, None）；days_back = 最近 N 天（含今天）。"""
    if days_back is not None:
        if days_back < 1:
            raise AppError(400, "days_back 需为正整数")
        return today - timedelta(days=days_back - 1), today
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise AppError(400, "start_date 不能晚于 end_date")
        return start_date, end_date
    if start_date is not None or end_date is not None:
        raise AppError(400, "请同时提供 start_date 与 end_date，或改用 days_back")
    return None, None


def _resolve_limit(limit: int | None) -> int | None:
    if limit is not None and limit < 1:
        raise AppError(400, "limit 需为正整数")
    return limit


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
    sport: SPORT = "all",
    config: RunnableConfig = None,
) -> dict:
    """按时间范围统计已完成运动（次数、时长、热量、活跃天数；计划与记录分开计数）。

    可直接给 start_date 与 end_date，或给 days_back 表示最近 N 天（含今天）；
    不传任何时间参数表示统计全部历史数据——只有用户明确要看全部 / 总账时才这样调用。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    with SessionLocal() as db:
        return queries.workout_summary(db, uid, start, end, sport)


@tool
async def get_fitness_records(
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    status: STATUS = "all",
    limit: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取健身计划 / 记录明细：日期、状态、起止时间、时长、心率、热量、备注、动作明细与容量、练后心得。

    范围可选：给 days_back（最近 N 天）或 start_date + end_date；都不传取全部历史。
    limit 可选：只要最近 N 条时传，不传返回范围内全部。问训练内容、容量、动作安排、某段时间练了什么时调用。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    limit = _resolve_limit(limit)
    with SessionLocal() as db:
        return queries.fitness_records(db, uid, start, end, status, limit)


@tool
async def get_swim_records(
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    status: STATUS = "all",
    limit: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取游泳计划 / 记录明细：日期、状态、距离、时长、配速、划频、泳姿、心率、热量、心得。

    范围可选：给 days_back（最近 N 天）或 start_date + end_date；都不传取全部历史。
    limit 可选：问“最近几次”时传 N，问全部游泳数据时不传。问游泳表现、配速、划频、训练量时调用。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    limit = _resolve_limit(limit)
    with SessionLocal() as db:
        return queries.swim_records(db, uid, start, end, status, limit)


@tool
async def get_dance_records(
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    status: STATUS = "all",
    limit: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取舞蹈计划 / 记录明细：日期、状态、舞种、老师、风格、时长、心率、热量、课程评分与心得。

    范围可选：给 days_back 或 start_date + end_date；都不传取全部历史；limit 为可选条数。
    问上过什么课、老师、风格、舞蹈训练量时调用。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    limit = _resolve_limit(limit)
    with SessionLocal() as db:
        return queries.dance_records(db, uid, start, end, status, limit)


@tool
async def get_body_measurements(
    metric: BODY_METRIC = "all",
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取身材数据：metric=all 返回基础 / 期望 / 围度 / 目标四组按日期合并的完整记录；
    指定指标则返回该指标的实测点序列（趋势）。

    范围可选：days_back 或 start_date + end_date；都不传取全部历史测量。
    问体重、体脂率、围度变化、历史身材记录时调用。
    """
    uid = _user_id(config)
    if metric not in queries.BODY_METRIC_WHITELIST and metric != "all":
        raise AppError(400, "不支持该身材指标")
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    with SessionLocal() as db:
        return queries.body_measurements(db, uid, metric, start, end)


@tool
async def get_state_records(
    type: STATE_TYPE = "all",
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    limit: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取状态记录：食欲 appetite / 肌肉疼痛 myalgia / 炎症 inflammation（星级 0~5 可空 + 描述）。

    范围可选：days_back 或 start_date + end_date；都不传取全部历史；limit 为可选条数。
    问某天 / 某段时间的食欲、肌肉酸痛、炎症状态时调用。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    limit = _resolve_limit(limit)
    with SessionLocal() as db:
        return queries.state_records(db, uid, start, end, type, limit)


@tool
async def get_cycle_records(
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """取生理周期数据：参考周期 / 参考经期、月经记录（起止日期与派生长度）、每日疼痛等级、今日所在阶段。

    范围可选，作用于月经记录与疼痛日志；不传取全部历史。
    问经期、周期长度、下次预测、当前阶段、疼痛对训练的影响时调用。男性账号或无记录时返回空。
    """
    uid = _user_id(config)
    start, end = _resolve_range(start_date, end_date, days_back, date.today())
    with SessionLocal() as db:
        return queries.cycle_records(db, uid, start, end)


@tool
async def get_profile_info(config: RunnableConfig = None) -> dict:
    """取当前登录用户的个人基本信息：昵称、性别、年龄、账号状态、注册时间。

    问“我的性别 / 年龄 / 昵称”等基本资料时调用；身高体重等身体数据请用身材工具。
    """
    uid = _user_id(config)
    with SessionLocal() as db:
        return queries.profile_info(db, uid)


ALL_TOOLS = [
    get_workout_summary,
    get_fitness_records,
    get_swim_records,
    get_dance_records,
    get_body_measurements,
    get_state_records,
    get_cycle_records,
    get_profile_info,
]
