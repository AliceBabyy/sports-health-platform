"""认证 service：登录校验（不区分用户不存在/密码错）、注册创建用户。"""
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.modules.auth.models import User


def authenticate(db: Session, username: str, password: str) -> User | None:
    """校验账号密码；失败统一返回 None，不暴露差异细节。"""
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(
    db: Session,
    username: str,
    password: str,
    display_name: str = "",
    gender: str | None = None,
    age: int | None = None,
) -> User:
    """注册：账号密码 + 基础信息（display_name 必填、性别/年龄可填；身高走 body 记录）。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        gender=gender or None,
        age=age,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
