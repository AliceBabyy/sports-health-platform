"""个人信息 service：基本资料更新（昵称/性别/年龄）、密码修改与健康/运动档案。

users 表已含 display_name/gender/age（注册基础信息），本模块只更新既有列，不改表结构。
校验口径与注册（auth.router_pages）完全一致。
健康/运动档案存 health_profile（一用户多行，按固定 aspect 分行记录），题目 key 见 questions.py。
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User
from app.modules.body.models import BodyBasicRecord, BodyBasicGoalRecord, BodyDimensionsRecord, BodyDimensionsGoalRecord
from app.modules.cycle.models import PeriodLog, PeriodRecord, PeriodSetting
from app.modules.profile.models import HealthProfile
from app.modules.profile import probe
from app.modules.profile.questions import COMPLETION_MIN_ANSWERS, QUESTION_MAP, QUESTIONS
from app.modules.training.models import TrainingRecord, TrainingRecordItem, TrainingNote
from app.modules.swim.models import SwimRecord, SwimNote
from app.modules.dance.models import DanceRecord, DanceNote

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
    """档案行的只读聚合视图，保持页面/API 仍按 answers + custom_questions 使用。"""

    user_id: int
    entries: list[HealthProfile]
    answers: dict[str, str]
    custom_questions: dict

    @property
    def filled(self) -> bool:
        return bool(self.entries)

    @property
    def completed_at(self) -> datetime | None:
        answered = [entry for entry in self.entries if entry.answer]
        if len(answered) < COMPLETION_MIN_ANSWERS:
            return None
        return max(entry.created_at for entry in answered)

    @property
    def created_at(self) -> datetime | None:
        return min((entry.created_at for entry in self.entries), default=None)

    @property
    def updated_at(self) -> datetime | None:
        return max((entry.updated_at for entry in self.entries), default=None)


def _entries(db: Session, user_id: int) -> list[HealthProfile]:
    return (
        db.query(HealthProfile)
        .filter(HealthProfile.user_id == user_id)
        .order_by(HealthProfile.created_at, HealthProfile.id)
        .all()
    )


def _view(db: Session, user_id: int) -> HealthProfileView | None:
    entries = _entries(db, user_id)
    if not entries:
        return None
    answers = {
        entry.item_key: entry.answer
        for entry in entries
        if entry.answer and entry.answer.strip()
    }
    return HealthProfileView(
        user_id=user_id,
        entries=entries,
        answers=answers,
        custom_questions=probe.store_from_entries(entries),
    )


def get_health_profile(db: Session, user_id: int) -> HealthProfileView | None:
    """读取档案聚合视图；未填写返回 None。"""
    return _view(db, user_id)


def get_health_answers(db: Session, user_id: int) -> dict[str, str]:
    """读取档案答案字典；未填写返回空字典。"""
    row = get_health_profile(db, user_id)
    return dict(row.answers) if row else {}


def _fixed_question_order() -> dict[str, int]:
    return {question["key"]: index for index, question in enumerate(QUESTIONS)}


def _apply_fixed_answer(
    db: Session,
    user_id: int,
    entry: HealthProfile | None,
    question: dict,
    text: str,
) -> HealthProfile | None:
    """固定题写入/更新；空答案返回 None，由调用方决定是否删除旧行。"""
    if not text:
        if entry is not None:
            db.delete(entry)
        return None
    if entry is None:
        entry = HealthProfile(user_id=user_id, item_key=question["key"])
        db.add(entry)
    entry.aspect = question["aspect"]
    entry.label = question["label"]
    entry.hint = question["hint"]
    entry.placeholder = question["placeholder"]
    entry.max_length = question["max_length"]
    entry.answer = text
    entry.source = "fixed"
    entry.set_id = None
    entry.persona_key = None
    entry.set_generated_at = None
    entry.sort_order = _fixed_question_order().get(question["key"], 0)
    return entry


def save_health_profile(db: Session, user: User, answers: dict[str, str]) -> HealthProfileView | None:
    """保存档案：逐题校验后按行合并写入。

    - 固定题按 questions.py 校验；定制题按当前档案中已有的 probe 行校验。
    - 未出现在请求里的题目保持原值；固定题传空串删除该行，定制题传空串清空 answer。
    - 未知 key、非文本、超长答案一律 400，不接受前端自行编造的题目。
    - 保存后没有任何有效答案时删除该用户全部档案行，页面回到问卷态。
    """
    if not isinstance(answers, dict):
        raise AppError(400, "answers 须为对象")

    entries = _entries(db, user.id)
    entry_map = {entry.item_key: entry for entry in entries}

    # 先全量校验，再落库，避免前面的题已加入 session、后面的题报错留下半截修改。
    pending: list[tuple[str, dict | HealthProfile, str]] = []
    for key, raw in answers.items():
        if not isinstance(raw, str):
            raise AppError(400, f"「{key}」的答案须为文本")
        text = raw.strip()

        question = QUESTION_MAP.get(key)
        if question is not None:
            if len(text) > question["max_length"]:
                raise AppError(400, f"「{question['label']}」最多 {question['max_length']} 字")
            pending.append(("fixed", question, text))
            continue

        entry = entry_map.get(key)
        if entry is None or entry.source != "probe":
            raise AppError(400, f"未知题目：{key}")
        if len(text) > entry.max_length:
            raise AppError(400, f"「{entry.label}」最多 {entry.max_length} 字")
        pending.append(("probe", entry, text))

    for kind, target, text in pending:
        if kind == "fixed":
            question = target
            entry = _apply_fixed_answer(db, user.id, entry_map.get(question["key"]), question, text)
            if entry is None:
                entry_map.pop(question["key"], None)
            else:
                entry_map[question["key"]] = entry
        else:
            target.answer = text or None

    db.flush()
    remaining = (
        db.query(HealthProfile)
        .filter(HealthProfile.user_id == user.id, HealthProfile.answer.isnot(None))
        .count()
    )
    if remaining == 0:
        db.query(HealthProfile).filter(HealthProfile.user_id == user.id).delete(
            synchronize_session=False
        )
        db.commit()
        return None

    db.commit()
    return get_health_profile(db, user.id)


def save_probe_health_profile(
    db: Session,
    user_id: int,
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """受控写入“健康档案测试”角色生成的一套问题与答案。

    - 问题 3~10 个，至少覆盖 3 个固定 aspect，答案至少 1 题，只允许 q1~q10。
    - 与最新一套问题相同则更新该套答案；不同则新增一套，保留历史（最多 20 套）。
    - 旧套被挤出时同步删除该套所有行；固定题行始终保留。
    - 返回值供工具原样回给模型。
    """
    normalized = probe.normalize_questions(questions)
    cleaned = probe.validate_probe_answers(normalized, answers)

    entries = _entries(db, user_id)
    store = probe.store_from_entries(entries)
    latest = probe.latest_set(store)
    status = "created"
    answered_count = len(cleaned)
    set_id: str

    if latest is not None and probe.signature(latest["questions"]) == probe.signature(normalized):
        set_id = latest["set_id"]
        current_local = probe.latest_answers(store, {
            entry.item_key: entry.answer for entry in entries if entry.answer
        })
        target_local = {**current_local, **cleaned}
        if target_local == current_local:
            view = get_health_profile(db, user_id)
            return {
                "ok": True,
                "status": "already_exists",
                "set_id": set_id,
                "question_count": len(latest["questions"]),
                "answered_count": len(current_local),
                "filled": view is not None,
                "completed_at": view.completed_at.isoformat()
                if view and view.completed_at else None,
            }
        entry_map = {
            entry.item_key: entry
            for entry in entries
            if entry.source == "probe" and entry.set_id == set_id
        }
        for question in latest["questions"]:
            entry = entry_map.get(question["key"])
            if entry is None:
                continue
            entry.answer = target_local.get(question["local_key"]) or None
        status = "updated"
        answered_count = len(target_local)
    else:
        new_store, set_id, dropped = probe.append_set(store, normalized)
        new_set = probe.latest_set(new_store)
        if new_set is None:
            raise AppError(500, "定制问题套生成失败")
        for old_set_id in dropped:
            db.query(HealthProfile).filter(
                HealthProfile.user_id == user_id,
                HealthProfile.set_id == old_set_id,
                HealthProfile.source == "probe",
            ).delete(synchronize_session=False)
        generated_at = datetime.now()
        for order, question in enumerate(new_set["questions"]):
            text = cleaned.get(question["local_key"])
            db.add(HealthProfile(
                user_id=user_id,
                aspect=question["aspect"],
                item_key=question["key"],
                label=question["label"],
                hint=question["hint"],
                placeholder=question["placeholder"],
                max_length=question["max_length"],
                answer=text or None,
                source="probe",
                set_id=set_id,
                persona_key=question.get("persona_key") or probe.PROBE_PERSONA_KEY,
                set_generated_at=generated_at,
                sort_order=order,
            ))

    db.commit()
    view = get_health_profile(db, user_id)
    return {
        "ok": True,
        "status": status,
        "set_id": set_id,
        "question_count": len(normalized),
        "answered_count": answered_count,
        "filled": view is not None,
        "completed_at": view.completed_at.isoformat() if view and view.completed_at else None,
    }


def get_custom_questions(db: Session, user_id: int) -> dict | None:
    """读取最新一套定制问题（供页面与 API 展示）。"""
    row = get_health_profile(db, user_id)
    if row is None:
        return None
    return probe.latest_payload(row.custom_questions)


def clear_health_profile(db: Session, user: User) -> None:
    """清空档案：删除该用户全部档案行，页面回到问卷态。"""
    db.query(HealthProfile).filter(HealthProfile.user_id == user.id).delete(
        synchronize_session=False
    )
    db.commit()
