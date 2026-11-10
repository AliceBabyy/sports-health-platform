"""Minimal structured LangChain invocation with bounded diagnostics."""
import logging
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.models.registry import get_model
from app.ai.prompts.loader import load_prompt

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class AIServiceError(Exception):
    pass


def invoke_structured(
    *,
    model_name: str | None,
    prompt_id: str,
    schema: type[T],
    input_text: str,
    variables: dict[str, str],
) -> T:
    started = time.monotonic()
    model = get_model(model_name, required="structured_output")
    prompt = load_prompt(prompt_id, **variables)
    try:
        # json_mode avoids provider-specific tool-call output for this first probe.
        chain = prompt | model.with_structured_output(schema, method="json_mode")
        result = chain.invoke({"input_text": input_text})
        return schema.model_validate(result)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI output validation failed: model=%s prompt=%s", model_name, prompt_id)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI call failed: model=%s prompt=%s elapsed_ms=%d",
                       model_name, prompt_id, int((time.monotonic() - started) * 1000))
        raise AIServiceError("模型服务暂不可用") from exc
