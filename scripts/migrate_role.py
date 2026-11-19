"""users.role 迁移（2026-11-19，幂等）：新增角色列、检查约束、中文 COMMENT 与首个管理员回填。

用法：
    python scripts/migrate_role.py

说明：只新增一列，不改动既有数据，可重复执行。回填仅在库中没有任何管理员时生效
（取启用账号中 id 最小的一条）；`.env` 的 `ADMIN_USERNAMES` 指定账号同样会被提升。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import SessionLocal, engine

DDL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role varchar(8) NOT NULL DEFAULT '普通用户'",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_role') THEN
            ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('管理员', '普通用户'));
        END IF;
    END $$;
    """,
    "COMMENT ON COLUMN users.role IS '角色：管理员 / 普通用户；/system 与 /api/system 仅管理员可访问'",
]

BACKFILL = """
UPDATE users SET role = '管理员'
WHERE id = (SELECT min(id) FROM users WHERE status = '启用')
  AND NOT EXISTS (SELECT 1 FROM users WHERE role = '管理员')
"""


def main() -> None:
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
        conn.execute(text(BACKFILL))

    from app.modules.auth.admin import ensure_admin_accounts
    from app.modules.auth.models import User

    db = SessionLocal()
    try:
        promoted = ensure_admin_accounts(db)
        admins = (
            db.query(User)
            .filter(User.role == "管理员")
            .order_by(User.id.asc())
            .all()
        )
    finally:
        db.close()

    print(f"已提升：{promoted} 个")
    for row in admins:
        print(f"管理员：id={row.id} username={row.username} status={row.status}")


if __name__ == "__main__":
    main()
