# -*- coding: utf-8 -*-
# 2026-11 生理周期表重构（幂等，可重复执行）：
# 1. cycle_settings -> period_setting
# 2. daily_pain_logs -> period_logs：
#    - pain_level 改为可空（去默认值 0）
#    - 新增 note varchar(255) NULL（当日 note）
#    - 新增 period_id integer NULL（FK period_records.id，ON DELETE SET NULL）
#    - 唯一约束改为 uq_period_log_user_date，索引/主键名同步
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"


def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cur.fetchone()[0] is not None


def _sequence_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
    return cur.fetchone()[0] is not None


def _constraint_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM pg_constraint
        WHERE conname = %s AND conrelid = %s::regclass
        """,
        (name, f"public.{table}"),
    )
    return cur.fetchone() is not None


def _index_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s", (name,))
    return cur.fetchone() is not None


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        # ---------- 表改名 ----------
        if _table_exists(cur, "cycle_settings") and not _table_exists(cur, "period_setting"):
            cur.execute("ALTER TABLE cycle_settings RENAME TO period_setting")
            print("完成：cycle_settings → period_setting")
        if _table_exists(cur, "daily_pain_logs") and not _table_exists(cur, "period_logs"):
            cur.execute("ALTER TABLE daily_pain_logs RENAME TO period_logs")
            print("完成：daily_pain_logs → period_logs")

        # ---------- 约束 / 索引 / 序列改名 ----------
        if _table_exists(cur, "period_setting"):
            if _constraint_exists(cur, "period_setting", "cycle_settings_user_id_fkey"):
                cur.execute(
                    "ALTER TABLE period_setting RENAME CONSTRAINT cycle_settings_user_id_fkey TO period_setting_user_id_fkey"
                )
            if _constraint_exists(cur, "period_setting", "cycle_settings_pkey"):
                cur.execute("ALTER TABLE period_setting RENAME CONSTRAINT cycle_settings_pkey TO period_setting_pkey")

        if _table_exists(cur, "period_logs"):
            if _constraint_exists(cur, "period_logs", "daily_pain_logs_pkey"):
                cur.execute("ALTER TABLE period_logs RENAME CONSTRAINT daily_pain_logs_pkey TO period_logs_pkey")
            if _constraint_exists(cur, "period_logs", "uq_pain_user_date"):
                cur.execute("ALTER TABLE period_logs RENAME CONSTRAINT uq_pain_user_date TO uq_period_log_user_date")
            if _index_exists(cur, "ix_daily_pain_logs_user_id"):
                cur.execute("ALTER INDEX ix_daily_pain_logs_user_id RENAME TO ix_period_logs_user_id")
            if _sequence_exists(cur, "daily_pain_logs_id_seq") and not _sequence_exists(cur, "period_logs_id_seq"):
                cur.execute("ALTER SEQUENCE daily_pain_logs_id_seq RENAME TO period_logs_id_seq")

            # ---------- 字段调整 ----------
            cur.execute("ALTER TABLE period_logs ALTER COLUMN pain_level DROP NOT NULL")
            cur.execute("ALTER TABLE period_logs ALTER COLUMN pain_level DROP DEFAULT")
            if not _column_exists(cur, "period_logs", "note"):
                cur.execute("ALTER TABLE period_logs ADD COLUMN note varchar(255) NULL")
                print("完成：period_logs.note 已新增")
            if not _column_exists(cur, "period_logs", "period_id"):
                cur.execute("ALTER TABLE period_logs ADD COLUMN period_id integer NULL")
                print("完成：period_logs.period_id 已新增")

            if _constraint_exists(cur, "period_logs", "fk_period_logs_period_id"):
                cur.execute(
                    "ALTER TABLE period_logs RENAME CONSTRAINT fk_period_logs_period_id TO period_logs_period_id_fkey"
                )
            if not _constraint_exists(cur, "period_logs", "period_logs_period_id_fkey"):
                cur.execute(
                    """
                    ALTER TABLE period_logs
                    ADD CONSTRAINT period_logs_period_id_fkey
                    FOREIGN KEY (period_id) REFERENCES period_records (id) ON DELETE SET NULL
                    """
                )
            if not _index_exists(cur, "ix_period_logs_period_id"):
                cur.execute("CREATE INDEX ix_period_logs_period_id ON period_logs (period_id)")

            # ---------- 注释 ----------
            cur.execute("COMMENT ON TABLE period_logs IS %s", ("生理周期每日日志（疼痛 / note，一天一行）",))
            cur.execute("COMMENT ON COLUMN period_logs.id IS %s", ("主键",))
            cur.execute("COMMENT ON COLUMN period_logs.user_id IS %s", ("用户（逻辑外键，归属校验在应用层）",))
            cur.execute("COMMENT ON COLUMN period_logs.log_date IS %s", ("记录日期（一天一行）",))
            cur.execute(
                "COMMENT ON COLUMN period_logs.pain_level IS %s",
                ("疼痛等级 0无/1轻/2中/3重；仅经期可填，非经期为 NULL",),
            )
            cur.execute("COMMENT ON COLUMN period_logs.note IS %s", ("当日 note（可空）",))
            cur.execute("COMMENT ON COLUMN period_logs.period_id IS %s", ("归属月经记录 id；非经期为 NULL",))
            cur.execute("COMMENT ON COLUMN period_logs.created_at IS %s", ("创建时间",))

        if _table_exists(cur, "period_setting"):
            cur.execute("COMMENT ON TABLE period_setting IS %s", ("生理周期参考值（单用户单行）",))
            cur.execute("COMMENT ON COLUMN period_setting.user_id IS %s", ("主键 + FK → users.id",))
            cur.execute(
                "COMMENT ON COLUMN period_setting.cycle_length IS %s",
                ("参考周期（天）：用于当前段、预测段与补推段",),
            )
            cur.execute(
                "COMMENT ON COLUMN period_setting.period_length IS %s",
                ("参考经期天数：用于当前段、预测段、补推段及未填结束日的记录",),
            )
            cur.execute(
                "COMMENT ON COLUMN period_setting.updated_at IS %s",
                ("更新时间（ORM onupdate 自动刷新）",),
            )

    conn.close()
    print("完成：生理周期表重构迁移已结束。")


if __name__ == "__main__":
    run()
