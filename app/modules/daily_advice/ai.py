"""每日训练建议的模型调用与输出清洗。

与 AI 运动报告同类：一次结构化调用，模型只解释 facts，不查库、不调工具、不写会话。
硬约束由 facts 生成、由 sanitize 强制降档，不依赖模型自觉。
"""
import json
import re
import time
from datetime import date

from app.ai.models.registry import current_alias
from app.ai.runtime.invoke import invoke_structured
from app.modules.daily_advice.models import (
    FOCUS_RECOVERY,
    INTENSITY_ORDER,
    VERDICT_MARKERS,
    VERDICT_REST,
)
from app.modules.daily_advice.schemas import DailyAdvice

PROMPT_ID = "daily_advice.v4"
# 侧栏五句：判断 / 训练安排 / 最近健身播报 / 健康档案与状态提示 / 鼓励
LINE_LIMITS = (30, 36, 32, 40, 16)
MAX_LINES = len(LINE_LIMITS)
MAX_TEXT = sum(limit + 2 for limit in LINE_LIMITS) + (MAX_LINES - 1)
MAX_BODY_PARTS = 2
MAX_BODY_PART_CHARS = 8

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
STRENGTH_WORDS = ("力量", "无氧", "抗阻", "撸铁", "举铁", "负重")

CYCLE_SCOPE_NONE = "本账号无周期数据，不要提及生理周期。"
CYCLE_SCOPE_HAS = "有周期数据：区分真实记录、漏记补推与预测段，预测段只能作参考，不得当作事实。"


def _stricter(current: str | None, cap: str | None, order: tuple[str, ...]) -> str | None:
    """取两者中更保守的一项（order 左侧更保守）。"""
    if cap is None:
        return current
    if current is None:
        return cap
    return order[min(order.index(current), order.index(cap))]


def _level(value: str | None, order: tuple[str, ...]) -> str | None:
    """从「级别：说明」自由文本里取前缀级别。"""
    for marker in order:
        if value and value.startswith(marker):
            return marker
    return None


def _cap_text(value: str | None, cap: str | None, order: tuple[str, ...]) -> str | None:
    """保留自由文本的说明，只把前缀级别换成硬约束上限。"""
    if not value or cap is None:
        return value
    current = _level(value, order)
    if current is None or order.index(current) <= order.index(cap):
        return value
    return cap + value[len(current):]


def _split_lines(raw: str | None) -> list[str]:
    """先按换行拆；模型若把整段塞成一行，再按句末标点拆。"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) <= 1:
        joined = lines[0] if lines else ""
        lines = [part.strip() for part in re.split(r"[。！？]", joined) if part.strip()]
    return lines


def clean_text(raw: str | None, line_limits: tuple[int, ...] = LINE_LIMITS) -> str:
    """规整成侧栏五句：每行一句、以「- 」开头、去句末标点，各行按大致上限收口。"""
    lines: list[str] = []
    for index, line in enumerate(_split_lines(raw)):
        if index >= len(line_limits):
            break
        limit_chars = line_limits[index]
        line = re.sub(r"^[-•·*]+\s*", "", line).strip()
        line = line.rstrip("。．.；;，,、 ")
        if not line:
            continue
        if len(line) > limit_chars:
            cut = line[:limit_chars]
            idx = max(cut.rfind("，"), cut.rfind(","))
            line = (cut[:idx] if idx >= limit_chars // 3 else cut).rstrip("，,、 ")
        lines.append("- " + line)
    return "\n".join(lines)


def clean_body_parts(parts: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for part in parts or []:
        name = re.sub(r"\s+", "", str(part or ""))
        if not name or len(name) > MAX_BODY_PART_CHARS:
            continue
        if name not in cleaned:
            cleaned.append(name)
        if len(cleaned) >= MAX_BODY_PARTS:
            break
    return cleaned


def sanitize(
    advice: DailyAdvice,
    hard_limits: list[dict] | None,
    avoid_parts: list[str] | None = None,
) -> tuple[DailyAdvice, list[str]]:
    """按硬约束降档并清洗文本；返回 (清洗后的建议, warnings)。"""
    warnings: list[str] = []
    cap_intensity: str | None = None
    cap_verdict: str | None = None
    block_parts = False
    for limit in hard_limits or []:
        cap_intensity = _stricter(cap_intensity, limit.get("cap_intensity"), INTENSITY_ORDER)
        cap_verdict = _stricter(cap_verdict, limit.get("cap_verdict"), VERDICT_MARKERS)
        if limit.get("block_parts"):
            block_parts = True

    intensity = _cap_text(advice.intensity, cap_intensity, INTENSITY_ORDER) or advice.intensity
    verdict = _cap_text(advice.verdict, cap_verdict, VERDICT_MARKERS) or advice.verdict
    focus = advice.focus.strip()
    parts = clean_body_parts(advice.body_parts)
    avoid = {str(part).strip() for part in (avoid_parts or []) if str(part).strip()}

    if intensity != advice.intensity:
        warnings.append(f"强度按硬约束由 {advice.intensity} 收敛为 {intensity}")
    if verdict != advice.verdict:
        warnings.append(f"结论按硬约束由 {advice.verdict} 收敛为 {verdict}")

    if _level(verdict, VERDICT_MARKERS) == VERDICT_REST:
        focus = "恢复：轻活动、散步或拉伸"
        parts = []
    elif focus.startswith(FOCUS_RECOVERY):
        parts = []
    elif block_parts:
        # 今日不再安排力量：有氧/恢复保留，带力量字样的自由训练安排改为不排力量
        if any(word in focus for word in STRENGTH_WORDS):
            focus = "低强度有氧或恢复：今日不安排力量"
        parts = []

    # 最近 2 天练过的部位今天不再重复安排；提示词负责解释，代码负责兜底清空
    kept_parts = [part for part in parts if part not in avoid]
    if kept_parts != parts:
        warnings.append("建议部位包含最近 2 天已练部位，已移除")
    parts = kept_parts

    text = clean_text(advice.text)
    if not text:
        raise ValueError("模型未返回正文")

    cleaned = DailyAdvice(
        verdict=verdict,
        focus=focus,
        intensity=intensity,
        body_parts=parts,
        text=text,
    )
    return cleaned, warnings


def generate_advice(facts: dict, model_name: str | None = None) -> tuple[DailyAdvice, dict]:
    """调用默认模型生成建议；失败抛 AIServiceError，由 service 记为 failed。"""
    day = date.fromisoformat(facts["date"])
    cycle_scope = CYCLE_SCOPE_HAS if facts.get("cycle") else CYCLE_SCOPE_NONE
    started = time.monotonic()
    raw = invoke_structured(
        feature="advice.daily",
        model_name=model_name,
        prompt_id=PROMPT_ID,
        schema=DailyAdvice,
        input_text=json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
        variables={
            "today": facts["date"],
            "weekday": WEEKDAY_CN[day.weekday()],
            "cycle_scope": cycle_scope,
        },
    )
    advice, warnings = sanitize(
        raw,
        facts.get("hard_limits") or [],
        avoid_parts=(facts.get("recent_load") or {}).get("recent_parts_2d") or [],
    )
    meta = {
        "model": current_alias("advice.daily", model_name),
        "prompt_version": PROMPT_ID,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "warnings": warnings,
    }
    return advice, meta
