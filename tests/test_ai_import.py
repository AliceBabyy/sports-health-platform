"""AI 导入单测（2026-11-10 新增）：输出清洗、契约校验、落库与接口错误映射。"""
import io
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.runtime.invoke import AIServiceError
from app.core.constants import TR_STATUS_RECORDED
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.dance import ai_profile as dance_ai
from app.modules.electronic_trainer import ai_import
from app.modules.swim import ai_profile as swim_ai
from app.modules.training import ai_profile as training_ai
from app.modules.training import service as training_service
from config import settings
from database import get_db
from main import app

USER = 1
TODAY = date(2026, 11, 10)


@pytest.fixture()
def client(db):
    user = User(id=USER, username="aiimport", password_hash="unused", display_name="AI")
    db.add(user)
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_training_normalize_cleans_noise_and_persists(db):
    raw = {"plans": [{
        "date": "昨天", "start_time": "19:00", "end_time": "20:00",
        "remark": " 练胸 ", "avg_heart_rate": "132", "max_heart_rate": 168,
        "calories": "320 kcal",
        "items": [
            {"exercise_name": " 杠铃卧推 ", "body_part": "胸", "weight_kg": "40kg",
             "sets": "3组", "reps": 10, "target_weight_kg": None},
            {"exercise_name": "", "sets": 2},
        ],
    }], "warnings": ["日期可能笔误"]}

    payload, warnings = training_ai.normalize(raw, TODAY)
    plan = payload["plans"][0]
    assert plan["date"] == "2026-11-09"
    assert plan["start_time"] == "2026-11-09T19:00:00"
    assert plan["end_time"] == "2026-11-09T20:00:00"
    assert plan["remark"] == "练胸"
    assert plan["calories"] == 320.0 and plan["avg_heart_rate"] == 132
    item = plan["items"][0]
    assert item["weight_kg"] == 40.0 and item["sets"] == 3 and item["reps"] == "10"
    assert "日期可能笔误" in warnings

    valid, errors = training_ai.PROFILE.validate(payload["plans"])
    assert not errors and len(valid) == 1
    ids, extra = training_ai.PROFILE.persist(db, USER, valid)
    assert len(ids) == 1 and extra["items_imported"] == 1
    record = training_service.get_plan(db, USER, ids[0])
    assert record.status == TR_STATUS_RECORDED
    assert record.end_time == datetime(2026, 11, 9, 20, 0) and record.duration_s == 3600
    assert [i.exercise_name for i in record.items] == ["杠铃卧推"]


def test_training_normalize_drops_single_sided_time_and_empty_items():
    raw = {"plans": [
        {"date": "2026-11-09", "start_time": "19:00", "end_time": None,
         "items": [{"exercise_name": "深蹲"}]},
        {"date": "2026-11-09", "items": []},
    ]}
    payload, warnings = training_ai.normalize(raw, TODAY)
    assert len(payload["plans"]) == 1
    assert payload["plans"][0]["start_time"] is None
    assert payload["plans"][0]["end_time"] is None
    assert any("没有可用的动作" in w for w in warnings)


def test_swim_normalize_requires_distance_and_normalizes_stroke():
    raw = {"records": [
        {"date": "2026-11-08", "start_time": "19:00", "end_time": "19:40",
         "distance_m": "1,500 米", "duration_min": "40", "main_stroke": "自由泳"},
        {"date": "2026-11-08", "distance_m": None},
    ]}
    payload, warnings = swim_ai.normalize(raw, TODAY)
    assert len(payload["records"]) == 1
    record = payload["records"][0]
    assert record["distance_m"] == 1500
    assert record["start_time"] == "2026-11-08T19:00:00"
    assert any("没有距离" in w for w in warnings)

    valid, errors = swim_ai.PROFILE.validate(payload["records"])
    assert not errors and len(valid) == 1
    assert valid[0]["main_stroke"] == "freestyle"
    assert valid[0]["duration_s"] == 2400


def test_dance_normalize_clamps_stars_and_skips_empty_records():
    raw = {"records": [
        {"date": "2026-11-09", "dance_type": "爵士", "stars": 9, "duration_s": 5400},
        {"date": "2026-11-09", "stars": 3},
    ]}
    payload, warnings = dance_ai.normalize(raw, TODAY)
    assert len(payload["records"]) == 1
    assert payload["records"][0]["stars"] == 5
    assert any("既没有舞种也没有时长" in w for w in warnings)


def test_encode_images_rejects_unknown_type_and_too_many():
    with pytest.raises(AppError):
        ai_import.encode_images([SimpleNamespace(file=io.BytesIO(b"plain text"))])
    many = [SimpleNamespace(file=io.BytesIO(b"\xff\xd8\xffjpg"))
            for _ in range(settings.ai_import_max_images + 1)]
    with pytest.raises(AppError):
        ai_import.encode_images(many)


def test_training_ai_import_endpoint_writes_recorded(client, db, monkeypatch):
    monkeypatch.setattr(ai_import, "invoke_ai_import", lambda **kwargs: {
        "plans": [{"date": "2026-11-09", "remark": "AI 练胸",
                   "items": [{"exercise_name": "杠铃卧推", "weight_kg": 40,
                              "sets": 3, "reps": "10"}]}],
        "warnings": [],
    })
    response = client.post("/api/training/ai-import", data={"prompt": "昨天练胸"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1 and body["items_imported"] == 1
    assert body["training_ids"] == body["created_ids"]
    assert body["payload"]["plans"][0]["date"] == "2026-11-09"
    assert body["ai"]["model"] == settings.ai_import_model
    assert body["failed"] == []

    daily = client.get("/api/training/daily", params={"date": "2026-11-09"}).json()
    assert daily["list"][0]["status"] == TR_STATUS_RECORDED
    assert daily["list"][0]["remark"] == "AI 练胸"
    record = training_service.get_plan(db, USER, body["created_ids"][0])
    # 没给结束时间不补当前时刻，详情里时段显示「—」（2026-11-10）
    assert record.start_time is None and record.end_time is None and record.duration_s is None


def test_ai_import_requires_text_or_image(client):
    response = client.post("/api/training/ai-import", data={"prompt": "   "})
    assert response.status_code == 400


def test_ai_import_maps_provider_failure_to_502(client, monkeypatch):
    def boom(**kwargs):
        raise AIServiceError("模型服务暂不可用")

    monkeypatch.setattr(ai_import, "invoke_ai_import", boom)
    response = client.post("/api/swim-records/ai-import", data={"prompt": "游了 1000 米"})
    assert response.status_code == 502


def test_ai_import_empty_result_does_not_write(client, monkeypatch):
    monkeypatch.setattr(ai_import, "invoke_ai_import",
                        lambda **kwargs: {"records": [], "warnings": ["图片看不清"]})
    response = client.post("/api/dance-records/ai-import", data={"prompt": "昨天上了节课"})
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 0 and body["created_ids"] == []
    assert body["message"] == "没有识别到可导入的记录"
    assert body["ai"]["warnings"] == ["图片看不清"]
