"""V2.0 model boundary, prompt validation, and probe authorization."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.models.registry import MODELS, ModelConfigurationError, get_model
from app.ai.prompts.loader import load_prompt
from app.core.deps import get_current_user
from app.modules.electronic_trainer.router_api import ProbeOut
from database import get_db
from main import app


def test_model_registry_and_capability(monkeypatch):
    monkeypatch.setattr("app.ai.models.registry.settings.ai_api_key", "test-key")
    assert set(MODELS) == {
        "deepseek-v4.1-flash", "qwen3.8-flash", "qwen3.8-2.4t-a95b"
    }
    assert get_model("qwen3.8-flash").model_name == "qwen3.8-flash"
    with pytest.raises(ModelConfigurationError):
        get_model("unknown")
    with pytest.raises(ModelConfigurationError):
        get_model("qwen3.8-flash", required="vision")


def test_prompt_version_and_variables():
    prompt = load_prompt("foundation_probe.v1", purpose="check")
    assert len(prompt.invoke({"input_text": "ping"}).messages) == 2
    with pytest.raises(ValueError):
        load_prompt("foundation_probe.v1")
    with pytest.raises(ValueError):
        load_prompt("../config.py", purpose="check")


def test_probe_requires_login():
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            assert client.get("/api/electronic-trainer/models").status_code == 401
            assert client.post("/api/electronic-trainer/probe", json={"text": "ping"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_probe_uses_structured_runtime(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(
        "app.modules.electronic_trainer.router_api.invoke_structured",
        lambda **kwargs: ProbeOut(answer="ok"),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/electronic-trainer/probe",
                json={"model": "qwen3.8-flash", "text": "ping"},
            )
        assert response.status_code == 200
        assert response.json() == {
            "model": "qwen3.8-flash",
            "prompt_version": "foundation_probe.v1",
            "answer": "ok",
        }
    finally:
        app.dependency_overrides.clear()
