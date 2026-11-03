"""个人信息 service：基本资料更新（昵称/性别/年龄）与密码修改。

users 表已含 display_name/gender/age（注册基础信息），本模块只更新既有列，不改表结构。
校验口径与注册（auth.router_pages）完全一致。
"""
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User

GENDERS = ("男", "女")


def update_profile(
    db: Session,
    user: User,
    display_name: str,
    gender: str = "",
    age: str = "",
) -> User:
    """更新昵称/性别/年龄；返回刷新后的 User（updated_at 由 ORM onupdate 维护）。"""
    display_name = display_name.strip()
    if not display_name:
        raise AppError(400, "请填写昵称")
    if len(display_name) > 32:
        raise AppError(400, "昵称最长 32 个字符")

    gender_val: str | None = None
    if gender.strip():
        gender_val = gender.strip()
        if gender_val not in GENDERS:
            raise AppError(400, "性别取值不正确")

    age_val: int | None = None
    if age.strip():
        try:
            age_val = int(age.strip())
            if not (1 <= age_val <= 120):
                raise ValueError
        except ValueError:
            raise AppError(400, "年龄需为 1~120 的整数")

    user.display_name = display_name
    user.gender = gender_val
    user.age = age_val
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    """修改密码：先校验当前密码，再校验新密码强度，成功即更新哈希。"""
    if not verify_password(current_password, user.password_hash):
        raise AppError(400, "当前密码不正确")
    if len(new_password) < 6:
        raise AppError(400, "新密码长度至少 6 位")
    if new_password == current_password:
        raise AppError(400, "新密码不能与当前密码相同")
    user.password_hash = hash_password(new_password)
    db.commit()
