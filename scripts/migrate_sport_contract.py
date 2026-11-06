"""Migrate the three sport modules to the shared storage contract.

Run once with the configured DATABASE_URL. All DDL runs in one transaction.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402
from database import engine  # noqa: E402


def run() -> None:
    with engine.begin() as conn:
        inspector = inspect(conn)
        if inspector.has_table("training_plans") and not inspector.has_table("training_records"):
            conn.exec_driver_sql("ALTER TABLE training_plans RENAME TO training_records")
        if inspector.has_table("training_plan_items") and not inspector.has_table("training_records_items"):
            conn.exec_driver_sql("ALTER TABLE training_plan_items RENAME TO training_records_items")

        renames = {
            "training_records": {"plan_date": "date", "starttime": "start_time", "endtime": "end_time"},
            "training_records_items": {"plan_id": "training_id"},
            "training_notes": {"plan_id": "training_id", "reflection": "notes"},
            "swim_records": {"record_date": "date"},
            "swim_notes": {"other": "notes"},
            "dance_records": {"record_date": "date"},
            "dance_notes": {"insight": "notes"},
        }
        for table, columns in renames.items():
            existing = {col["name"] for col in inspect(conn).get_columns(table)}
            for old, new in columns.items():
                if old in existing and new not in existing:
                    conn.exec_driver_sql(f'ALTER TABLE {table} RENAME COLUMN {old} TO "{new}"')

        additions = {
            "training_records": {
                "avg_heart_rate": "integer", "max_heart_rate": "integer", "calories": "numeric(8,2)"
            },
            "swim_records": {"start_time": "timestamp", "end_time": "timestamp", "max_heart_rate": "integer"},
        }
        for table, columns in additions.items():
            for name, sql_type in columns.items():
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {sql_type}")

        for table in ("training_records", "swim_records", "dance_records"):
            orphan_count = conn.execute(text(
                f"SELECT count(*) FROM {table} r LEFT JOIN users u ON u.id = r.user_id WHERE u.id IS NULL"
            )).scalar_one()
            if orphan_count:
                raise RuntimeError(f"{table} has {orphan_count} rows without a user")
            constraints = {item["name"] for item in inspect(conn).get_foreign_keys(table)}
            fk_name = f"fk_{table}_user_id"
            if fk_name not in constraints:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
                    "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
                )
            check_name = f"ck_{table}_status"
            exists = conn.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(:table) AND conname = :name"
            ), {"table": table, "name": check_name}).scalar()
            if not exists:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD CONSTRAINT {check_name} "
                    "CHECK (status IN ('planned', 'recorded'))"
                )
            conn.exec_driver_sql(
                f'CREATE INDEX IF NOT EXISTS ix_{table}_user_date_id ON {table} (user_id, "date", id)'
            )
    print("Sport contract migration complete")


if __name__ == "__main__":
    run()
