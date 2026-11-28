"""重置 health_profile 为“专项 skill 一套题”结构（数据清空后执行）。

用法：
    python scripts/migrate_health_profile_aspects.py

安全边界：
- 只允许在 health_profile 无数据时执行；有数据会中止，避免误删。
- 删除旧表后按 app/modules/profile/models.py 重建，并补齐 COMMENT 注释。
- 不迁移旧固定题 / probe 数据；旧结构已由用户确认清空。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.modules.profile.aspects import ASPECT_KEYS
from database import engine

ASPECT_SQL = ", ".join(f"'{key}'" for key in sorted(ASPECT_KEYS))

CREATE_SQL = f"""
CREATE TABLE health_profile (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    set_id VARCHAR(16) NOT NULL,
    skill_key VARCHAR(48) NOT NULL,
    aspect VARCHAR(32) NOT NULL,
    local_key VARCHAR(8) NOT NULL,
    label VARCHAR(120) NOT NULL DEFAULT '',
    hint VARCHAR(120) NOT NULL DEFAULT '',
    placeholder VARCHAR(120) NOT NULL DEFAULT '',
    max_length INTEGER NOT NULL DEFAULT 200,
    answer TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    set_generated_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_health_profile_user_set_local UNIQUE (user_id, set_id, local_key),
    CONSTRAINT ck_health_profile_aspect CHECK (aspect IN ({ASPECT_SQL})),
    CONSTRAINT ck_health_profile_max_length CHECK (max_length BETWEEN 50 AND 255)
);
CREATE INDEX idx_health_profile_user_skill
    ON health_profile (user_id, skill_key, set_generated_at);
COMMENT ON TABLE health_profile IS '健康档案（按专项 skill 分套，一行一道题的开放式答案）';
COMMENT ON COLUMN health_profile.id IS '主键';
COMMENT ON COLUMN health_profile.user_id IS '用户主键 + FK，删除账号时级联删除';
COMMENT ON COLUMN health_profile.set_id IS '一套专项问题的 id；同一用户内唯一标识一套';
COMMENT ON COLUMN health_profile.skill_key IS '生成这套题的档案专项 skill key，见 app/modules/profile/aspect_skills.py';
COMMENT ON COLUMN health_profile.aspect IS '档案方面，必须是该 skill 允许的 aspect';
COMMENT ON COLUMN health_profile.local_key IS '套内题号 q1、q2...；页面题数不设上限';
COMMENT ON COLUMN health_profile.label IS '题目标题';
COMMENT ON COLUMN health_profile.hint IS '填写提示';
COMMENT ON COLUMN health_profile.placeholder IS '占位文案';
COMMENT ON COLUMN health_profile.max_length IS '答案最大字数（50~255）';
COMMENT ON COLUMN health_profile.answer IS '用户文本答案；为空表示题目已生成但未回答';
COMMENT ON COLUMN health_profile.sort_order IS '同一套内的展示顺序';
COMMENT ON COLUMN health_profile.set_generated_at IS '这套问题的生成时间';
COMMENT ON COLUMN health_profile.created_at IS '创建时间';
COMMENT ON COLUMN health_profile.updated_at IS '更新时间（ORM onupdate 自动刷新）';
"""


def main() -> None:
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM health_profile")).scalar_one()
        if count:
            raise SystemExit(f"health_profile 仍有 {count} 行数据，已中止；请先备份或清空后再执行")
        conn.execute(text("DROP TABLE health_profile"))
        conn.execute(text(CREATE_SQL))
    print("health_profile 已重建为专项问答结构")


if __name__ == "__main__":
    main()
