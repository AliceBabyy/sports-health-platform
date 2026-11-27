"""每日训练建议的模型调用与输出清洗。

与 AI 运动报告同类：一次结构化调用，模型只解释 facts，不查库、不调工具、不写会话。
硬约束由 facts 生成、由 sanitize 强制降档，不依赖模型自觉。
"""
import json
import re
import time
from datetime import date

from app.ai.runtime.invoke import invoke_structured
from app.modules.daily_advice.models import (
    FOCUS_AEROBIC,
    FOCUS_RECOVERY,
    INTENSITIES,
    VERDICTS,
)
from app.modules.daily_advice.schemas import DailyAdvice
from config import settings

PROMPT_ID = "daily_advice.v3"
# 侧栏正文三句：强度 / 运动类型与部位 / 依据；服务端按大致上限收口，不要求精确字数
LINE_LIMITS = (32, 36, 48)
MAX_LINES = len(LINE_LIMITS)
MAX_TEXT = sum(limit + 2 for limit in LINE_LIMITS) + (MAX_LINES - 1)
MAX_BODY_PARTS = 2
MAX_BODY_PART_CHARS = 8

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
# 强弱/宽严顺序：降档时取更保守的一档
INTENSITY_ORDER = ("低", "中", "高")
VERDICT_ORDER = ("休息", "克制", "适合")

CYCLE_SCOPE_NONE = "本账号无周期数据，不要提及生理周期。"
CYCLE_SCOPE_HAS = "有周期数据：区分真实记录、漏记补推与预测段，预测段只能作参考，不得当作事实。"


def _stricter(current: str | None, cap: str | None, order: tuple[str, ...]) -> str | None:
    """取两者中更保守的一项（order 左侧更保守）。"""
    if cap is None:
        return current
    if current is None:
        return cap
    return order[min(order.index(current), order.index(cap))]


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
    """规整成侧栏三句：每行一句、以「- 」开头、去句末标点，各行按大致上限收口。"""
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


def sanitize(advice: DailyAdvice, hard_limits: list[dict] | None) -> tuple[DailyAdvice, list[str]]:
    """按硬约束降档并清洗文本；返回 (清洗后的建议, warnings)。"""
    warnings: list[str] = []
    cap_intensity: str | None = None
    cap_verdict: str | None = None
    block_parts = False
    for limit in hard_limits or []:
        cap_intensity = _stricter(cap_intensity, limit.get("cap_intensity"), INTENSITY_ORDER)
        cap_verdict = _stricter(cap_verdict, limit.get("cap_verdict"), VERDICT_ORDER)
        if limit.get("block_parts"):
            block_parts = True

    intensity = _stricter(advice.intensity, cap_intensity, INTENSITY_ORDER) or INTENSITIES[0]
    verdict = _stricter(advice.verdict, cap_verdict, VERDICT_ORDER) or VERDICTS[0]
    focus = advice.focus
    parts = clean_body_parts(advice.body_parts)

    if intensity != advice.intensity:
        warnings.append(f"强度按硬约束由 {advice.intensity} 降为 {intensity}")
    if verdict != advice.verdict:
        warnings.append(f"结论按硬约束由 {advice.verdict} 降为 {verdict}")

    if verdict == "休息":
        focus = FOCUS_RECOVERY
        parts = []
    elif focus == FOCUS_RECOVERY:
        parts = []
    elif block_parts:
        # 今日不再安排力量：有氧保留，纯无氧与混合降为有氧并清空部位
        parts = []
        if focus != FOCUS_AEROBIC:
            focus = FOCUS_AEROBIC

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
    """调用默认模型生成一句建议；失败抛 AIServiceError，由 service 记为 failed。"""
    day = date.fromisoformat(facts["date"])
    cycle_scope = CYCLE_SCOPE_HAS if facts.get("cycle") else CYCLE_SCOPE_NONE
    started = time.monotonic()
    raw = invoke_structured(
        model_name=model_name,
        prompt_id=PROMPT_ID,
        schema=DailyAdvice,
        input_text=json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
        variables={
            "today": facts["date"],
            "weekday": WEEKDAY_CN[day.weekday()],
            "cycle_scope": cycle_scope,
        },
        timeout=settings.advice_timeout_seconds,
    )
    advice, warnings = sanitize(raw, facts.get("hard_limits") or [])
    meta = {
        "model": model_name or settings.ai_default_model,
        "prompt_version": PROMPT_ID,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "warnings": warnings,
    }
    return advice, meta
