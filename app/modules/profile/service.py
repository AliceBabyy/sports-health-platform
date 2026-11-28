"""个人信息 service：基本资料更新、密码修改与健康档案。

health_profile 现在只存“专项 skill 生成的问题 + 答案”，不再有固定 10 题或
跨方面混合问卷。读取时按 skill_key 聚合为套装视图；保存时按套/题更新答案，
健康档案测试角色通过受控工具把每批题合并进该专项当前档案。
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.access import is_female
from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User
from app.modules.body.models import BodyBasicRecord, BodyBasicGoalRecord, BodyDimensionsRecord, BodyDimensionsGoalRecord
from app.modules.cycle.models import PeriodLog, PeriodRecord, PeriodSetting
from app.modules.dance.models import DanceNote, DanceRecord
from app.modules.profile import questionnaire
from app.modules.profile.aspect_skills import PROFILE_SKILL_MAP, skill_name
from app.modules.profile.models import HealthProfile
from app.modules.swim.models import SwimNote, SwimRecord
from app.modules.training.models import TrainingNote, TrainingRecord, TrainingRecordItem

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


def delete_account(db: Session, user: User, mode: str, current_password: str) -> None:
    if mode not in ("retain", "purge"):
        raise AppError(400, "注销方式不正确")
    if not verify_password(current_password, user.password_hash):
        raise AppError(400, "当前密码不正确")
    try:
        if mode == "retain":
            user.status = "停用"
        else:
            for parent, child, key in (
                (TrainingRecord, TrainingRecordItem, "training_id"),
                (TrainingRecord, TrainingNote, "training_id"),
                (SwimRecord, SwimNote, "swim_id"),
                (DanceRecord, DanceNote, "dance_id"),
            ):
                ids = db.query(parent.id).filter(parent.user_id == user.id)
                db.query(child).filter(getattr(child, key).in_(ids)).delete(synchronize_session=False)
            for model in (
                BodyBasicRecord, BodyBasicGoalRecord, BodyDimensionsRecord, BodyDimensionsGoalRecord,
                PeriodSetting, PeriodRecord, PeriodLog, TrainingRecord, SwimRecord, DanceRecord,
                HealthProfile,
            ):
                db.query(model).filter(model.user_id == user.id).delete(synchronize_session=False)
            db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise


@dataclass
class HealthProfileView:
    """按专项聚合后的只读视图。"""

    user_id: int
    entries: list[HealthProfile]
    sets: list[dict]  # 每个 skill 最近一套，供页面展示
    all_sets: list[dict]  # 全部套装，供 Agent 读取历史

    @property
    def filled(self) -> bool:
        return bool(self.all_sets)

    @property
    def set_count(self) -> int:
        return len(self.all_sets)

    @property
    def skill_count(self) -> int:
        return len({item["skill_key"] for item in self.all_sets})

    @property
    def created_at(self) -> datetime | None:
        return min((entry.created_at for entry in self.entries), default=None)

    @property
    def updated_at(self) -> datetime | None:
        return max((entry.updated_at for entry in self.entries), default=None)

    def latest_for(self, skill_key: str) -> dict | None:
        return questionnaire.latest_set(self.all_sets, skill_key)


def _entries(db: Session, user_id: int) -> list[HealthProfile]:
    return (
        db.query(HealthProfile)
        .filter(HealthProfile.user_id == user_id)
        .order_by(
            HealthProfile.set_generated_at,
            HealthProfile.sort_order,
            HealthProfile.id,
        )
        .all()
    )


def _view(db: Session, user_id: int) -> HealthProfileView | None:
    entries = _entries(db, user_id)
    if not entries:
        return None
    all_sets = questionnaire.sets_from_entries(entries)
    if not all_sets:
        return None
    return HealthProfileView(
        user_id=user_id,
        entries=entries,
        sets=questionnaire.latest_sets_by_skill(all_sets),
        all_sets=all_sets,
    )


def get_health_profile(db: Session, user_id: int) -> HealthProfileView | None:
    """读取按专项聚合的档案；没有任何套装返回 None。"""
    return _view(db, user_id)


def _item_value(item, name: str, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def save_health_profile_items(
    db: Session,
    user: User,
    items: list[dict],
) -> HealthProfileView | None:
    """页面保存：按 (set_id, local_key) 更新已有题目答案。

    只允许更新当前用户已存储的套和题；空答案保留该题（显示为空输入框）。
    """
    if not items:
        raise AppError(400, "没有要保存的档案内容")

    entries = _entries(db, user.id)
    entry_map = {(entry.set_id, entry.local_key): entry for entry in entries}
    pending: list[tuple[HealthProfile, str | None]] = []
    for item in items:
        set_id = str(_item_value(item, "set_id", "") or "").strip()
        local_key = str(_item_value(item, "local_key", "") or "").strip()
        raw = _item_value(item, "answer", "")
        if not isinstance(raw, str):
            raise AppError(400, f"{local_key} 的答案须为文本")
        entry = entry_map.get((set_id, local_key))
        if entry is None:
            raise AppError(400, f"档案题目不存在：{set_id}/{local_key}")
        text = raw.strip()
        if len(text) > entry.max_length:
            raise AppError(400, f"「{entry.label}」最多 {entry.max_length} 字")
        pending.append((entry, text or None))

    for entry, text in pending:
        entry.answer = text
    db.commit()
    return get_health_profile(db, user.id)


def _page_set_questions(raw_questions, skill: dict) -> tuple[list[dict], dict[str, str | None]]:
    """校验页面手工提交的一套题；至少 1 题，答案可以为空，题数不设上限。"""
    try:
        normalized = questionnaire.normalize_page_questions(
            raw_questions, frozenset(skill["aspects"])
        )
    except ValueError as exc:
        raise AppError(400, str(exc)) from exc

    answers: dict[str, str | None] = {}
    for index, raw in enumerate(raw_questions):
        raw_answer = _item_value(raw, "answer", "")
        if raw_answer is None:
            raw_answer = ""
        if not isinstance(raw_answer, str):
            raise AppError(400, f"{normalized[index]['local_key']} 的答案须为文本")
        text = raw_answer.strip()
        if len(text) > normalized[index]["max_length"]:
            raise AppError(
                400,
                f"「{normalized[index]['label']}」最多 {normalized[index]['max_length']} 字",
            )
        answers[normalized[index]["local_key"]] = text or None
    return normalized, answers


def _check_profile_skill_access(db: Session, user_id: int, skill: dict) -> None:
    if skill["female_only"]:
        user = db.get(User, user_id)
        if user is None or not is_female(user.gender):
            raise AppError(400, "生理期档案仅适用于女性用户")


def save_health_profile_page_set(
    db: Session,
    user: User,
    skill_key: str,
    questions: list[dict],
) -> dict:
    """页面新增档案：没有该专项时建一套，已有最近一套时直接编辑它。

    页面至少 1 题，可继续追加；不创建重复套。
    """
    skill = PROFILE_SKILL_MAP.get(skill_key)
    if skill is None:
        raise AppError(400, "未知的档案专项")
    _check_profile_skill_access(db, user.id, skill)
    normalized, answers = _page_set_questions(questions, skill)

    existing = questionnaire.latest_set(
        questionnaire.sets_from_entries(_entries(db, user.id)), skill_key
    )
    if existing is not None:
        return update_health_profile_page_set(
            db, user, existing["set_id"], questions, skill_key=skill_key
        )

    set_id = questionnaire.new_set_id()
    generated_at = datetime.now()
    for question in normalized:
        key = question["local_key"]
        db.add(HealthProfile(
            user_id=user.id,
            set_id=set_id,
            skill_key=skill_key,
            aspect=question["aspect"],
            local_key=key,
            label=question["label"],
            hint=question["hint"],
            placeholder=question["placeholder"],
            max_length=question["max_length"],
            answer=answers.get(key),
            sort_order=question["sort_order"],
            set_generated_at=generated_at,
        ))
    db.commit()
    return {
        "ok": True,
        "status": "created",
        "skill_key": skill_key,
        "skill_name": skill_name(skill_key),
        "set_id": set_id,
        "question_count": len(normalized),
    }


def update_health_profile_page_set(
    db: Session,
    user: User,
    set_id: str,
    questions: list[dict],
    skill_key: str = "",
) -> dict:
    """页面编辑已有套：改问题文本、改答案，并在末尾追加 qN+1 新问题。"""
    set_entries = [
        entry for entry in _entries(db, user.id)
        if entry.set_id == set_id
    ]
    if not set_entries:
        raise AppError(400, "没有找到这套档案")
    actual_skill_key = set_entries[0].skill_key
    if skill_key and skill_key != actual_skill_key:
        raise AppError(400, "专项与档案套不匹配")
    skill = PROFILE_SKILL_MAP.get(actual_skill_key)
    if skill is None:
        raise AppError(400, "未知的档案专项")
    _check_profile_skill_access(db, user.id, skill)
    normalized, answers = _page_set_questions(questions, skill)

    entry_map = {entry.local_key: entry for entry in set_entries}
    generated_at = set_entries[0].set_generated_at
    for question in normalized:
        key = question["local_key"]
        entry = entry_map.get(key)
        if entry is None:
            db.add(HealthProfile(
                user_id=user.id,
                set_id=set_id,
                skill_key=actual_skill_key,
                aspect=question["aspect"],
                local_key=key,
                label=question["label"],
                hint=question["hint"],
                placeholder=question["placeholder"],
                max_length=question["max_length"],
                answer=answers.get(key),
                sort_order=question["sort_order"],
                set_generated_at=generated_at,
            ))
            continue
        entry.aspect = question["aspect"]
        entry.label = question["label"]
        entry.hint = question["hint"]
        entry.placeholder = question["placeholder"]
        entry.max_length = question["max_length"]
        entry.answer = answers.get(key)
        entry.sort_order = question["sort_order"]

    db.commit()
    return {
        "ok": True,
        "status": "updated",
        "skill_key": actual_skill_key,
        "skill_name": skill_name(actual_skill_key),
        "set_id": set_id,
        "question_count": len(normalized),
    }


def save_health_profile_aspect(
    db: Session,
    user_id: int,
    skill_key: str,
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """健康档案测试专用：把一批 3~10 题合并进该专项当前档案。

    单批仍按 3~10 题校验；已有档案时不再新建一套，而是：
    - 标题一致的问题覆盖字段与答案（用户本次留空则保留原答案）；
    - 新标题追加到末尾，题号顺延为 qN+1；
    - 因此保存后的总题数可以超过 10，页面展示同一套持续累积的档案。
    """
    skill = PROFILE_SKILL_MAP.get(skill_key)
    if skill is None:
        raise AppError(400, "未知的档案专项")
    if skill["female_only"]:
        user = db.get(User, user_id)
        if user is None or not is_female(user.gender):
            raise AppError(400, "生理期档案仅适用于女性用户")

    try:
        normalized = questionnaire.normalize_questions(
            questions, frozenset(skill["aspects"])
        )
        cleaned = questionnaire.validate_answers(normalized, answers)
    except ValueError as exc:
        raise AppError(400, str(exc)) from exc

    entries = _entries(db, user_id)
    all_sets = questionnaire.sets_from_entries(entries)
    latest = questionnaire.latest_set(all_sets, skill_key)
    generated_at = datetime.now()

    if latest is None:
        set_id = questionnaire.new_set_id()
        status = "created"
        for question in normalized:
            db.add(HealthProfile(
                user_id=user_id,
                set_id=set_id,
                skill_key=skill_key,
                aspect=question["aspect"],
                local_key=question["local_key"],
                label=question["label"],
                hint=question["hint"],
                placeholder=question["placeholder"],
                max_length=question["max_length"],
                answer=cleaned.get(question["local_key"]) or None,
                sort_order=question["sort_order"],
                set_generated_at=generated_at,
            ))
    else:
        set_id = latest["set_id"]
        status = "updated"
        set_entries = [entry for entry in entries if entry.set_id == set_id]
        by_label = {
            (entry.label or "").strip().casefold(): entry
            for entry in set_entries
        }
        next_order = max((entry.sort_order for entry in set_entries), default=-1) + 1
        next_no = max(
            (
                int(entry.local_key[1:])
                for entry in set_entries
                if entry.local_key and entry.local_key[1:].isdigit()
            ),
            default=0,
        ) + 1
        changed = False

        for question in normalized:
            entry = by_label.get(question["label"].casefold())
            answer = cleaned.get(question["local_key"])
            if entry is not None:
                for field in ("aspect", "label", "hint", "placeholder", "max_length"):
                    if getattr(entry, field) != question[field]:
                        setattr(entry, field, question[field])
                        changed = True
                if answer is not None and entry.answer != answer:
                    entry.answer = answer
                    changed = True
                continue

            entry = HealthProfile(
                user_id=user_id,
                set_id=set_id,
                skill_key=skill_key,
                aspect=question["aspect"],
                local_key=f"q{next_no}",
                label=question["label"],
                hint=question["hint"],
                placeholder=question["placeholder"],
                max_length=question["max_length"],
                answer=answer or None,
                sort_order=next_order,
                set_generated_at=generated_at,
            )
            db.add(entry)
            by_label[question["label"].casefold()] = entry
            next_order += 1
            next_no += 1
            changed = True

        if not changed:
            latest_answered = questionnaire.answered_count(latest)
            view = get_health_profile(db, user_id)
            return {
                "ok": True,
                "status": "already_exists",
                "skill_key": skill_key,
                "skill_name": skill_name(skill_key),
                "set_id": set_id,
                "question_count": questionnaire.question_count(latest),
                "answered_count": latest_answered,
                "filled": view is not None,
            }
        for entry in set_entries:
            entry.set_generated_at = generated_at

    db.commit()
    view = get_health_profile(db, user_id)
    saved = questionnaire.latest_set(view.sets, skill_key) if view is not None else None
    return {
        "ok": True,
        "status": status,
        "skill_key": skill_key,
        "skill_name": skill_name(skill_key),
        "set_id": set_id,
        "question_count": questionnaire.question_count(saved) if saved else 0,
        "answered_count": questionnaire.answered_count(saved) if saved else 0,
        "filled": view is not None,
    }


def clear_health_profile(db: Session, user: User) -> None:
    """清空档案：删除该用户全部档案行。"""
    db.query(HealthProfile).filter(HealthProfile.user_id == user.id).delete(
        synchronize_session=False
    )
    db.commit()
