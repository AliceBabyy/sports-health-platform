"""AI 模型解析：功能键 → 模型别名 → 来源（base_url/密钥）→ ChatOpenAI。

配置以数据库三表为准（ai_providers / ai_models / ai_feature_routes），进程内维护
快照并在保存配置时显式失效；TTL 兜底多 worker 场景。数据库不可用或功能未配路由时，
按 .env 旧键与代码内置清单回落，保证可回滚。
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Literal

from langchain_openai import ChatOpenAI
from sqlalchemy import text

from app.ai.models.secrets import SecretError, resolve_secret
from config import settings
from database import SessionLocal

logger = logging.getLogger(__name__)

Capability = Literal["text", "vision", "tools", "structured_output"]

# 功能键是代码契约：新增功能点在这里登记，管理页只允许维护这些键。
FEATURES: dict[str, dict] = {
    "agent.chat": {
        "label": "AI 助手对话",
        "required": frozenset({"text", "tools"}),
        "legacy_model": lambda: settings.ai_default_model,
        "desc": "会话主模型，必须支持工具调用",
    },
    "agent.skill_parse": {
        "label": "技能参数解析",
        "required": frozenset({"text", "structured_output"}),
        "legacy_model": lambda: settings.ai_default_model,
        "desc": "斜杠技能参数抽取，必须支持结构化输出",
    },
    "import.text": {
        "label": "AI 导入·文字",
        "required": frozenset({"text", "structured_output"}),
        "legacy_model": lambda: settings.ai_import_model,
        "desc": "纯文字运动记录导入，必须支持结构化输出",
    },
    "import.vision": {
        "label": "AI 导入·图片",
        "required": frozenset({"text", "vision", "structured_output"}),
        "legacy_model": lambda: settings.ai_import_vision_model,
        "desc": "带图运动记录导入，必须支持图片与结构化输出",
    },
    "report.weekly": {
        "label": "周报生成",
        "required": frozenset({"text", "structured_output"}),
        "legacy_model": lambda: settings.report_model or settings.ai_default_model,
        "desc": "周运动报告叙事，必须支持结构化输出",
    },
    "report.monthly": {
        "label": "月报生成",
        "required": frozenset({"text", "structured_output"}),
        "legacy_model": lambda: settings.report_model or settings.ai_default_model,
        "desc": "月运动报告叙事，必须支持结构化输出",
    },
    "advice.daily": {
        "label": "每日训练建议",
        "required": frozenset({"text", "structured_output"}),
        "legacy_model": lambda: settings.ai_default_model,
        "desc": "每日建议正文，必须支持结构化输出",
    },
}

FEATURE_KEYS = tuple(FEATURES.keys())
SNAPSHOT_TTL_SECONDS = 45.0


@dataclass(frozen=True)
class ModelSpec:
    """代码内置清单（仅作数据库不可用/未配置路由时的回落）。"""
    name: str
    capabilities: frozenset[str]


MODELS = {
    name: ModelSpec(name, frozenset({"text", "structured_output", "tools"}))
    for name in ("deepseek-v4.1-flash", "qwen3.8-flash", "qwen3.8-2.4t-a95b",
                 "qwen4-max", "kimi-k3.1-pro", "glm-5.3")
}
MODELS["qwen3-vl-plus"] = ModelSpec(
    "qwen3-vl-plus", frozenset({"text", "vision", "structured_output", "tools"})
)


class ModelConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    id: int
    provider_key: str
    name: str
    base_url: str
    api_key_env: str
    api_key_cipher: str | None
    timeout_seconds: float
    max_retries: int
    extra_headers: dict
    status: str


@dataclass(frozen=True)
class ModelConfig:
    id: int
    alias: str
    provider_id: int
    upstream_name: str
    capabilities: frozenset[str]
    structured_method: str
    timeout_seconds: float | None
    extra_body: dict
    params: dict
    selectable_for_chat: bool
    status: str
    sort_order: int


@dataclass(frozen=True)
class RouteConfig:
    feature_key: str
    model_alias: str
    timeout_seconds: float | None
    params_override: dict
    enabled: bool


@dataclass
class Snapshot:
    providers: dict[int, ProviderConfig] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    routes: dict[str, RouteConfig] = field(default_factory=dict)
    loaded_at: float = 0.0
    source: str = "db"


@dataclass
class ResolvedModel:
    alias: str
    upstream_name: str
    provider_key: str
    feature: str | None
    capabilities: frozenset[str]
    structured_method: str
    timeout: float
    extra_body: dict
    params: dict
    chat: ChatOpenAI


_lock = threading.RLock()
_snapshot: Snapshot | None = None
_snapshot_at = 0.0
_db_warned = False

PARAM_KEYS = {
    "temperature", "max_tokens", "max_completion_tokens", "top_p",
    "frequency_penalty", "presence_penalty", "seed", "stop", "n", "logprobs",
}


def _f(value, default: float) -> float:
    return float(value) if isinstance(value, (Decimal, int, float)) else default


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def normalize_base_url(value: str) -> str:
    """用户可只填主机名：缺协议时补 https，保留其填写的路径（如 /v1）。"""
    url = (value or "").strip().rstrip("/")
    if not url:
        raise ModelConfigurationError("来源 base_url 未配置")
    if "://" not in url:
        url = "https://" + url
    return url


def _load_snapshot() -> Snapshot:
    snap = Snapshot(loaded_at=time.monotonic())
    with SessionLocal() as db:
        for row in db.execute(text(
            "SELECT id, provider_key, name, base_url, api_key_env, api_key_cipher, "
            "timeout_seconds, max_retries, extra_headers, status FROM ai_providers"
        )):
            snap.providers[row.id] = ProviderConfig(
                id=row.id, provider_key=row.provider_key, name=row.name,
                base_url=row.base_url, api_key_env=row.api_key_env,
                api_key_cipher=row.api_key_cipher,
                timeout_seconds=_f(row.timeout_seconds, settings.ai_timeout_seconds),
                max_retries=int(row.max_retries or 0),
                extra_headers=_dict(row.extra_headers), status=row.status,
            )
        for row in db.execute(text(
            "SELECT id, alias, provider_id, upstream_name, supports_text, supports_vision, "
            "supports_tools, supports_structured_output, structured_method, timeout_seconds, "
            "extra_body, params, selectable_for_chat, status, sort_order FROM ai_models"
        )):
            caps = {
                name for name, enabled in (
                    ("text", row.supports_text), ("vision", row.supports_vision),
                    ("tools", row.supports_tools),
                    ("structured_output", row.supports_structured_output),
                ) if enabled
            }
            snap.models[row.alias] = ModelConfig(
                id=row.id, alias=row.alias, provider_id=row.provider_id,
                upstream_name=row.upstream_name, capabilities=frozenset(caps),
                structured_method=row.structured_method,
                timeout_seconds=float(row.timeout_seconds) if row.timeout_seconds is not None else None,
                extra_body=_dict(row.extra_body), params=_dict(row.params),
                selectable_for_chat=bool(row.selectable_for_chat),
                status=row.status, sort_order=int(row.sort_order or 0),
            )
        for row in db.execute(text(
            "SELECT feature_key, model_alias, timeout_seconds, params_override, enabled "
            "FROM ai_feature_routes"
        )):
            snap.routes[row.feature_key] = RouteConfig(
                feature_key=row.feature_key, model_alias=row.model_alias,
                timeout_seconds=float(row.timeout_seconds) if row.timeout_seconds is not None else None,
                params_override=_dict(row.params_override), enabled=bool(row.enabled),
            )
    return snap


def get_snapshot(force: bool = False) -> Snapshot:
    global _snapshot, _snapshot_at, _db_warned
    now = time.monotonic()
    if not force and _snapshot is not None and now - _snapshot_at < SNAPSHOT_TTL_SECONDS:
        return _snapshot
    with _lock:
        now = time.monotonic()
        if not force and _snapshot is not None and now - _snapshot_at < SNAPSHOT_TTL_SECONDS:
            return _snapshot
        try:
            snap = _load_snapshot()
            _db_warned = False
        except Exception as exc:  # 首次部署尚未迁移时应回落到 .env，而不是整站不可用
            if not _db_warned:
                logger.warning("AI 配置表不可读，回落 .env：%s", type(exc).__name__)
                _db_warned = True
            snap = Snapshot(source="legacy")
        _snapshot = snap
        _snapshot_at = time.monotonic()
        return snap


def invalidate_model_config() -> None:
    """管理页保存后调用：清空快照，下一次调用立即读库（保存即生效）。"""
    global _snapshot, _snapshot_at
    with _lock:
        _snapshot = None
        _snapshot_at = 0.0


def _legacy_model(alias: str) -> tuple[ModelSpec | None, ProviderConfig | None]:
    spec = MODELS.get(alias)
    if spec is None:
        return None, None
    provider = ProviderConfig(
        id=0, provider_key="legacy-env", name=".env 默认来源",
        base_url=settings.ai_base_url, api_key_env="AI_API_KEY", api_key_cipher=None,
        timeout_seconds=settings.ai_timeout_seconds, max_retries=settings.ai_max_retries,
        extra_headers={}, status="active",
    )
    return spec, provider


def _normalize_required(required: str | Iterable[str] | None) -> frozenset[str]:
    if required is None:
        return frozenset()
    if isinstance(required, str):
        return frozenset({required})
    return frozenset(required)


def _select_alias(snap: Snapshot, feature: str | None, model_name: str | None) -> tuple[str, RouteConfig | None]:
    if model_name:
        return model_name, None
    if feature:
        route = snap.routes.get(feature)
        if route and route.enabled and route.model_alias:
            return route.model_alias, route
        legacy = FEATURES.get(feature, {}).get("legacy_model")
        if legacy:
            return legacy(), None
    return settings.ai_default_model, None


def current_alias(feature: str, model_name: str | None = None) -> str:
    """只做选型（不校验能力/密钥），用于落库元信息展示。"""
    snap = get_snapshot()
    return _select_alias(snap, feature, model_name)[0]


def resolve_model(
    feature: str | None = None,
    model_name: str | None = None,
    *,
    required: str | Iterable[str] | None = None,
    timeout: float | None = None,
    extra_body: dict | None = None,
) -> ResolvedModel:
    if feature and feature not in FEATURES:
        raise ModelConfigurationError(f"未知 AI 功能键：{feature}")
    snap = get_snapshot()
    alias, route = _select_alias(snap, feature, model_name)
    if not alias:
        raise ModelConfigurationError("未选择模型")

    model_cfg = snap.models.get(alias)
    if model_cfg is None:
        spec, provider = _legacy_model(alias)
        if spec is None:
            raise ModelConfigurationError(f"不支持该模型：{alias}（请在 AI 配置页登记）")
        caps = spec.capabilities
        method = "json_schema"
        model_extra: dict = {}
        params: dict = {}
        model_timeout = None
    else:
        if model_cfg.status != "active":
            raise ModelConfigurationError(f"模型 {alias} 已停用")
        provider = snap.providers.get(model_cfg.provider_id)
        if provider is None:
            raise ModelConfigurationError(f"模型 {alias} 的来源不存在")
        caps = model_cfg.capabilities
        method = model_cfg.structured_method or "json_schema"
        model_extra = model_cfg.extra_body
        params = model_cfg.params
        model_timeout = model_cfg.timeout_seconds

    if model_cfg is not None and provider.status != "active":
        raise ModelConfigurationError(f"来源 {provider.name} 已停用")

    need = _normalize_required(required)
    if feature:
        need |= FEATURES[feature]["required"]
    missing = need - caps
    if missing:
        labels = {"text": "文本", "vision": "图片输入", "tools": "工具调用",
                  "structured_output": "结构化输出"}
        raise ModelConfigurationError(
            f"模型 {alias} 未声明能力：{'、'.join(labels.get(x, x) for x in sorted(missing))}")

    try:
        api_key = resolve_secret(provider.api_key_env, provider.api_key_cipher)
    except SecretError as exc:
        raise ModelConfigurationError(str(exc)) from exc
    if not api_key:
        raise ModelConfigurationError(
            f"来源 {provider.name} 未配置密钥（变量 {provider.api_key_env}）")

    merged_extra = {**model_extra}
    if route:
        merged_extra.update(_dict(route.params_override.get("extra_body")))
    if extra_body:
        merged_extra.update(extra_body)
    merged_params = {k: v for k, v in params.items() if k in PARAM_KEYS}
    if route:
        merged_params.update({k: v for k, v in route.params_override.items()
                              if k in PARAM_KEYS})

    chosen_timeout = (
        timeout
        or (route.timeout_seconds if route else None)
        or model_timeout
        or provider.timeout_seconds
        or settings.ai_timeout_seconds
    )

    kwargs: dict = {
        "model": model_cfg.upstream_name if model_cfg else alias,
        "api_key": api_key,
        "base_url": normalize_base_url(provider.base_url),
        "timeout": float(chosen_timeout),
        "max_retries": provider.max_retries,
    }
    if provider.extra_headers:
        kwargs["default_headers"] = provider.extra_headers
    if merged_extra:
        kwargs["extra_body"] = merged_extra
    kwargs.update(merged_params)
    try:
        chat = ChatOpenAI(**kwargs)
    except Exception as exc:
        raise ModelConfigurationError(f"模型 {alias} 参数不合法：{exc}") from exc

    return ResolvedModel(
        alias=alias,
        upstream_name=model_cfg.upstream_name if model_cfg else alias,
        provider_key=provider.provider_key,
        feature=feature,
        capabilities=caps,
        structured_method=method,
        timeout=float(chosen_timeout),
        extra_body=merged_extra,
        params=merged_params,
        chat=chat,
    )


def get_model(name: str | None = None, *, required: str = "text",
              timeout: float | None = None, extra_body: dict | None = None,
              feature: str | None = None) -> ChatOpenAI:
    """兼容入口：返回裸 ChatOpenAI；需要结构化方式时用 resolve_model。"""
    return resolve_model(feature, name, required=required, timeout=timeout,
                         extra_body=extra_body).chat


def model_capabilities(alias: str) -> frozenset[str]:
    snap = get_snapshot()
    cfg = snap.models.get(alias)
    if cfg:
        return cfg.capabilities
    spec = MODELS.get(alias)
    return spec.capabilities if spec else frozenset()


def chat_model_names() -> list[str]:
    """AI 助手页下拉：启用 + 允许对话 + 支持工具，按 sort_order 排序。"""
    snap = get_snapshot()
    rows = [
        cfg for cfg in snap.models.values()
        if cfg.status == "active" and cfg.selectable_for_chat and "tools" in cfg.capabilities
    ]
    if rows:
        return [cfg.alias for cfg in sorted(rows, key=lambda c: (c.sort_order, c.alias))]
    return [name for name, spec in MODELS.items() if "tools" in spec.capabilities]


def is_chat_model(alias: str | None) -> bool:
    return alias is None or alias in chat_model_names()


def public_models(include_disabled: bool = True) -> list[dict]:
    snap = get_snapshot()
    if snap.models:
        rows = [
            cfg for cfg in snap.models.values()
            if include_disabled or cfg.status == "active"
        ]
        return [
            {"name": cfg.alias, "capabilities": sorted(cfg.capabilities),
             "provider_key": snap.providers[cfg.provider_id].provider_key
             if cfg.provider_id in snap.providers else "",
             "status": cfg.status}
            for cfg in sorted(rows, key=lambda c: (c.sort_order, c.alias))
        ]
    return [{"name": name, "capabilities": sorted(spec.capabilities),
             "provider_key": "legacy-env", "status": "active"}
            for name, spec in MODELS.items()]


def feature_catalog(snap: Snapshot | None = None) -> list[dict]:
    snap = snap or get_snapshot()
    items = []
    for key, meta in FEATURES.items():
        route = snap.routes.get(key)
        alias = route.model_alias if route and route.enabled else meta["legacy_model"]()
        items.append({
            "feature_key": key, "label": meta["label"], "desc": meta["desc"],
            "required": sorted(meta["required"]), "model_alias": alias,
            "configured": bool(route and route.enabled),
        })
    return items
