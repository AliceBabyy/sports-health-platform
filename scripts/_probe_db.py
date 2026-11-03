# -*- coding: utf-8 -*-
"""临时探活：检查 PostgreSQL 连接与表清单。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2

conn = psycopg2.connect("postgresql://postgres:123456@127.0.0.1:5432/sports-health-platform")
cur = conn.cursor()
cur.execute("select version()")
print("PG:", cur.fetchone()[0][:60])
cur.execute("select tablename from pg_tables where schemaname='public' order by 1")
for row in cur.fetchall():
    print("TABLE:", row[0])
for t in ("swim_records", "dance_records"):
    cur.execute('select column_name, data_type, is_nullable, column_default from information_schema.columns where table_name=%s order by ordinal_position', (t,))
    print("---", t)
    for r in cur.fetchall():
        print("  ", r)
conn.close()
