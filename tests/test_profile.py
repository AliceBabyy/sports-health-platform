"""个人信息单测（PR）：基本资料更新校验与落库、密码修改校验。"""
import pytest

from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User
from app.modules.profile import service


def _make_user(db) -> User:
    user = User(
        username="profileuser",
        password_hash=hash_password("oldpass123"),
        display_name="初始昵称",
        gender="女",
        age=28,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_update_profile_basic(db):
    user = _make_user(db)
    service.update_profile(db, user, "新昵称", "男", "30")
    db.refresh(user)
    assert user.display_name == "新昵称"
    assert user.gender == "男"
    assert user.age == 30
    assert user.username == "profileuser"  # 用户名不可修改


def test_update_profile_clear_optional_fields(db):
    user = _make_user(db)
    service.update_profile(db, user, "昵称", "", "")
    db.refresh(user)
    assert user.display_name == "昵称"
    assert user.gender is None
    assert user.age is None


def test_update_profile_rejects_blank_nickname(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.update_profile(db, user, "   ")
    with pytest.raises(AppError):
        service.update_profile(db, user, "x" * 33)


def test_update_profile_rejects_bad_gender_and_age(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.update_profile(db, user, "昵称", "未知")
    with pytest.raises(AppError):
        service.update_profile(db, user, "昵称", "男", "abc")
    with pytest.raises(AppError):
        service.update_profile(db, user, "昵称", "男", "0")


def test_change_password_success(db):
    user = _make_user(db)
    service.change_password(db, user, "oldpass123", "newpass123")
    db.refresh(user)
    assert verify_password("newpass123", user.password_hash)
    assert not verify_password("oldpass123", user.password_hash)


def test_change_password_rejects_wrong_current(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.change_password(db, user, "wrongpass", "newpass123")


def test_change_password_rejects_short_and_same(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.change_password(db, user, "oldpass123", "123")
    with pytest.raises(AppError):
        service.change_password(db, user, "oldpass123", "oldpass123")
