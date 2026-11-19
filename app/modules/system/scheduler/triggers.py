"""触发表达式解析与人类可读描述。

- cron：标准五段式「分 时 日 月 星期」，如 `0 8 * * mon`。星期字段只接受 mon~sun 英文缩写：
  APScheduler 的 day_of_week 以 0=周一，与 crontab 的 0=周日 差一位，数字写法会静默错一天。
- interval：如 `30s`、`10m`、`2h`、`1d`，最小 60 秒。
- date：一次性触发，如 `2026-11-20 15:40`，必须晚于当前时间。
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.exceptions import AppError

_DAYS = {"mon": "周一", "tue": "周二", "wed": "周三", "thu": "周四", "fri": "周五", "sat": "周六", "sun": "周日"}
_INTERVAL_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_UNIT_LABEL = {"s": "秒", "m": "分钟", "h": "小时", "d": "天"}
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def get_tz(name: str) -> ZoneInfo:
    """时区名转 ZoneInfo；不存在时转成 400 业务错误。"""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(400, f"时区不存在：{name}") from None


def _check_day_of_week(expr: str) -> None:
    """星期字段只允许 *、mon~sun 与它们的组合（含 - 区间和 /N 步进）。"""
    for part in expr.split()[4].split(","):
        token = part.split("/")[0]
        if token == "*":
            continue
        for day in token.split("-"):
            if day.lower() not in _DAYS:
                raise AppError(
                    400, "cron 星期字段只接受 mon~sun 英文缩写（如 mon、mon-fri），不接受数字"
                )


def _parse_date(expr: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(expr, fmt)
        except ValueError:
            continue
    raise AppError(400, "date 表达式形如 2026-11-20 15:40")


def parse_trigger(trigger_type: str, expr: str, timezone: str):
    """把表达式解析成 APScheduler trigger；非法表达式转成 400 业务错误。"""
    expr = (expr or "").strip()
    tz = get_tz(timezone)
    if trigger_type == "cron":
        if len(expr.split()) != 5:
            raise AppError(400, "cron 表达式需 5 段：分 时 日 月 星期，如 0 8 * * mon")
        _check_day_of_week(expr)
        try:
            return CronTrigger.from_crontab(expr, timezone=tz)
        except (ValueError, TypeError) as exc:
            raise AppError(400, f"cron 表达式无效：{exc}") from None

    if trigger_type == "interval":
        matched = _INTERVAL_RE.match(expr.lower())
        if not matched:
            raise AppError(400, "interval 表达式形如 30s / 10m / 2h / 1d")
        seconds = int(matched.group(1)) * _UNIT_SECONDS[matched.group(2)]
        if seconds < 60:
            raise AppError(400, "interval 间隔不能小于 60 秒")
        return IntervalTrigger(seconds=seconds, timezone=tz)

    if trigger_type == "date":
        run_date = _parse_date(expr)
        if run_date <= datetime.now():
            raise AppError(400, "date 触发器的时间必须晚于当前时间")
        return DateTrigger(run_date=run_date, timezone=tz)

    raise AppError(400, f"不支持的触发类型：{trigger_type}")


def describe(trigger_type: str, expr: str) -> str:
    """给管理页展示的中文描述；认得常见形态，其余原样回显。"""
    expr = (expr or "").strip()
    if trigger_type == "interval":
        matched = _INTERVAL_RE.match(expr.lower())
        if matched:
            return f"每 {matched.group(1)} {_UNIT_LABEL[matched.group(2)]}"
        return expr
    if trigger_type == "date":
        return f"{expr} 执行一次"
    if trigger_type != "cron":
        return expr

    fields = expr.split()
    if len(fields) != 5:
        return expr
    minute, hour, day, month, dow = fields
    clock = f"{int(hour):02d}:{int(minute):02d}" if hour.isdigit() and minute.isdigit() else None
    if clock and day == "*" and month == "*" and dow == "*":
        return f"每天 {clock}"
    if clock and day == "*" and month == "*" and dow.lower() in _DAYS:
        return f"每{_DAYS[dow.lower()]} {clock}"
    if clock and day.isdigit() and month == "*" and dow == "*":
        return f"每月 {int(day)} 日 {clock}"
    if clock and day.isdigit() and month.isdigit() and dow == "*":
        return f"每年 {int(month)} 月 {int(day)} 日 {clock}"
    return f"cron {expr}"
