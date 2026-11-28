"""健康档案专项 skill 的运行时：加载专项提示词，并把已有专项问答拼成上下文。

代码技能本身不写库、不生成题目；它返回的 summary 是模型本轮必须遵循的专项提示词。
保存仍由受控工具 save_health_profile_aspect 完成，边界在工具/service 中强制。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.prompts.loader import load_system_prompt
from app.core.access import is_female
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.aspect_skills import PROFILE_SKILL_MAP
from app.modules.profile.aspects import aspect_label
from app.modules.profile.questionnaire import set_qa


def _existing_block(question_set: dict | None) -> str:
    if question_set is None:
        return "尚无已保存的专项问答，这是第一次为该专项建档。"
    qa = set_qa(question_set)
    lines = [
        f"- {item['label']}（{item['group']}）：{item['answer'] or '（未答）'}"
        for item in qa
    ]
    return "最近一套专项问答：\n" + "\n".join(lines)


def run_profile_aspect(
    db: Session,
    user_id: int,
    skill_key: str,
    mode: str = "补齐",
) -> dict:
    skill = PROFILE_SKILL_MAP.get(skill_key)
    if skill is None:
        raise ValueError("未知的档案专项")
    if skill.get("female_only"):
        user = db.get(User, user_id)
        if user is None or not is_female(user.gender):
            raise AppError(403, "生理期档案仅适用于女性用户")
    prompt = load_system_prompt(skill["prompt_id"])
    view = service.get_health_profile(db, user_id)
    latest = view.latest_for(skill_key) if view else None
    aspects = "、".join(
        f"{key}（{aspect_label(key)}）" for key in skill["aspects"]
    )
    mode_text = (
        "补齐：只问尚未回答或答案明显不足的题，已有答案不要原样重问。"
        if mode == "补齐" else
        "更新：逐题复核已有答案；已足够的不重问，只问需要修正、过期或新增的题。"
    )
    context = (
        f"\n\n【本轮专项运行上下文】\n"
        f"- 专项：{skill['name']}（{skill_key}），斜杠命令：/{skill['slash_alias']}\n"
        f"- 允许的 aspect：{aspects}\n"
        f"- 模式：{mode}。{mode_text}\n"
        f"- 已有专项问答：\n{_existing_block(latest)}\n"
        f"- 本轮只处理这个专项，不要混入其他专项；生成 3~10 题（健身档案 6~10 题），全部题目的 aspect 必须在上面的允许列表内。\n"
        f"- 逐题使用 ask_user 采集答案；用户确认后再调用 save_health_profile_aspect，"
        f"skill_key 固定为 {skill_key}。"
    )
    return {
        "status": "ok",
        "range": None,
        "sample_size": 0,
        "outputs": [],
        "facts": {
            "skill_key": skill_key,
            "mode": mode,
            "prompt_id": skill["prompt_id"],
            "allowed_aspects": list(skill["aspects"]),
            "existing_questions": len(latest["questions"]) if latest else 0,
            "existing_answers": sum(1 for q in latest["questions"] if q["answer"]) if latest else 0,
        },
        "summary": prompt + context,
        "caveats": [],
    }
