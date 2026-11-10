# -*- coding: utf-8 -*-
# 2026-11-10 删除训练动作明细的勾选列（幂等，可重复执行）：
# training_records_items.checked 仅用于汇总 completed_count（动作完成数），
# 前端无勾选入口、接口字段与显示已一并移除，故删除该列。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE training_records_items DROP COLUMN IF EXISTS checked")
        cur.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_name='training_records_items' AND column_name='checked'"""
        )
        print("OK: training_records_items.checked 已删除" if cur.fetchone() is None
              else "FAILED: training_records_items.checked 仍存在")
    conn.close()


if __name__ == "__main__":
    run()
