# -*- coding: utf-8 -*-
# 2026-11-04 training_plans 时刻/时长整改（幂等，可重复执行）：
# 1) started_at → starttime（DateTime）
# 2) saved_at   → endtime（DateTime）
# 3) 新增 duration_s（训练时长秒，仅记录态）
# 只做改名/加列，不动历史数据；已存在目标列均跳过。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def _col_exists(cur, table: str, col: str) -> bool:
    cur.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_name=%s AND column_name=%s""",
        (table, col),
    )
    return cur.fetchone() is not None


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        # started_at -> starttime（旧列存在且目标不存在才改名）
        if _col_exists(cur, "training_plans", "started_at") and not _col_exists(cur, "training_plans", "starttime"):
            cur.execute('ALTER TABLE "training_plans" RENAME COLUMN started_at TO starttime')
            print("renamed started_at -> starttime")
        # saved_at -> endtime
        if _col_exists(cur, "training_plans", "saved_at") and not _col_exists(cur, "training_plans", "endtime"):
            cur.execute('ALTER TABLE "training_plans" RENAME COLUMN saved_at TO endtime')
            print("renamed saved_at -> endtime")
        # duration_s
        cur.execute('ALTER TABLE "training_plans" ADD COLUMN IF NOT EXISTS duration_s INTEGER')
        print("OK: training_plans.starttime/endtime/duration_s 已就绪")
    conn.close()


if __name__ == "__main__":
    run()
