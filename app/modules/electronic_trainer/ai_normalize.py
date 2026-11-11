"""AI 输出的宽松清洗：只修形状、单位与相对日期，不改业务口径。"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

_EMPTY_TOKENS = {"", "-", "—", "null", "none", "n/a", "未知", "未提供", "未提及", "没有", "无", "不祥"}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TIME_RE = re.compile(r"^(\d{1,2})[:：](\d{1,2})(?:[:：](\d{1,2}))?$")
_RANGE_RE = re.compile(
    r"^(\d{1,2}[:：]\d{1,2}(?:[:：]\d{1,2})?)\s*[-~～至]\s*(\d{1,2}[:：]\d{1,2}(?:[:：]\d{1,2}))?$"
)
_CLOCK_RE = re.compile(r"^(上午|下午|晚上|傍晚|中午|早上|凌晨)?\s*(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分?)?")
_RELATIVE_DAYS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}


def clean_str(value, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _EMPTY_TOKENS:
        return None
    if max_length and len(text) > max_length:
        text = text[:max_length]
    return text


def to_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("，", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def to_int(value) -> int | None:
    number = to_number(value)
    return int(round(number)) if number is not None else None


def clamp_int(value, low: int, high: int) -> int | None:
    number = to_int(value)
    if number is None:
        return None
    return min(high, max(low, number))


def parse_date(value, today: date) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_str(value)
    if text is None:
        return None
    if text in _RELATIVE_DAYS:
        return today - timedelta(days=_RELATIVE_DAYS[text])
    text = text.replace("／", "/").replace("．", ".").strip()
    head = text[:10]
    for sep in ("/", "."):
        candidate = head.replace(sep, "-")
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    try:
        return date.fromisoformat(head)
    except ValueError:
        pass
    match = re.match(r"^(\d{1,2})\s*[-月]\s*(\d{1,2})\s*[日号]?$", text)
    if match:
        try:
            return date(today.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
    return None


def _to_datetime(day: date, value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = clean_str(value)
    if text is None:
        return None
    if "T" in text or re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return None
    match = _TIME_RE.match(text)
    if match:
        try:
            return datetime.combine(day, time(int(match.group(1)), int(match.group(2)),
                                             int(match.group(3) or 0)))
        except ValueError:
            return None
    match = _CLOCK_RE.match(text)
    if match:
        period, hour, minute = match.group(1), int(match.group(2)), int(match.group(3) or 0)
        if period in ("下午", "晚上", "傍晚") and hour < 12:
            hour += 12
        if period == "凌晨" and hour == 12:
            hour = 0
        try:
            return datetime.combine(day, time(hour, minute))
        except ValueError:
            return None
    return None


def pair_times(day: date, start_raw, end_raw) -> tuple[str | None, str | None]:
    """起止成对返回；只有一端或顺序颠倒时整对丢弃，避免把单边时间写进记录。"""
    start_text = clean_str(start_raw)
    end_text = clean_str(end_raw)
    if start_text and not end_text:
        match = _RANGE_RE.match(start_text)
        if match:
            start_text, end_text = match.group(1), match.group(2) or ""
    start = _to_datetime(day, start_text)
    end = _to_datetime(day, end_text)
    if start is None or end is None or end <= start:
        return None, None
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
