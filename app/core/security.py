"""认证安全：bcrypt 密码哈希、会话登录态读写。"""
import bcrypt


def hash_password(plain: str) -> str:
    """bcrypt 哈希（bcrypt>=5 返回值 bytes，转 str 存库）。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
