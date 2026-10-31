"""趋势聚合服务（BD-10~14）：周/月/半年/年四档，锚点+窗口均值，null 断线。

口径（需求 9.3 定稿）：
- week        ：本周周一~周日 7 点，取当日记录值（无记录 null）
- month       ：本月每天 1 点，取当日记录值（无记录 null）
- half_year   ：近半年每月 1/10/20 号共 18 锚点，窗口 [锚点-10天, 锚点] 共 11 天取均值
- year        ：近 12 个月每月 1/15 号共 24 锚点，窗口 [锚点-15天, 锚点] 共 16 天取均值
同日多条按 BD-02 归一为当日最后一条再参与计算；窗口内无记录 → null（前端断线）。
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.constants import (
    HALF_YEAR_ANCHOR_DAYS,
    HALF_YEAR_WINDOW_BACK,
    YEAR_ANCHOR_DAYS,
    YEAR_WINDOW_BACK,
    monday_of,
    today_local,
)
from app.modules.body.service import normalize_day_values


def _points_response(range_key: str, points: list[dict]) -> dict:
    return {"range": range_key, "points": points}


def _week_points(day_map: dict[date, float]) -> list[dict]:
    monday = monday_of(today_local())
    points = []
    for i in range(7):
        d = monday + timedelta(days=i)
        points.append({"date": d.isoformat(), "value": day_map.get(d)})
    return points


def _month_points(day_map: dict[date, float]) -> list[dict]:
    today = today_local()
    points = []
    for i in range(1, 32):
        try:
            d = today.replace(day=i)
        except ValueError:
            break
        points.append({"date": d.isoformat(), "value": day_map.get(d)})
    return points


def _window_average(day_map: dict[date, float], anchor: date, back: int) -> float | None:
    values = []
    for i in range(back + 1):  # [锚点-back, 锚点] 含两端共 back+1 天
        v = day_map.get(anchor - timedelta(days=i))
        if v is not None:
            values.append(v)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _half_year_points(day_map: dict[date, float]) -> list[dict]:
    today = today_local()
    points = []
    for month_offset in range(5, -1, -1):  # 近 6 个月，最旧在前
        year_month = _shift_month(today, -month_offset)
        for day in HALF_YEAR_ANCHOR_DAYS:
            try:
                anchor = year_month.replace(day=day)
            except ValueError:
                continue
            if anchor > today:
                continue  # 未来锚点不产出
            points.append(
                {"date": anchor.isoformat(), "value": _window_average(day_map, anchor, HALF_YEAR_WINDOW_BACK)}
            )
    return points


def _year_points(day_map: dict[date, float]) -> list[dict]:
    today = today_local()
    points = []
    for month_offset in range(11, -1, -1):  # 近 12 个月
        year_month = _shift_month(today, -month_offset)
        for day in YEAR_ANCHOR_DAYS:
            try:
                anchor = year_month.replace(day=day)
            except ValueError:
                continue
            if anchor > today:
                continue
            points.append(
                {"date": anchor.isoformat(), "value": _window_average(day_map, anchor, YEAR_WINDOW_BACK)}
            )
    return points


def _shift_month(day: date, offset: int) -> date:
    """将日期平移 offset 个月（保持日，溢出时取当月最后一天）。"""
    month_index = day.year * 12 + (day.month - 1) + offset
    year, month = divmod(month_index, 12)
    month += 1
    from calendar import monthrange

    return date(year, month, min(day.day, monthrange(year, month)[1]))


def build_trend(db: Session, user_id: int, metric: str, range_key: str) -> dict:
    day_map = normalize_day_values(db, user_id, metric)
    if range_key == "week":
        points = _week_points(day_map)
    elif range_key == "month":
        points = _month_points(day_map)
    elif range_key == "half_year":
        points = _half_year_points(day_map)
    elif range_key == "year":
        points = _year_points(day_map)
    else:
        raise ValueError("不支持的档位")
    return _points_response(range_key, points)
