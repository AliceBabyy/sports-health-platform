# -*- coding: utf-8 -*-
# 2026-11 练后心得迁移（幂等，可重复执行）：
# 1) training_notes 扩三列：best_movement / reflection / next_steps（rating/status_text 已存在）
# 2) 新建 swim_notes（swim_id unique cascade，rating/stroke_insight/other）
# 3) 新建 dance_notes（dance_id unique cascade，rating/video_effect/insight）
# 只做加列/建表，不动历史数据；任何一步已存在均跳过。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute('ALTER TABLE "training_notes" ADD COLUMN IF NOT EXISTS best_movement VARCHAR(128)')
        cur.execute('ALTER TABLE "training_notes" ADD COLUMN IF NOT EXISTS reflection TEXT')
        cur.execute('ALTER TABLE "training_notes" ADD COLUMN IF NOT EXISTS next_steps TEXT')
        cur.execute("""
            CREATE TABLE IF NOT EXISTS "swim_notes" (
                id SERIAL PRIMARY KEY,
                swim_id INTEGER NOT NULL UNIQUE REFERENCES "swim_records"(id) ON DELETE CASCADE,
                rating SMALLINT,
                stroke_insight TEXT,
                other TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS "dance_notes" (
                id SERIAL PRIMARY KEY,
                dance_id INTEGER NOT NULL UNIQUE REFERENCES "dance_records"(id) ON DELETE CASCADE,
                rating SMALLINT,
                video_effect SMALLINT,
                insight TEXT
            )
        """)
    conn.close()
    print("OK: notes 表结构已就绪（幂等，无重复副作用）")


if __name__ == "__main__":
    run()
