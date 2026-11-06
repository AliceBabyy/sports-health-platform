"""Cross-module storage and API contract checks."""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.modules.auth.models import User
from database import get_db
from main import app


@pytest.fixture()
def client(db):
    user = User(id=7, username="contract", password_hash="unused", display_name="Contract")
    db.add(user)
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("prefix,payload", [
    ("/api/training", {"date": "2026-11-06", "status": "planned", "items": [{"exercise_name": "深蹲"}]}),
    ("/api/swim-records", {"date": "2026-11-06", "status": "planned", "distance_m": 500}),
    ("/api/dance-records", {"date": "2026-11-06", "status": "planned", "dance_type": "爵士", "stars": 4}),
])
def test_required_api_and_state_contract(client, prefix, payload):
    created = client.post(prefix, json=payload)
    assert created.status_code == 200, created.text
    record_id = created.json()["id"]
    assert created.json()["date"] == payload["date"]

    daily = client.get(prefix + "/daily", params={"date": payload["date"]})
    assert daily.status_code == 200 and daily.json()["list"][0]["id"] == record_id
    listing = client.get(prefix, params={"page": 1, "page_size": 10})
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert listing.json()["list"][0]["status"] == "planned"
    updated = client.put(prefix + f"/{record_id}", json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == record_id
    assert client.get(prefix + "/stats").status_code == 200
    assert client.get(prefix + "/template").status_code == 200

    note = client.put(prefix + f"/{record_id}/note", json={"rating": 4, "notes": "练后感受"})
    assert note.status_code == 400 and note.json()["code"] == "BAD_REQUEST"
    deleted = client.post(prefix + "/batch-delete", json={"ids": [record_id, 999999]}).json()
    assert deleted == {"deleted": [record_id], "skipped": [999999]}
    assert client.get(prefix).json()["total"] == 0


def test_sport_tables_have_common_columns(db):
    from sqlalchemy import inspect

    inspector = inspect(db.bind)
    required = {"id", "user_id", "date", "status", "start_time", "end_time", "duration_s",
                "created_at", "updated_at", "remark", "avg_heart_rate", "max_heart_rate", "calories"}
    for table in ("training_records", "swim_records", "dance_records"):
        assert required <= {col["name"] for col in inspector.get_columns(table)}
        fk = inspector.get_foreign_keys(table)
        assert any(item["referred_table"] == "users" for item in fk)
    for table in ("training_notes", "swim_notes", "dance_notes"):
        assert {"id", "rating", "notes"} <= {col["name"] for col in inspector.get_columns(table)}
