"""来源密钥的加密存取：DB 密文（SECRET_KEY 派生 Fernet）+ .env 变量名兜底。

明文只存在于进程内存与请求体，不写日志、不回显；管理接口最多返回掩码。
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class SecretError(ValueError):
    pass


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"ai-config::{settings.secret_key}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    value = (plain or "").strip()
    if not value:
        raise SecretError("密钥不能为空")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretError("来源密钥无法解密（SECRET_KEY 可能已变更）") from exc


def env_secret(env_name: str) -> str:
    """按变量名取密钥：进程环境变量优先，其次 .env 加载进 settings 的扩展字段。"""
    name = (env_name or "").strip()
    if not name:
        return ""
    value = os.environ.get(name)
    if value:
        return value.strip()
    # pydantic-settings 的 extra=allow：A_AI_API_KEY → settings.a_ai_api_key
    value = getattr(settings, name.lower(), None)
    return str(value).strip() if value else ""


def resolve_secret(api_key_env: str, api_key_cipher: str | None) -> str:
    if api_key_cipher:
        return decrypt_secret(api_key_cipher)
    return env_secret(api_key_env)


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••"
    return f"{secret[:4]}••••{secret[-4:]}"
