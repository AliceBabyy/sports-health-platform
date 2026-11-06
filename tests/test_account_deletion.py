import pytest

from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.auth.service import authenticate, restore_user
from app.modules.body.models import BodyBasicRecord
from app.modules.cycle.models import CycleSetting
from app.modules.profile.service import delete_account
from app.modules.training.models import TrainingRecord, TrainingRecordItem
from app.core.security import hash_password
from datetime import date


def _user(db, name):
    user = User(username=name, password_hash=hash_password("secret123"), display_name=name)
    db.add(user)
    db.commit()
    return user


def test_retain_and_restore(db):
    user = _user(db, "retain")
    db.add(BodyBasicRecord(user_id=user.id, record_date=date(2026, 1, 1)))
    db.commit()
    with pytest.raises(AppError):
        delete_account(db, user, "retain", "wrong")
    assert user.status == "启用"
    delete_account(db, user, "retain", "secret123")
    assert authenticate(db, "retain", "secret123") is None
    assert db.query(BodyBasicRecord).filter_by(user_id=user.id).count() == 1
    assert not restore_user(db, user, "wrong")
    assert restore_user(db, user, "secret123")
    assert authenticate(db, "retain", "secret123") is not None


def test_purge_only_selected_user(db):
    target = _user(db, "target")
    other = _user(db, "other")
    for user in (target, other):
        db.add(BodyBasicRecord(user_id=user.id, record_date=date(2026, 1, 1)))
        db.add(CycleSetting(user_id=user.id))
        plan = TrainingRecord(user_id=user.id, date=date(2026, 1, 1))
        plan.items.append(TrainingRecordItem(exercise_name="深蹲"))
        db.add(plan)
    db.commit()
    delete_account(db, target, "purge", "secret123")
    assert db.get(User, target.id) is None
    assert db.get(User, other.id) is not None
    for model in (BodyBasicRecord, CycleSetting, TrainingRecord):
        assert db.query(model).filter_by(user_id=target.id).count() == 0
        assert db.query(model).filter_by(user_id=other.id).count() == 1
    assert db.query(TrainingRecordItem).count() == 1
