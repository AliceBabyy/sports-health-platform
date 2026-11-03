# 2026-11 二次迁移（幂等，可重复执行）：
# 1) swim_records / dance_records：DROP plan_text（先将其内容保全到新列 remark），ADD remark varchar(255)
# 2) training_plans：ADD remark varchar(255)
# 依据用户口径：游泳/舞蹈计划态弃用笼统字符串，改为结构化字段（距离/时长/主泳姿/备注、舞种/星级/备注）。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        for t in ("swim_records", "dance_records"):
            cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS remark varchar(255)")
            # 数据保全：旧计划文本迁入备注，避免删列丢内容
            cur.execute(
                f"UPDATE {t} SET remark = plan_text WHERE status = 'planned' AND plan_text IS NOT NULL AND remark IS NULL"
            )
            cur.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS plan_text")
        cur.execute("ALTER TABLE training_plans ADD COLUMN IF NOT EXISTS remark varchar(255)")
        print("完成：swim/dance 移除 plan_text（内容已保全至 remark）+ 三表新增 remark。")
    conn.close()


if __name__ == "__main__":
    run()
