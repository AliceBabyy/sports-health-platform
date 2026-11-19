"""任务注册表：job_key → 执行函数 + 参数 schema + 默认排期。

数据库只存 job_key 与表达式，不存 callable：重构函数名、挪模块都不会让已存任务失效。
新增任务只需在这里加一条，管理页与调度器会自动出现。
"""
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import AppError


class EmptyParams(BaseModel):
    """无参数任务：禁止额外字段，避免页面传入意料之外的参数。"""

    model_config = ConfigDict(extra="forbid")


class ScanParams(BaseModel):
    """兜底扫描参数：单次最多处理的周期数。"""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=1000)


@dataclass(frozen=True)
class JobSpec:
    key: str
    name: str
    desc: str
    func: Callable[[Any, dict], dict]
    params_schema: type[BaseModel] = EmptyParams
    # 互斥域：同域任务不会并发执行；空则用 job_key 自身（如三条报告任务共用 "report"）
    lock_scope: str = ""
    # 默认排期：为 None 表示仅在页面/命令行手动执行，不自动注册定时任务
    default_trigger_type: str | None = None
    default_trigger_expr: str | None = None


def _report_weekly(db, params: dict) -> dict:
    from app.modules.report.service import generate_due

    return generate_due(db, period_types=("weekly",))


def _report_monthly(db, params: dict) -> dict:
    from app.modules.report.service import generate_due

    return generate_due(db, period_types=("monthly",))


def _report_scan(db, params: dict) -> dict:
    from app.modules.report.service import generate_due

    # 手动兜底：忽略 report_auto_enabled 开关，用户主动要求就生成
    return generate_due(
        db, period_types=("weekly", "monthly"), limit=params.get("limit", 100), check_switch=False
    )


def _advice_daily(db, params: dict) -> dict:
    from app.modules.daily_advice.service import generate_due

    return generate_due(db)


def _advice_scan(db, params: dict) -> dict:
    from app.modules.daily_advice.service import generate_due

    # 手动兜底：忽略 advice_auto_enabled，用户主动要求就补跑当天
    return generate_due(db, limit=params.get("limit", 100), check_switch=False)


REGISTRY: dict[str, JobSpec] = {
    "report.weekly": JobSpec(
        key="report.weekly",
        name="周报自动生成",
        desc="每周一生成上周（周一至周日）的运动报告，已生成/已删除的周期跳过",
        func=_report_weekly,
        lock_scope="report",
        default_trigger_type="cron",
        default_trigger_expr="0 8 * * mon",
    ),
    "report.monthly": JobSpec(
        key="report.monthly",
        name="月报自动生成",
        desc="每月 1 日生成上个月的运动报告，已生成/已删除的周期跳过",
        func=_report_monthly,
        lock_scope="report",
        default_trigger_type="cron",
        default_trigger_expr="0 8 1 * *",
    ),
    "report.scan": JobSpec(
        key="report.scan",
        name="报告兜底扫描",
        desc="一次性补跑上周周报与上月月报（手动执行或命令行 --scan 使用，不排期）",
        func=_report_scan,
        lock_scope="report",
        params_schema=ScanParams,
    ),
    "advice.daily": JobSpec(
        key="advice.daily",
        name="今日训练建议",
        desc="每天 00:01 为启用账号生成当天的一份训练建议；已生成、失败达上限与生成中的跳过",
        func=_advice_daily,
        lock_scope="advice",
        default_trigger_type="cron",
        default_trigger_expr="1 0 * * *",
    ),
    "advice.scan": JobSpec(
        key="advice.scan",
        name="今日建议兜底扫描",
        desc="一次性补齐当天缺失或失败的训练建议（手动执行，不排期）",
        func=_advice_scan,
        lock_scope="advice",
        params_schema=ScanParams,
    ),
}


def get_spec(job_key: str) -> JobSpec:
    spec = REGISTRY.get(job_key)
    if spec is None:
        raise AppError(404, f"任务不存在：{job_key}")
    return spec


def validate_params(spec: JobSpec, params: dict) -> dict:
    """按注册表 schema 校验参数，返回规范化后的 dict（空参数返回 {}）。"""
    try:
        return spec.params_schema(**(params or {})).model_dump(exclude_none=True)
    except Exception as exc:  # pydantic ValidationError
        raise AppError(400, f"任务参数无效：{exc}") from None


def catalog() -> list[dict]:
    """给管理页的下拉选项：全部任务键、名称与默认排期。"""
    return [
        {
            "key": spec.key,
            "name": spec.name,
            "desc": spec.desc,
            "default_trigger_type": spec.default_trigger_type,
            "default_trigger_expr": spec.default_trigger_expr,
        }
        for spec in REGISTRY.values()
    ]
