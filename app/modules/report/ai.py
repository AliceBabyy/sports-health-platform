"""报告 AI 叙事：一次性结构化调用 + evidence 白名单校验。

与 AI 导入同类：不绑定工具、不进 Agent 图、不写会话；模型只解释 facts，不查库。
所有数字来自 facts.metrics，叙事中的 evidence 只能引用其中真实存在的键。
"""
import json
import logging
import time

from app.ai.runtime.invoke import invoke_structured
from app.modules.report.facts import Period
from app.modules.report.schemas import EvidenceItem, ReportNarrative
from config import settings

logger = logging.getLogger(__name__)

PROMPT_IDS = {
    "weekly": "weekly_report.v1",
    "monthly": "monthly_report.v1",
}
MODEL_LABELS = {"weekly": "周报", "monthly": "月报"}


def _status_note(period: Period) -> str:
    if period.partial:
        return f"本期尚未结束，事实只统计到 {period.as_of.isoformat()}，不要当作完整周期。"
    return "本期已结束，事实覆盖完整周期。"


def _trim(value: str, limit: int) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit]


def sanitize_narrative(narrative: ReportNarrative, metrics: dict) -> tuple[ReportNarrative, list[str]]:
    """裁剪文本、过滤编造的 evidence；返回 (清洗后的叙事, warnings)。

    evidence 引用了不存在的指标键时删除该键；如果一条内容的 evidence 全部无效，
    整条丢弃，避免把编造的依据留在页面上。
    """
    warnings: list[str] = []

    def clean_items(items: list[EvidenceItem], limit: int) -> list[EvidenceItem]:
        cleaned = []
        for item in items[:limit]:
            raw_keys = [k for k in (item.evidence or []) if k]
            valid = [k for k in raw_keys if k in metrics]
            invalid = [k for k in raw_keys if k not in metrics]
            if invalid:
                warnings.append(f"已忽略不存在的指标引用：{', '.join(invalid[:3])}")
            if raw_keys and not valid:
                warnings.append(f"内容「{_trim(item.title, 14)}」引用了无效指标，已丢弃")
                continue
            cleaned.append(
                EvidenceItem(
                    title=_trim(item.title, 40),
                    detail=_trim(item.detail, 400),
                    evidence=valid[:3],
                )
            )
        return cleaned

    cleaned = ReportNarrative(
        headline=_trim(narrative.headline, 64) or "本期运动报告",
        summary=_trim(narrative.summary, 600),
        highlights=clean_items(narrative.highlights, 5),
        watchouts=clean_items(narrative.watchouts, 3),
        next_actions=clean_items(narrative.next_actions, 4),
        caveats=[_trim(x, 200) for x in (narrative.caveats or []) if x][:4],
        cycle_note=_trim(narrative.cycle_note, 300),
    )
    return cleaned, warnings


def _extra_body(model_name: str | None) -> dict | None:
    """报告是非流式结构化调用：qwen 系思考模式会先想再吐 JSON，实测 90~120s 顶满读超时。

    默认关闭思考（实测 20~25s）；仅对 qwen* 模型传参，换用其他厂商模型时不传。
    """
    if settings.report_enable_thinking:
        return None
    selected = model_name or settings.report_model or settings.ai_default_model
    return {"enable_thinking": False} if selected.startswith("qwen") else None


def generate_narrative(
    period: Period,
    facts: dict,
    model_name: str | None = None,
    cycle_allowed: bool = False,
) -> tuple[ReportNarrative, dict]:
    """调用模型生成叙事；失败抛出 AIServiceError，由 service 记为 failed。"""
    prompt_id = PROMPT_IDS[period.type]
    model = model_name or settings.report_model or None
    started = time.monotonic()
    narrative = invoke_structured(
        model_name=model,
        prompt_id=prompt_id,
        schema=ReportNarrative,
        input_text=json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
        variables={
            "today": period.as_of.isoformat(),
            "period_label": period.label,
            "period_range": period.range_label,
            "status_note": _status_note(period),
        },
        timeout=settings.report_timeout_seconds,
        extra_body=_extra_body(model),
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    narrative, warnings = sanitize_narrative(narrative, facts.get("metrics") or {})
    if not cycle_allowed:
        narrative.cycle_note = ""
    meta = {
        "model": model or settings.ai_default_model,
        "prompt_version": prompt_id,
        "elapsed_ms": elapsed_ms,
        "warnings": warnings,
    }
    return narrative, meta
