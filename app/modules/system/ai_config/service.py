"""AI 配置管理：来源 / 模型 / 功能路由的校验、增删改、测试连接与生效刷新。

能力约束在代码里（FEATURES），页面只能在这些约束内调整；保存后清空运行时快照，
下一次模型调用立即按新配置构造客户端（保存即生效，多 worker 由 45s TTL 兜底）。
"""
import logging
import re
import time

from langchain_openai import ChatOpenAI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.models.registry import (
    FEATURES,
    PARAM_KEYS,
    get_snapshot,
    invalidate_model_config,
    normalize_base_url,
    resolve_model,
)
from app.ai.models.secrets import SecretError, decrypt_secret, encrypt_secret, env_secret, mask_secret
from app.modules.auth.models import User
from app.modules.system.ai_config.models import AiFeatureRoute, AiModel, AiProvider

logger = logging.getLogger("system_ai")

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CAP_LABELS = {"text": "文本", "vision": "图片输入", "tools": "工具调用", "structured_output": "结构化输出"}


class AiConfigError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _clean_url(value: str) -> str:
    url = (value or "").strip()
    if not url or any(ch.isspace() for ch in url):
        raise AiConfigError("接口地址不能为空，也不能包含空格")
    if len(url) > 255:
        raise AiConfigError("接口地址过长（上限 255 字符）")
    # 只校验可解析，不替用户补路径：库里保留用户填写的原样
    normalize_base_url(url)
    return url


