"""Minimal structured LangChain invocation with bounded diagnostics."""
import logging
import time
from typing import TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.ai.models.registry import resolve_model
from app.ai.prompts.loader import load_prompt

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class AIServiceError(Exception):
    pass


def _structured_chain(model, schema: type[T], method: str, strict: bool):
    kwargs: dict = {"method": method}
    if method != "json_mode":
        kwargs["strict"] = strict
    return model.with_structured_output(schema, **kwargs)


def invoke_structured(
    *,
    feature: str | None = None,
    model_name: str | None = None,
    prompt_id: str,
    schema: type[T],
    input_text: str,
    variables: dict[str, str],
    timeout: float | None = None,
    extra_body: dict | None = None,
) -> T:
    started = time.monotonic()
    resolved = resolve_model(feature, model_name, timeout=timeout, extra_body=extra_body)
    prompt = load_prompt(prompt_id, **variables)
    try:
        chain = prompt | _structured_chain(
            resolved.chat, schema, resolved.structured_method, strict=True
        )
        result = chain.invoke({"input_text": input_text})
        return schema.model_validate(result)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI output validation failed: model=%s prompt=%s err=%s",
                       resolved.alias, prompt_id, type(exc).__name__, exc_info=True)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI call failed: model=%s prompt=%s elapsed_ms=%d err=%s",
                       resolved.alias, prompt_id, int((time.monotonic() - started) * 1000),
                       type(exc).__name__, exc_info=True)
        raise AIServiceError("模型服务暂不可用") from exc


def invoke_ai_import(
    *,
    feature: str | None = None,
    model_name: str | None = None,
    prompt_id: str,
    schema: type[T],
    input_text: str,
    image_urls: list[str],
    variables: dict[str, str],
) -> dict:
    """一次导入调用：文字 + 可选多张图片 → schema 约束下的 dict。"""
    started = time.monotonic()
    resolved = resolve_model(feature, model_name)
    prompt = load_prompt(prompt_id, **variables)
    messages = prompt.format_messages(input_text=input_text or "请从这些图片里识别运动记录。")
    if image_urls:
        content = [{"type": "text", "text": input_text or "请从这些图片里识别运动记录。"}]
        content += [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
        messages[-1] = HumanMessage(content=content)
    try:
        result = _structured_chain(
            resolved.chat, schema, resolved.structured_method, strict=True
        ).invoke(messages)
        if result is None:
            raise AIServiceError("模型未返回结构化结果")
        return result.model_dump(mode="json")
    except AIServiceError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI import output validation failed: model=%s prompt=%s",
                       resolved.alias, prompt_id)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI import call failed: model=%s prompt=%s elapsed_ms=%d",
                       resolved.alias, prompt_id, int((time.monotonic() - started) * 1000))
        raise AIServiceError("模型服务暂不可用") from exc


async def ainvoke_structured(
    *,
    feature: str | None = None,
    model_name: str | None = None,
    prompt_id: str,
    schema: type[T],
    input_text: str,
    variables: dict[str, str],
    strict: bool = True,
) -> T:
    """异步结构化调用（Agent 斜杠解析等异步链路使用），语义与同步版一致。"""
    started = time.monotonic()
    resolved = resolve_model(feature, model_name)
    prompt = load_prompt(prompt_id, **variables)
    try:
        chain = prompt | _structured_chain(
            resolved.chat, schema, resolved.structured_method, strict
        )
        result = await chain.ainvoke({"input_text": input_text})
        return schema.model_validate(result)
    except AIServiceError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("AI async output validation failed: model=%s prompt=%s", resolved.alias, prompt_id)
        raise AIServiceError("模型返回格式无效") from exc
    except Exception as exc:
        logger.warning("AI async call failed: model=%s prompt=%s elapsed_ms=%d",
                       resolved.alias, prompt_id, int((time.monotonic() - started) * 1000))
        raise AIServiceError("模型服务暂不可用") from exc
