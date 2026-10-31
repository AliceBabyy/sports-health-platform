# -*- coding: utf-8 -*-
"""核对 body 4 表新命名（表/约束/索引）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine

with engine.connect() as c:
    tables = [r[0] for r in c.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_name LIKE 'body_%' ORDER BY table_name"
    ))]
    print("body tables:", tables)
    cons = [r[0] for r in c.execute(text(
        "SELECT conname FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='public' "
        "AND c.contype='u' AND r.relname LIKE 'body_%' ORDER BY conname"
    ))]
    print("unique:", cons)
    idx = [r[0] for r in c.execute(text(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename LIKE 'body_%' ORDER BY indexname"
    ))]
    print("indexes:", idx)
