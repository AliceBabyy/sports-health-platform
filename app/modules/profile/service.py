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


def get_health_profile(db: Session, user_id: int) -> HealthProfile | None:
    """读取档案（1:1 单行），未填写返回 None。"""
    return db.query(HealthProfile).filter(HealthProfile.user_id == user_id).first()


def get_health_answers(db: Session, user_id: int) -> dict[str, str]:
    """读取档案答案字典；未填写返回空字典。"""
    row = get_health_profile(db, user_id)
    return dict(row.answers or {}) if row else {}


def save_health_profile(db: Session, user: User, answers: dict[str, str]) -> HealthProfile | None:
    """保存档案：逐题校验后合并写入。

    - 固定题按 questions.py 校验；定制题按当前 custom_questions 中已有的 key 校验。
    - 未出现在请求里的题目保持原值；显式传空串表示清空该题。
    - 未知 key、非文本、超长答案一律 400，不接受前端自行编造的题目。
    - 答案达到 COMPLETION_MIN_ANSWERS 项才记 completed_at，低于则清空（不阻断保存）。
    - 合并后一项不剩时删除整行，页面回到问卷态。
    """
    row = get_health_profile(db, user.id)
    merged: dict[str, str] = dict(row.answers or {}) if row else {}
    store = probe.parse_store(row.custom_questions if row else None)
    custom_answers: dict[str, str] = {}

    for key, raw in answers.items():
        if key in QUESTION_MAP:
            question = QUESTION_MAP[key]
            if not isinstance(raw, str):
                raise AppError(400, f"「{question['label']}」的答案须为文本")
            text = raw.strip()
            if not text:
                merged.pop(key, None)
                continue
            if len(text) > question["max_length"]:
                raise AppError(400, f"「{question['label']}」最多 {question['max_length']} 字")
            merged[key] = text
            continue

        custom_answers[key] = raw

    if custom_answers:
        cleaned = probe.validate_page_answers(store, custom_answers)
        for key, text in cleaned.items():
            if text:
                merged[key] = text
            else:
                merged.pop(key, None)

    if not merged:
        if row is not None:
            db.delete(row)
            db.commit()
        return None

    if row is None:
        row = HealthProfile(user_id=user.id, answers=merged, custom_questions={"sets": []})
        db.add(row)
    else:
        row.answers = merged

    if len(merged) >= COMPLETION_MIN_ANSWERS:
        if row.completed_at is None:
            row.completed_at = datetime.now()
    else:
        row.completed_at = None

    db.commit()
    db.refresh(row)
    return row


def save_probe_health_profile(
    db: Session,
    user_id: int,
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """受控写入“健康档案测试”角色生成的一套问题与答案。

    - 问题 3~10 个，答案至少 1 题，只允许 q1~q10 且不得覆盖固定题。
    - 与最新一套问题相同则更新该套答案；不同则新增一套，保留历史（最多 20 套）。
    - 旧套被挤出时同步删除该套答案；固定题答案始终保留。
    - 返回值供工具原样回给模型。
    """
    normalized = probe.normalize_questions(questions)
    cleaned = probe.validate_probe_answers(normalized, answers)

    row = get_health_profile(db, user_id)
    store = probe.parse_store(row.custom_questions if row else None)
    merged: dict[str, str] = dict(row.answers or {}) if row else {}
    latest = probe.latest_set(store)
    status = "created"

    if latest is not None and probe.signature(latest["questions"]) == probe.signature(normalized):
        set_id = latest["set_id"]
        current_local = probe.latest_answers(store, merged)
        target_local = {**current_local, **cleaned}
        if target_local == current_local:
            return {
                "ok": True,
                "status": "already_exists",
                "set_id": set_id,
                "question_count": len(latest["questions"]),
                "answered_count": len(current_local),
                "filled": True,
                "completed_at": row.completed_at.isoformat() if row and row.completed_at else None,
            }
        for question in latest["questions"]:
            key = question["key"]
            text = target_local.get(question["local_key"])
            if text:
                merged[key] = text
            else:
                merged.pop(key, None)
        status = "updated"
    else:
        store, set_id, dropped = probe.append_set(store, normalized)
        for old_set_id in dropped:
            prefix = probe.answer_prefix(old_set_id)
            merged = {key: value for key, value in merged.items() if not key.startswith(prefix)}
        for question in probe.latest_set(store)["questions"]:
            text = cleaned.get(question["local_key"])
            if text:
                merged[question["key"]] = text

    if row is None:
        row = HealthProfile(user_id=user_id, answers=merged, custom_questions=store)
        db.add(row)
    else:
        row.answers = merged
        row.custom_questions = store

    if len(merged) >= COMPLETION_MIN_ANSWERS:
        if row.completed_at is None:
            row.completed_at = datetime.now()
    else:
        row.completed_at = None

    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "status": status,
        "set_id": set_id,
        "question_count": len(normalized),
        "answered_count": len(cleaned),
        "filled": True,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def get_custom_questions(db: Session, user_id: int) -> dict | None:
    """读取最新一套定制问题（供页面与 API 展示）。"""
    row = get_health_profile(db, user_id)
    return probe.latest_payload(probe.parse_store(row.custom_questions if row else None))


def clear_health_profile(db: Session, user: User) -> None:
    """清空档案：直接删除该行，页面回到问卷态。"""
    row = get_health_profile(db, user.id)
    if row is None:
        return
    db.delete(row)
    db.commit()
