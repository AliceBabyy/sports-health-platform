"""AI 导入的共享编排：模型调用、图片编码、规范化、校验、落库。

设计要点：
- 不反向调用本项目的 /import-json 接口，直接复用各模块的 validate / persist 函数；
- 输出结构由 json_schema 在解码期强制，提示词只描述字段含义；
- 导入数据统一落成 recorded，不做计划态。
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from fastapi import UploadFile
from pydantic import BaseModel

from app.ai.models.registry import ModelConfigurationError
from app.ai.runtime.invoke import AIServiceError, invoke_ai_import
from app.core.constants import today_local
from app.core.exceptions import AppError
from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportProfile:
    """一个运动模块的 AI 导入差异：提示词、输出模型、清洗、校验、落库。"""

    sport: str
    prompt_id: str
    key: str
    schema: type[BaseModel]
    normalize: Callable[[dict, date], tuple[dict, list[str]]]
    validate: Callable[[list], tuple[list, list[dict]]]
    persist: Callable[..., tuple[list[int], dict]]
    max_items: int = 20


def _detect_mime(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def encode_images(files: list[UploadFile] | None) -> list[str]:
    """校验张数/体积/类型后转 data URL；图片只在内存里过一遍，不落盘。"""
    files = files or []
    limit_mb = settings.ai_import_max_image_bytes // (1024 * 1024)
    if len(files) > settings.ai_import_max_images:
        raise AppError(400, f"最多上传 {settings.ai_import_max_images} 张图片")
    urls: list[str] = []
    for item in files:
        content = item.file.read()
        if not content:
            raise AppError(400, "上传的图片为空")
        if len(content) > settings.ai_import_max_image_bytes:
            raise AppError(400, f"单张图片不能超过 {limit_mb}MB")
        mime = _detect_mime(content)
        if mime is None:
            raise AppError(400, "仅支持 JPG / PNG / WebP 图片")
        urls.append(f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}")
    return urls


def _meta(model_name: str, prompt_id: str, elapsed_ms: int, warnings: list[str]) -> dict:
    return {
        "model": model_name,
        "prompt_version": prompt_id,
        "elapsed_ms": elapsed_ms,
        "warnings": warnings,
    }


def run_import(
    *,
    profile: ImportProfile,
    text: str | None,
    images: list[UploadFile] | None,
    db,
    user,
) -> dict:
    text = (text or "").strip()
    if len(text) > settings.ai_import_max_prompt_chars:
        raise AppError(400, f"文字描述过长（上限 {settings.ai_import_max_prompt_chars} 字）")
    image_urls = encode_images(images)
    if not text and not image_urls:
        raise AppError(400, "请提供文字描述或至少一张图片")

    today = today_local()
    model_name = settings.ai_import_vision_model if image_urls else settings.ai_import_model
    started = time.monotonic()
    try:
        raw = invoke_ai_import(
            model_name=model_name,
            prompt_id=profile.prompt_id,
            schema=profile.schema,
            input_text=text,
            image_urls=image_urls,
            variables={"today": today.isoformat(), "weekday": "一二三四五六日"[today.weekday()]},
        )
    except ModelConfigurationError as exc:
        raise AppError(400, str(exc)) from exc
    except AIServiceError as exc:
        raise AppError(502, str(exc)) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)

    payload, warnings = profile.normalize(raw, today)
    items = payload.get(profile.key) or []
    if len(items) > profile.max_items:
        raise AppError(400, f"单次最多导入 {profile.max_items} 条，请把内容拆开再试")

    logger.info("ai import: sport=%s model=%s records=%d elapsed_ms=%d",
                profile.sport, model_name, len(items), elapsed_ms)

    base = {
        "ok": True,
        "payload": payload,
        "ai": _meta(model_name, profile.prompt_id, elapsed_ms, warnings),
    }
    if not items:
        return {**base, "imported": 0, "created_ids": [], "failed": [],
                "message": "没有识别到可导入的记录"}

    valid, errors = profile.validate(items)
    if errors:
        return {**base, "imported": 0, "created_ids": [], "failed": errors,
                "message": "识别结果未通过校验，未写入任何记录"}

    created_ids, extra = profile.persist(db, user.id, valid)
    return {**base, **extra, "imported": len(created_ids), "created_ids": created_ids,
            "failed": []}
