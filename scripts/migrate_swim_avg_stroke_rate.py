# 2026-11 三次迁移（幂等，可重复执行）：
# swim_records：ADD avg_stroke_rate double precision（平均划频，记录态可手填；
# 未填时仍由 total_strokes/duration 派生，见 service.to_dict）。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE swim_records ADD COLUMN IF NOT EXISTS avg_stroke_rate double precision"
        )
        print("完成：swim_records 新增 avg_stroke_rate（可空）。")
    conn.close()


if __name__ == "__main__":
    run()
