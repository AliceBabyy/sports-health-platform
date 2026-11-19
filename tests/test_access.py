"""管理员区访问控制（2026-11-19）：前缀判定、角色判定、默认角色与管理员保障幂等。"""
import pytest

from app.core.access import ADMIN_PATH_PREFIXES, ADMIN_ROLE, USER_ROLE, is_admin, is_admin_path
from app.modules.auth.admin import ensure_admin_accounts
from app.modules.auth.models import User


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/system", True),
        ("/system/scheduler", True),
        ("/api/system/scheduler/jobs", True),
        ("/systematic", False),
        ("/api/scheduler/jobs", False),
        ("/body", False),
        ("/profile/health-profile", False),
    ],
)
def test_is_admin_path(path, expected):
    assert is_admin_path(path) is expected


def test_admin_prefixes_cover_page_and_api():
    assert ADMIN_PATH_PREFIXES == ("/system", "/api/system")


def test_is_admin_by_role(db):
    normal = User(username="n1", password_hash="x", display_name="n1")
    admin = User(username="a1", password_hash="x", display_name="a1", role=ADMIN_ROLE)
    db.add_all([normal, admin])
    db.commit()
    assert is_admin(admin) is True
    assert is_admin(normal) is False
    assert is_admin(None) is False


def test_new_user_defaults_to_normal_role(db):
    user = User(username="newbie", password_hash="x", display_name="newbie")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.role == USER_ROLE


def test_ensure_admin_accounts_promotes_once(db):
    db.add_all(
        [
            User(username="first", password_hash="x", display_name="first"),
            User(username="second", password_hash="x", display_name="second"),
        ]
    )
    db.commit()

    assert ensure_admin_accounts(db) == 1
    assert db.query(User).filter(User.username == "first").one().role == ADMIN_ROLE
    assert db.query(User).filter(User.username == "second").one().role == USER_ROLE

    # 幂等：已有管理员时不再提升任何账号
    assert ensure_admin_accounts(db) == 0


def test_ensure_admin_accounts_honours_configured_usernames(db, monkeypatch):
    from config import settings

    db.add(User(username="owner", password_hash="x", display_name="owner"))
    db.commit()

    monkeypatch.setattr(settings, "admin_usernames", "owner")
    assert ensure_admin_accounts(db) == 1
    assert db.query(User).filter(User.username == "owner").one().role == ADMIN_ROLE


def test_ensure_admin_accounts_keeps_existing_admin(db):
    db.add(User(username="boss", password_hash="x", display_name="boss", role=ADMIN_ROLE))
    db.add(User(username="staff", password_hash="x", display_name="staff"))
    db.commit()

    assert ensure_admin_accounts(db) == 0
    assert db.query(User).filter(User.username == "boss").one().role == ADMIN_ROLE
