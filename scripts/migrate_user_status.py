"""为现有 users 表增加启用状态列。用法：python scripts/migrate_user_status.py"""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS status varchar(8) NOT NULL DEFAULT '启用'"))
        conn.execute(text("UPDATE users SET status = '启用' WHERE status IS NULL"))
        conn.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_status') THEN ALTER TABLE users ADD CONSTRAINT ck_users_status CHECK (status IN ('启用', '停用')); END IF; END $$"))
        conn.execute(text("COMMENT ON COLUMN users.status IS '启用状态：启用 / 停用'"))
    print("users.status 迁移完成")


if __name__ == "__main__":
    main()
