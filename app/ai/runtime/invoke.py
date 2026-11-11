"""Minimal structured LangChain invocation with bounded diagnostics."""
import logging
import time
from typing import TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.ai.models.registry import get_model
from app.ai.prompts.loader import load_prompt
from config import settings

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
        # json_schema lets the provider enforce the schema while decoding.
        chain = prompt | model.with_structured_output(schema, method="json_schema", strict=True)
        result = chain.invoke({"input_text": input_text})
        return schema.model_validate(result)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI output validation failed: model=%s prompt=%s", model_name, prompt_id)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI call failed: model=%s prompt=%s elapsed_ms=%d",
                       model_name, prompt_id, int((time.monotonic() - started) * 1000))
        raise AIServiceError("模型服务暂不可用") from exc


def invoke_ai_import(
    *,
    model_name: str,
    prompt_id: str,
    schema: type[T],
    input_text: str,
    image_urls: list[str],
    variables: dict[str, str],
) -> dict:
    """一次导入调用：文字 + 可选多张图片 → schema 约束下的 dict。"""
    started = time.monotonic()
    model = get_model(
        model_name,
        required="vision" if image_urls else "structured_output",
        timeout=settings.ai_import_timeout_seconds,
    )
    prompt = load_prompt(prompt_id, **variables)
    messages = prompt.format_messages(input_text=input_text or "请从这些图片里识别运动记录。")
    if image_urls:
        content = [{"type": "text", "text": input_text or "请从这些图片里识别运动记录。"}]
        content += [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
        messages[-1] = HumanMessage(content=content)
    try:
        result = model.with_structured_output(schema, method="json_schema", strict=True).invoke(messages)
        if result is None:
            raise AIServiceError("模型未返回结构化结果")
        return result.model_dump(mode="json")
    except AIServiceError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI import output validation failed: model=%s prompt=%s", model_name, prompt_id)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI import call failed: model=%s prompt=%s elapsed_ms=%d",
                       model_name, prompt_id, int((time.monotonic() - started) * 1000))
        raise AIServiceError("模型服务暂不可用") from exc
