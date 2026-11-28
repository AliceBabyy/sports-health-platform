"""AI 模型配置初始种子（幂等）：按当前 .env 与模型注册表写入来源、模型与功能路由。

用法：
    python scripts/seed_ai_config.py

说明：
- 只补缺失行，不覆盖已有配置；可重复执行。
- 来源默认取 `AI_BASE_URL` / `AI_API_KEY` / `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES`，
  来源键固定 `maas-default`，后续可在管理页新增其他来源。
- 模型取自 `app/ai/models/registry.py` 的 `MODELS`，别名与上游名一致，能力按注册表声明。
- 路由按现有 `.env` 选型写入；报告关闭思考的覆盖写在路由层，避免影响同一模型的对话调用。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.ai.models.registry import MODELS
from config import settings
from database import engine

PROVIDER_KEY = "maas-default"


def _insert_provider(conn) -> int:
    conn.execute(text("""
        INSERT INTO ai_providers (provider_key, name, base_url, api_key_env,
                                  timeout_seconds, max_retries, remark)
        VALUES (:key, :name, :base_url, 'AI_API_KEY', :timeout, :retries, :remark)
        ON CONFLICT (provider_key) DO NOTHING
    """), {
        "key": PROVIDER_KEY,
        "name": "默认 OpenAI 兼容网关",
        "base_url": settings.ai_base_url,
        "timeout": settings.ai_timeout_seconds,
        "retries": settings.ai_max_retries,
        "remark": "由 .env 初始化（AI_BASE_URL / AI_API_KEY / AI_TIMEOUT_SECONDS / AI_MAX_RETRIES）",
    })
    return conn.execute(text(
        "SELECT id FROM ai_providers WHERE provider_key = :key"
    ), {"key": PROVIDER_KEY}).scalar_one()


def _insert_model(conn, provider_id: int, alias: str, capabilities: frozenset[str],
                  sort_order: int, remark: str = "") -> None:
    conn.execute(text("""
        INSERT INTO ai_models (alias, provider_id, upstream_name, supports_text,
                               supports_vision, supports_tools, supports_structured_output,
                               structured_method, selectable_for_chat, sort_order, remark)
        VALUES (:alias, :provider_id, :upstream, :text, :vision, :tools, :structured,
                'json_schema', true, :sort_order, :remark)
        ON CONFLICT (alias) DO NOTHING
    """), {
        "alias": alias,
        "provider_id": provider_id,
        "upstream": alias,
        "text": "text" in capabilities,
        "vision": "vision" in capabilities,
        "tools": "tools" in capabilities,
        "structured": "structured_output" in capabilities,
        "sort_order": sort_order,
        "remark": remark,
    })


def _insert_route(conn, feature_key: str, alias: str, override: dict, remark: str,
                  timeout: float | None = None) -> None:
    conn.execute(text("""
        INSERT INTO ai_feature_routes (feature_key, model_alias, timeout_seconds,
                                       params_override, remark)
        VALUES (:key, :alias, :timeout, CAST(:override AS jsonb), :remark)
        ON CONFLICT (feature_key) DO NOTHING
    """), {
        "key": feature_key,
        "alias": alias,
        "timeout": timeout,
        "override": json.dumps(override, ensure_ascii=False),
        "remark": remark,
    })


def _report_override(alias: str) -> dict:
    """报告是非流式结构化调用，qwen 系默认关思考；覆盖放路由层，不影响同模型的对话。"""
    if settings.report_enable_thinking or not alias.startswith("qwen"):
        return {}
    return {"extra_body": {"enable_thinking": False}}


def main() -> None:
    default_model = settings.ai_default_model
    report_model = settings.report_model or default_model
    routes = [
        ("agent.chat", default_model, {}, "AI 对话默认（会话级 model_name 为空时使用）",
         settings.ai_timeout_seconds),
        ("agent.skill_parse", default_model, {}, "斜杠技能参数解析",
         settings.ai_timeout_seconds),
        ("import.text", settings.ai_import_model, {}, "AI 导入·纯文字",
         settings.ai_import_timeout_seconds),
        ("import.vision", settings.ai_import_vision_model, {}, "AI 导入·带图（需 vision 能力）",
         settings.ai_import_timeout_seconds),
        ("report.weekly", report_model, _report_override(report_model), "AI 周报",
         settings.report_timeout_seconds),
        ("report.monthly", report_model, _report_override(report_model), "AI 月报",
         settings.report_timeout_seconds),
        ("advice.daily", default_model, {}, "每日训练建议", settings.advice_timeout_seconds),
    ]

    with engine.begin() as conn:
        provider_id = _insert_provider(conn)
        for index, (alias, spec) in enumerate(MODELS.items()):
            _insert_model(conn, provider_id, alias, spec.capabilities, index)

        # .env 指向了注册表之外的模型时补一条占位记录，能力按最保守声明，待人工补齐
        known = set(MODELS)
        extra = {alias for _, alias, _, _, _ in routes} - known
        for offset, alias in enumerate(sorted(extra)):
            _insert_model(conn, provider_id, alias, frozenset({"text", "structured_output"}),
                          len(known) + offset, "来自 .env，能力未声明，请补齐")

        for feature_key, alias, override, remark, timeout in routes:
            _insert_route(conn, feature_key, alias, override, remark, timeout)

        missing = conn.execute(text("""
            SELECT DISTINCT r.model_alias
            FROM ai_feature_routes r
            LEFT JOIN ai_models m ON m.alias = r.model_alias
            WHERE m.id IS NULL
        """)).fetchall()
        counts = conn.execute(text("""
            SELECT
                (SELECT count(*) FROM ai_providers),
                (SELECT count(*) FROM ai_models),
                (SELECT count(*) FROM ai_feature_routes)
        """)).fetchone()

    print(f"来源 {counts[0]} 条 / 模型 {counts[1]} 条 / 路由 {counts[2]} 条")
    if missing:
        raise SystemExit(f"路由指向了不存在的模型别名：{[r[0] for r in missing]}")
    print("AI 模型配置种子完成（只补缺失行，已有配置未改动）")


if __name__ == "__main__":
    main()
