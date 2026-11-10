"""Authenticated V2.0 model connection probe."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.ai.models.registry import MODELS, ModelConfigurationError
from app.ai.runtime.invoke import AIServiceError, invoke_structured
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from config import settings

router = APIRouter(prefix="/api/electronic-trainer", tags=["electronic-trainer"])


class ProbeIn(BaseModel):
    model: str | None = None
    text: str = Field(min_length=1, max_length=200)


class ProbeOut(BaseModel):
    answer: str = Field(min_length=1)


@router.get("/models")
def list_models(user: User = Depends(get_current_user)):
    return {"models": [
        {"name": spec.name, "capabilities": sorted(spec.capabilities)}
        for spec in MODELS.values()
    ]}


@router.post("/probe")
def probe(payload: ProbeIn, user: User = Depends(get_current_user)):
    try:
        result = invoke_structured(
            model_name=payload.model,
            prompt_id="foundation_probe.v1",
            schema=ProbeOut,
            input_text=payload.text,
            variables={"purpose": "验证模型连接与结构化输出。请返回 JSON 对象，字段 answer 为回答文本"},
        )
    except ModelConfigurationError as exc:
        raise AppError(400, str(exc)) from exc
    except AIServiceError as exc:
        raise AppError(502, str(exc)) from exc
    return {"model": payload.model or settings.ai_default_model,
            "prompt_version": "foundation_probe.v1", **result.model_dump()}
