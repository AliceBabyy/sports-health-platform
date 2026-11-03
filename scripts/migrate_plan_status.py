"""游泳/舞蹈 计划态迁移（swim/dance 支持「计划、记录」统一状态）：
1. swim_records / dance_records 各加 status（planned|recorded，默认 recorded）+ plan_text（可空）；
2. 记录必填列转可空（计划态无需填写）：
   - swim_records: distance_m / duration_s
   - dance_records: dance_type / stars / duration_s
3. 补 (user_id, record_date) 联合索引（总览按日/周/月窗口聚合查询提速）。

幂等：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / DROP NOT NULL，可重复执行。
用法：python scripts/migrate_plan_status.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        for t in ("swim_records", "dance_records"):
            conn.execute(
                text(
                    f"ALTER TABLE {t} "
                    "ADD COLUMN IF NOT EXISTS status varchar(16) NOT NULL DEFAULT 'recorded'"
                )
            )
            conn.execute(
                text(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS plan_text varchar(255)")
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{t}_user_date "
                    f"ON {t} (user_id, record_date)"
                )
            )
        conn.execute(text("ALTER TABLE swim_records ALTER COLUMN distance_m DROP NOT NULL"))
        conn.execute(text("ALTER TABLE swim_records ALTER COLUMN duration_s DROP NOT NULL"))
        conn.execute(text("ALTER TABLE dance_records ALTER COLUMN dance_type DROP NOT NULL"))
        conn.execute(text("ALTER TABLE dance_records ALTER COLUMN stars DROP NOT NULL"))
        conn.execute(text("ALTER TABLE dance_records ALTER COLUMN duration_s DROP NOT NULL"))
    print("完成：swim/dance 已支持计划态（status + plan_text），记录必填列已转可空，并补齐按日联合索引。")


if __name__ == "__main__":
    main()