def _clean_dict(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise AiConfigError(f"{label}必须是 JSON 对象")
    return value


def _clean_caps(data: dict) -> frozenset[str]:
    caps = {
        name for name in ("text", "vision", "tools", "structured_output")
        if bool(data.get(f"supports_{name}"))
    }
    if not caps:
        raise AiConfigError("至少声明一种能力")
    return frozenset(caps)


def _check_route_caps(feature_key: str, caps: frozenset[str]) -> None:
    meta = FEATURES.get(feature_key)
    if not meta:
        raise AiConfigError(f"未知功能键：{feature_key}")
    missing = meta["required"] - caps
    if missing:
        raise AiConfigError(
            f"功能「{meta['label']}」要求模型具备："
            + "、".join(_CAP_LABELS.get(x, x) for x in sorted(missing))
        )


def _key_state(provider: AiProvider) -> tuple[str, str]:
    if provider.api_key_cipher:
        try:
            preview = mask_secret(decrypt_secret(provider.api_key_cipher))
        except SecretError:
            return "invalid", "密文无法解密"
        return "db", preview
    value = env_secret(provider.api_key_env)
    if value:
        return "env", mask_secret(value)
    return "missing", ""


def provider_to_dict(provider: AiProvider, model_count: int = 0) -> dict:
    key_state, preview = _key_state(provider)
    return {
        "id": provider.id,
        "provider_key": provider.provider_key,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key_env": provider.api_key_env,
        "key_state": key_state,
        "key_preview": preview,
        "timeout_seconds": float(provider.timeout_seconds),
        "max_retries": provider.max_retries,
        "extra_headers": provider.extra_headers or {},
        "status": provider.status,
        "remark": provider.remark,
        "model_count": model_count,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def model_to_dict(model: AiModel, provider: AiProvider | None, routes: list[str] | None = None) -> dict:
    caps = {name for name in ("text", "vision", "tools", "structured_output")
            if getattr(model, f"supports_{name}")}
    return {
        "id": model.id,
        "alias": model.alias,
        "provider_id": model.provider_id,
        "provider_key": provider.provider_key if provider else "",
        "provider_name": provider.name if provider else "",
        "provider_status": provider.status if provider else "missing",
        "upstream_name": model.upstream_name,
        "capabilities": sorted(caps),
        "structured_method": model.structured_method,
        "timeout_seconds": float(model.timeout_seconds) if model.timeout_seconds is not None else None,
        "extra_body": model.extra_body or {},
        "params": model.params or {},
        "selectable_for_chat": bool(model.selectable_for_chat),
        "status": model.status,
        "sort_order": model.sort_order,
        "remark": model.remark,
        "routes": routes or [],
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
    }


def route_to_dict(route: AiFeatureRoute | None, feature_key: str, models: dict[str, AiModel]) -> dict:
    meta = FEATURES[feature_key]
    alias = route.model_alias if route else ""
    model = models.get(alias)
    issues: list[str] = []
    if not route or not route.enabled:
        issues.append("未启用，运行时回落 .env")
    elif not model:
        issues.append(f"模型 {alias} 不存在")
    elif model.status != "active":
        issues.append(f"模型 {alias} 已停用")
    elif meta["required"] - {
        name for name in ("text", "vision", "tools", "structured_output")
        if getattr(model, f"supports_{name}")
    }:
        issues.append("模型能力不满足该功能要求")
    return {
        "id": route.id if route else None,
        "feature_key": feature_key,
        "label": meta["label"],
        "desc": meta["desc"],
        "required": sorted(meta["required"]),
        "model_alias": alias,
        "timeout_seconds": float(route.timeout_seconds) if route and route.timeout_seconds is not None else None,
        "params_override": route.params_override if route else {},
        "enabled": bool(route.enabled) if route else False,
        "remark": route.remark if route else "",
        "issues": issues,
        "updated_at": route.updated_at.isoformat() if route and route.updated_at else None,
    }


def list_payload(db: Session) -> dict:
    providers = db.query(AiProvider).order_by(AiProvider.id).all()
    models = db.query(AiModel).order_by(AiModel.sort_order, AiModel.alias).all()
    routes = db.query(AiFeatureRoute).all()
    model_map = {m.alias: m for m in models}
    route_by_alias: dict[str, list[str]] = {}
    for route in routes:
        if route.enabled:
            route_by_alias.setdefault(route.model_alias, []).append(
                FEATURES.get(route.feature_key, {}).get("label", route.feature_key)
            )
    provider_map = {p.id: p for p in providers}
    counts: dict[int, int] = {}
    for model in models:
        counts[model.provider_id] = counts.get(model.provider_id, 0) + 1
    route_map = {r.feature_key: r for r in routes}
    return {
        "providers": [provider_to_dict(p, counts.get(p.id, 0)) for p in providers],
        "models": [model_to_dict(m, provider_map.get(m.provider_id),
                                 route_by_alias.get(m.alias, [])) for m in models],
        "routes": [route_to_dict(route_map.get(key), key, model_map) for key in FEATURES],
        "features": [
            {"key": key, "label": meta["label"], "desc": meta["desc"],
             "required": sorted(meta["required"])}
            for key, meta in FEATURES.items()
        ],
        "snapshot": {"source": get_snapshot().source},
    }


def _provider(db: Session, provider_id: int) -> AiProvider:
    row = db.get(AiProvider, provider_id)
    if row is None:
        raise AiConfigError("来源不存在", 404)
    return row


def _assert_key_free(db: Session, provider_key: str, exclude_id: int | None = None) -> None:
    query = db.query(AiProvider).filter(AiProvider.provider_key == provider_key)
    if exclude_id is not None:
        query = query.filter(AiProvider.id != exclude_id)
    if query.first():
        raise AiConfigError(f"来源标识 {provider_key} 已存在")


def _routes_for_model(db: Session, alias: str) -> list[AiFeatureRoute]:
    return db.query(AiFeatureRoute).filter(
        AiFeatureRoute.model_alias == alias, AiFeatureRoute.enabled.is_(True)
    ).all()


def save_provider(db: Session, provider_id: int | None, data: dict, user: User) -> dict:
    key = (data.get("provider_key") or "").strip()
    if not _KEY_RE.match(key):
        raise AiConfigError("来源标识只能用小写字母、数字、- 与 _，2~48 位，且以字母或数字开头")
    name = (data.get("name") or "").strip()
    if not name:
        raise AiConfigError("来源名称不能为空")
    base_url = _clean_url(data.get("base_url") or "")
    env_name = (data.get("api_key_env") or "AI_API_KEY").strip()
    if not _ENV_RE.match(env_name):
        raise AiConfigError("密钥变量名只能包含大写字母、数字与下划线")
    headers = _clean_dict(data.get("extra_headers", {}), "附加请求头")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
        raise AiConfigError("附加请求头的键和值都必须是字符串")

    _assert_key_free(db, key, provider_id)
    row = _provider(db, provider_id) if provider_id else AiProvider(provider_key=key)

    if data.get("status") == "disabled" and row.id:
        active_models = db.query(AiModel).filter(
            AiModel.provider_id == row.id, AiModel.status == "active"
        ).all()
        used = [m.alias for m in active_models if _routes_for_model(db, m.alias)]
        if used:
            raise AiConfigError(
                f"该来源下有启用中的功能路由引用模型：{'、'.join(used)}，请先停用对应路由"
            )

    row.provider_key = key
    row.name = name
    row.base_url = base_url
    row.api_key_env = env_name
    row.timeout_seconds = data.get("timeout_seconds", 30)
    row.max_retries = data.get("max_retries", 1)
    row.extra_headers = headers
    row.status = data.get("status", "active")
    row.remark = (data.get("remark") or "").strip()
    row.updated_by = user.id
    if data.get("clear_api_key"):
        row.api_key_cipher = None
    api_key = (data.get("api_key") or "").strip()
    if api_key:
        try:
            row.api_key_cipher = encrypt_secret(api_key)
        except SecretError as exc:
            raise AiConfigError(str(exc)) from exc

    if provider_id is None:
        db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AiConfigError("来源保存失败：标识重复或被模型引用", 409) from exc
    db.refresh(row)
    invalidate_model_config()
    return provider_to_dict(row, db.query(AiModel).filter(AiModel.provider_id == row.id).count())


def delete_provider(db: Session, provider_id: int) -> None:
    row = _provider(db, provider_id)
    if db.query(AiModel).filter(AiModel.provider_id == provider_id).count():
        raise AiConfigError("该来源下仍有模型，请先删除或迁移模型", 409)
    db.delete(row)
    db.commit()
    invalidate_model_config()


def save_model(db: Session, model_id: int | None, data: dict, user: User) -> dict:
    alias = (data.get("alias") or "").strip()
    if not _ALIAS_RE.match(alias):
        raise AiConfigError("模型别名只能用字母、数字、点、- 与 _，1~64 位")
    upstream = (data.get("upstream_name") or "").strip()
    if not upstream:
        raise AiConfigError("上游模型名不能为空")
    provider = _provider(db, int(data.get("provider_id") or 0))
    if provider.status != "active":
        raise AiConfigError("不能挂到已停用的来源")
    caps = _clean_caps(data)
    method = data.get("structured_method") or "json_schema"
    if method not in ("json_schema", "function_calling", "json_mode"):
        raise AiConfigError("结构化方式不合法")
    extra_body = _clean_dict(data.get("extra_body", {}), "extra_body")
    params = _clean_dict(data.get("params", {}), "params")
    unknown = set(params) - PARAM_KEYS
    if unknown:
        raise AiConfigError(f"不支持的模型参数：{'、'.join(sorted(unknown))}")

    query = db.query(AiModel).filter(AiModel.alias == alias)
    if model_id:
        query = query.filter(AiModel.id != model_id)
    if query.first():
        raise AiConfigError(f"模型别名 {alias} 已存在")

    row = db.get(AiModel, model_id) if model_id else AiModel(alias=alias)
    if row is None:
        raise AiConfigError("模型不存在", 404)
    if model_id and row.alias != alias:
        raise AiConfigError("别名已被会话与路由引用，创建后不可修改")

    if data.get("status") == "disabled" or provider.status != "active":
        used = [r.feature_key for r in _routes_for_model(db, row.alias)]
        if used:
            raise AiConfigError(
                f"该模型正被功能路由使用：{'、'.join(FEATURES.get(x, {}).get('label', x) for x in used)}，请先停用路由"
            )
    if data.get("status") == "active":
        for route in _routes_for_model(db, row.alias):
            _check_route_caps(route.feature_key, caps)

    row.alias = alias
    row.provider_id = provider.id
    row.upstream_name = upstream
    row.supports_text = "text" in caps
    row.supports_vision = "vision" in caps
    row.supports_tools = "tools" in caps
    row.supports_structured_output = "structured_output" in caps
    row.structured_method = method
    row.timeout_seconds = data.get("timeout_seconds")
    row.extra_body = extra_body
    row.params = params
    row.selectable_for_chat = bool(data.get("selectable_for_chat", True))
    row.status = data.get("status", "active")
    row.sort_order = int(data.get("sort_order") or 0)
    row.remark = (data.get("remark") or "").strip()

    if model_id is None:
        db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AiConfigError("模型保存失败：别名重复或被路由引用", 409) from exc
    db.refresh(row)
    invalidate_model_config()
    routes = [FEATURES.get(r.feature_key, {}).get("label", r.feature_key)
              for r in _routes_for_model(db, row.alias)]
    return model_to_dict(row, provider, routes)


def delete_model(db: Session, model_id: int) -> None:
    row = db.get(AiModel, model_id)
    if row is None:
        raise AiConfigError("模型不存在", 404)
    used = _routes_for_model(db, row.alias)
    if used:
        raise AiConfigError(
            "该模型正被功能路由使用："
            + "、".join(FEATURES.get(r.feature_key, {}).get("label", r.feature_key) for r in used)
            + "，请先改配或停用路由",
            409,
        )
    db.delete(row)
    db.commit()
    invalidate_model_config()


def save_route(db: Session, feature_key: str, data: dict, user: User) -> dict:
    if feature_key not in FEATURES:
        raise AiConfigError("未知功能键", 404)
    alias = (data.get("model_alias") or "").strip()
    model = db.query(AiModel).filter(AiModel.alias == alias).first()
    if model is None:
        raise AiConfigError(f"模型 {alias} 不存在")
    if model.status != "active":
        raise AiConfigError(f"模型 {alias} 已停用")
    caps = {name for name in ("text", "vision", "tools", "structured_output")
            if getattr(model, f"supports_{name}")}
    if data.get("enabled", True):
        _check_route_caps(feature_key, caps)
    override = _clean_dict(data.get("params_override", {}), "参数覆盖")
    unknown = set(override) - PARAM_KEYS - {"extra_body"}
    if unknown:
        raise AiConfigError(f"参数覆盖只允许模型参数与 extra_body，不支持：{'、'.join(sorted(unknown))}")
    if "extra_body" in override:
        _clean_dict(override["extra_body"], "extra_body")

    row = db.query(AiFeatureRoute).filter(AiFeatureRoute.feature_key == feature_key).first()
    if row is None:
        row = AiFeatureRoute(feature_key=feature_key)
        db.add(row)
    row.model_alias = alias
    row.timeout_seconds = data.get("timeout_seconds")
    row.params_override = override
    row.enabled = bool(data.get("enabled", True))
    row.remark = (data.get("remark") or "").strip()
    db.commit()
    db.refresh(row)
    invalidate_model_config()
    models = {m.alias: m for m in db.query(AiModel).all()}
    return route_to_dict(row, feature_key, models)


def delete_route(db: Session, feature_key: str) -> None:
    row = db.query(AiFeatureRoute).filter(AiFeatureRoute.feature_key == feature_key).first()
    if row is None:
        raise AiConfigError("该功能尚未配置路由", 404)
    db.delete(row)
    db.commit()
    invalidate_model_config()


def _reply_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _run_ping(client: ChatOpenAI) -> dict:
    started = time.monotonic()
    response = client.invoke("ping，只回复 pong")
    return {
        "ok": True,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reply": _reply_text(response.content)[:120],
    }


def test_provider(db: Session, provider_id: int, model_alias: str | None = None) -> dict:
    provider = _provider(db, provider_id)
    query = db.query(AiModel).filter(AiModel.provider_id == provider_id)
    model = (query.filter(AiModel.alias == model_alias).first() if model_alias
             else query.order_by(AiModel.sort_order, AiModel.alias).first())
    if model is None:
        raise AiConfigError("该来源下还没有模型，无法测试")
    key_state, _ = _key_state(provider)
    if key_state == "missing":
        raise AiConfigError(f"来源密钥未配置（变量 {provider.api_key_env}）")
    try:
        from app.ai.models.secrets import resolve_secret
        key = resolve_secret(provider.api_key_env, provider.api_key_cipher)
        kwargs = {
            "model": model.upstream_name,
            "api_key": key,
            "base_url": normalize_base_url(provider.base_url),
            "timeout": min(float(provider.timeout_seconds), 30.0),
            "max_retries": 0,
        }
        if provider.extra_headers:
            kwargs["default_headers"] = provider.extra_headers
        if model.extra_body:
            kwargs["extra_body"] = model.extra_body
        params = {k: v for k, v in (model.params or {}).items() if k in PARAM_KEYS}
        kwargs.update(params)
        kwargs["max_tokens"] = 16
        result = _run_ping(ChatOpenAI(**kwargs))
    except AiConfigError:
        raise
    except Exception as exc:
        logger.info("AI 来源测试失败：provider=%s err=%s", provider.provider_key, type(exc).__name__)
        return {"ok": False, "error": f"连接失败：{type(exc).__name__}: {str(exc)[:180]}"}
    return {"provider": provider.provider_key, "model": model.alias, **result}


def test_model(db: Session, model_id: int) -> dict:
    model = db.get(AiModel, model_id)
    if model is None:
        raise AiConfigError("模型不存在", 404)
    try:
        resolved = resolve_model(None, model.alias, required="text", timeout=30.0)
        chat = resolved.chat
        chat.max_tokens = 16
        result = _run_ping(chat)
    except Exception as exc:
        logger.info("AI 模型测试失败：alias=%s err=%s", model.alias, type(exc).__name__)
        return {"ok": False, "error": f"调用失败：{type(exc).__name__}: {str(exc)[:180]}"}
    return {"model": model.alias, "provider": resolved.provider_key, **result}


def apply_config() -> dict:
    invalidate_model_config()
    snap = get_snapshot()
    return {"ok": True, "source": snap.source,
            "providers": len(snap.providers), "models": len(snap.models),
            "routes": sum(1 for r in snap.routes.values() if r.enabled)}


def page_context(db: Session) -> dict:
    return {"config": list_payload(db),
            "snapshot_source": get_snapshot().source}
