"""训练模块整改迁移（一日多计划）：
1. 删除 training_plans 的 (user_id, plan_date) 唯一约束 uq_training_plan_user_date；
2. 新建联合索引 ix_training_plans_user_date (user_id, plan_date)（加速按日列表查询）。

幂等：约束不存在则跳过、索引已存在则跳过，可重复执行。
用法：python scripts/migrate_training_multi_plan.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE training_plans "
                "DROP CONSTRAINT IF EXISTS uq_training_plan_user_date"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_training_plans_user_date "
                "ON training_plans (user_id, plan_date)"
            )
        )
    print("完成：已移除一日一计划唯一约束，并建立 (user_id, plan_date) 联合索引。")


if __name__ == "__main__":
    main()
