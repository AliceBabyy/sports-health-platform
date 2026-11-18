# -*- coding: utf-8 -*-
# 2026-11-17 状态记录表名加 state_ 前缀（幂等，可重复执行）：
# appetite_record → state_appetite_record、myalgia_record → state_myalgia_record、
# inflammation_record → state_inflammation_record、mood_record → state_mood_record。
# 同步重命名主键 / 唯一约束 / 外键 / 索引 / identity 序列，使旧库与 models.py、scripts/schema.sql 命名一致；
# ALTER TABLE ... RENAME 不丢数据、不丢 COMMENT，脚本末尾重新写入 COMMENT 做幂等修复。
# 新库（无旧表）直接执行 scripts/migrate_state_record.py 建新名表即可，本脚本会跳过。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

DSN = "postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform"

COLUMN_COMMENTS = {
    "id": "主键",
    "user_id": "用户 FK，删除账号时级联删除",
    "date": "记录日期（同类一天一行）",
    "star": "星级 0~5，可空；0=最低分，null=未评",
    "remark": "描述",
    "created_at": "创建时间",
    "updated_at": "更新时间（ORM onupdate 自动刷新）",
}

# (旧表名, 新表名, 旧唯一约束, 新唯一约束, 表注释)
TABLES = [
    ("appetite_record", "state_appetite_record", "uq_appetite_user_date", "uq_state_appetite_user_date",
     "食欲状态记录（按天，每类每天一行）"),
    ("myalgia_record", "state_myalgia_record", "uq_myalgia_user_date", "uq_state_myalgia_user_date",
     "肌肉疼痛状态记录（按天，每类每天一行）"),
    ("inflammation_record", "state_inflammation_record", "uq_inflammation_user_date",
     "uq_state_inflammation_user_date", "炎症状态记录（按天，每类每天一行）"),
    ("mood_record", "state_mood_record", "uq_mood_user_date", "uq_state_mood_user_date",
     "情绪状态记录（按天，每类每天一行）"),
]


def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return bool(cur.fetchone()[0])


def _constraint_name(cur, table: str, conname: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = %s AND conrelid = %s::regclass)",
        (conname, f"public.{table}"),
    )
    return bool(cur.fetchone()[0])


def _rename_constraint(cur, table: str, old: str, new: str) -> None:
    if old == new or not _constraint_name(cur, table, old):
        return
    if _constraint_name(cur, table, new):
        print(f"  约束 {new} 已存在，跳过 {old}")
        return
    cur.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
    print(f"  约束 {old} → {new}")


def _rename_index(cur, old: str, new: str) -> None:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{old}",))
    if not cur.fetchone()[0]:
        return
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{new}",))
    if cur.fetchone()[0]:
        print(f"  索引 {new} 已存在，跳过 {old}")
        return
    cur.execute(f'ALTER INDEX public."{old}" RENAME TO "{new}"')
    print(f"  索引 {old} → {new}")


def _rename_sequence(cur, old_table: str, new_table: str) -> None:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{old_table}_id_seq",))
    if not cur.fetchone()[0]:
        return
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{new_table}_id_seq",))
    if cur.fetchone()[0]:
        print(f"  序列 {new_table}_id_seq 已存在，跳过 {old_table}_id_seq")
        return
    cur.execute(f'ALTER SEQUENCE public."{old_table}_id_seq" RENAME TO "{new_table}_id_seq"')
    print(f"  序列 {old_table}_id_seq → {new_table}_id_seq")


def _apply_comments(cur, table: str, table_comment: str) -> None:
    cur.execute(f'COMMENT ON TABLE "{table}" IS %s', (table_comment,))
    for column, comment in COLUMN_COMMENTS.items():
        cur.execute(f'COMMENT ON COLUMN "{table}"."{column}" IS %s', (comment,))


def _migrate_table(cur, old: str, new: str, uq_old: str, uq_new: str, comment: str) -> None:
    print(f"[{old} → {new}]")
    old_exists = _table_exists(cur, old)
    new_exists = _table_exists(cur, new)
    if old_exists and new_exists:
        raise RuntimeError(f"{old} 与 {new} 同时存在，状态不明确，请人工确认后再执行")
    if old_exists:
        cur.execute(f'ALTER TABLE public."{old}" RENAME TO "{new}"')
        print(f"  表 {old} → {new}")
    elif new_exists:
        print(f"  表已是 {new}，跳过改名")
    else:
        print(f"  {old} / {new} 均不存在，跳过（新库请执行 scripts/migrate_state_record.py）")
        return

    # 约束：主键 / 唯一 / 外键（约束挂在表上，顺序执行先表内约束）
    _rename_constraint(cur, new, f"{old}_pkey", f"{new}_pkey")
    _rename_constraint(cur, new, uq_old, uq_new)
    _rename_constraint(cur, new, f"{old}_user_id_fkey", f"{new}_user_id_fkey")

    # 索引：user_id 单列索引与 (user_id, date, id) 联合索引（唯一约束的索引已随约束改名）
    _rename_index(cur, f"ix_{old}_user_id", f"ix_{new}_user_id")
    _rename_index(cur, f"ix_{old}_user_date_id", f"ix_{new}_user_date_id")

    # identity 序列
    _rename_sequence(cur, old, new)

    _apply_comments(cur, new, comment)
    cur.execute(f'SELECT count(*) FROM "{new}"')
    print(f"  数据行数：{cur.fetchone()[0]}")


def run() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        for old, new, uq_old, uq_new, comment in TABLES:
            _migrate_table(cur, old, new, uq_old, uq_new, comment)
    conn.close()
    print("完成：状态记录四表已统一为 state_ 前缀。")


if __name__ == "__main__":
    run()
