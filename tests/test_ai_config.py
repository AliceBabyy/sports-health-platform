"""DB 配置解析：功能键 → 别名 → 来源，能力/密钥/超时/extra_body 合并。"""
import pytest

from app.ai.models import registry
from app.ai.models.registry import (
    ModelConfig,
    ModelConfigurationError,
    ProviderConfig,
    RouteConfig,
    Snapshot,
    resolve_model,
)
from app.ai.models.secrets import decrypt_secret, encrypt_secret


def _snapshot(*, caps=None, status="active", cipher=None):
    caps = caps or {"text", "tools", "structured_output"}
    provider = ProviderConfig(
        id=1, provider_key="addzero", name="AddZero", base_url="company-ai.lyokm.cn",
        api_key_env="A_AI_API_KEY", api_key_cipher=cipher, timeout_seconds=30.0,
        max_retries=2, extra_headers={"X-Tenant": "sh"}, status="active",
    )
    model = ModelConfig(
        id=1, alias="deepseek-v4.1-flash", provider_id=1, upstream_name="deepseek-flash",
        capabilities=frozenset(caps), structured_method="function_calling",
        timeout_seconds=20.0, extra_body={"enable_thinking": True},
        params={"temperature": 0.3, "max_tokens": 800, "unknown_key": 1},
        selectable_for_chat=True, status=status, sort_order=0,
    )
    route = RouteConfig(
        feature_key="agent.chat", model_alias="deepseek-v4.1-flash",
        timeout_seconds=12.0,
        params_override={"extra_body": {"enable_thinking": False}, "temperature": 0.1},
        enabled=True,
    )
    return Snapshot(providers={1: provider}, models={"deepseek-v4.1-flash": model},
                    routes={"agent.chat": route})


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setattr(registry, "get_snapshot", lambda force=False: _snapshot())
    monkeypatch.setattr(registry.settings, "a_ai_api_key", "sk-test-1234", raising=False)
    return registry


def test_alias_provider_and_upstream_are_separate(fake):
    resolved = resolve_model("agent.chat")
    assert resolved.alias == "deepseek-v4.1-flash"
    assert resolved.upstream_name == "deepseek-flash"
    assert resolved.chat.model_name == "deepseek-flash"
    assert resolved.chat.openai_api_base == "https://company-ai.lyokm.cn"
    assert resolved.chat.max_retries == 2
    assert resolved.chat.default_headers == {"X-Tenant": "sh"}
    assert resolved.chat.openai_api_key.get_secret_value() == "sk-test-1234"


def test_route_timeout_and_param_merge(fake):
    resolved = resolve_model("agent.chat")
    assert resolved.timeout == 12.0
    assert resolved.structured_method == "function_calling"
    assert resolved.extra_body == {"enable_thinking": False}
    assert resolved.params == {"temperature": 0.1, "max_tokens": 800}
    assert resolved.chat.temperature == 0.1
    assert resolve_model("agent.chat", timeout=8).timeout == 8.0


def test_capability_contract_rejects_route(fake):
    snap = _snapshot(caps={"text", "structured_output"})
    registry.get_snapshot = lambda force=False: snap
    with pytest.raises(ModelConfigurationError) as exc:
        resolve_model("agent.chat")
    assert "工具调用" in str(exc.value)


def test_disabled_model_is_not_silently_replaced(fake):
    snap = _snapshot(status="disabled")
    registry.get_snapshot = lambda force=False: snap
    with pytest.raises(ModelConfigurationError) as exc:
        resolve_model("agent.chat")
    assert "已停用" in str(exc.value)


def test_encrypted_key_takes_precedence(fake):
    snap = _snapshot(cipher=encrypt_secret("sk-db-9999"))
    registry.get_snapshot = lambda force=False: snap
    resolved = resolve_model("agent.chat")
    assert resolved.chat.openai_api_key.get_secret_value() == "sk-db-9999"
    assert decrypt_secret(snap.providers[1].api_key_cipher) == "sk-db-9999"


def test_dialog_models_only_include_tool_models(fake):
    assert registry.chat_model_names() == ["deepseek-v4.1-flash"]
    assert registry.is_chat_model("deepseek-v4.1-flash")
    assert not registry.is_chat_model("unknown")


def test_admin_service_encrypts_key_and_enforces_route_caps(db):
    from types import SimpleNamespace

    from app.modules.system.ai_config import service
    from app.modules.system.ai_config.models import AiProvider

    user = SimpleNamespace(id=1)
    provider = service.save_provider(db, None, {
        "provider_key": "tmp-test", "name": "临时来源",
        "base_url": "company-ai.lyokm.cn", "api_key_env": "A_AI_API_KEY",
        "api_key": "sk-db-secret-9999", "clear_api_key": False,
        "timeout_seconds": 30, "max_retries": 1, "extra_headers": {},
        "status": "active", "remark": "",
    }, user)
    assert provider["key_state"] == "db"
    row = db.query(AiProvider).filter(AiProvider.provider_key == "tmp-test").one()
    assert decrypt_secret(row.api_key_cipher) == "sk-db-secret-9999"

    model = service.save_model(db, None, {
        "alias": "tmp-test-model", "provider_id": provider["id"],
        "upstream_name": "deepseek-v4.1-flash",
        "supports_text": True, "supports_vision": False,
        "supports_tools": False, "supports_structured_output": True,
        "structured_method": "json_schema", "timeout_seconds": None,
        "extra_body": {}, "params": {}, "selectable_for_chat": False,
        "status": "active", "sort_order": 0, "remark": "",
    }, user)
    with pytest.raises(service.AiConfigError):
        service.save_route(db, "agent.chat", {
            "feature_key": "agent.chat", "model_alias": "tmp-test-model",
            "timeout_seconds": None, "params_override": {}, "enabled": True, "remark": "",
        }, user)
    route = service.save_route(db, "agent.skill_parse", {
        "feature_key": "agent.skill_parse", "model_alias": "tmp-test-model",
        "timeout_seconds": 30, "params_override": {}, "enabled": True, "remark": "",
    }, user)
    assert route["model_alias"] == "tmp-test-model"
    with pytest.raises(service.AiConfigError):
        service.delete_model(db, model["id"])
    service.delete_route(db, "agent.skill_parse")
    service.delete_model(db, model["id"])
    service.delete_provider(db, provider["id"])
