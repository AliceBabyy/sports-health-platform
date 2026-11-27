"""给现有 health_profile 的 aspect CHECK 增加 sport（运动项目），保留数据。

用法：
    python scripts/migrate_health_profile_sport.py

只在已有表上升级约束；新建库直接执行 scripts/schema.sql 即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.modules.profile.aspects import ASPECT_KEYS
from database import engine

ASPECT_SQL = ", ".join(f"'{key}'" for key in sorted(ASPECT_KEYS))
CHECK = f"aspect IN ({ASPECT_SQL})"


def main() -> None:
    with engine.begin() as conn:
        table = conn.execute(text("SELECT to_regclass('health_profile')")).scalar()
        if not table:
            print("health_profile 不存在，跳过；新建库请执行 scripts/schema.sql")
            return
        conn.execute(text(
            "ALTER TABLE health_profile DROP CONSTRAINT IF EXISTS ck_health_profile_aspect"
        ))
        conn.execute(text(
            f"ALTER TABLE health_profile ADD CONSTRAINT ck_health_profile_aspect CHECK ({CHECK})"
        ))
    print("health_profile.aspect CHECK 已包含 sport")


if __name__ == "__main__":
    main()
