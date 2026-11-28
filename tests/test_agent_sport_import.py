"""会话运动记录导入工具单测：三运动落库、字段约束、相对日期与身份隔离。"""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.constants import today_local
from app.modules.agent.tools.catalog import tool_options
from app.modules.agent.tools.sport_import_actions import (
    SportImportItemIn,
    SportImportRecordIn,
    SportImportRecordsIn,
    _clean_record,
    import_records,
)
from app.modules.dance.models import DanceRecord
from app.modules.swim.models import SwimRecord
from app.modules.training import service as training_service
from app.modules.training.models import TrainingRecord
from scripts.seed_agent_personas import TRAINING_COACH_TOOLS

U1, U2 = 1, 2


def _train_item(**kw):
    base = {"exercise_name": "杠铃卧推", "body_part": "胸", "weight_kg": 40,
            "sets": 3, "reps": "10+8+6", "target_weight_kg": 50}
    base.update(kw)
    return SportImportItemIn(**base)


def _payload(sport, records):
    return SportImportRecordsIn(sport=sport, records=records)


def test_training_import_writes_recorded_with_items(db):
    day = (today_local() - timedelta(days=1)).isoformat()
    result = import_records(db, U1, _payload("training", [SportImportRecordIn(
        date=day, start_time="19:00", end_time="20:00", remark="练胸",
        avg_heart_rate=132, calories=320, items=[_train_item()],
    )]))

    assert result["status"] == "imported"
    assert result["imported"] == 1
    assert result["items_imported"] == 1
    row = db.query(TrainingRecord).one()
    assert row.user_id == U1 and row.status == "recorded"
    assert row.date.isoformat() == day
    assert row.duration_s == 3600
    assert row.items[0].exercise_name == "杠铃卧推"
    assert training_service.plan_to_dict(row)["calories"] == 320


def test_swim_import_writes_recorded_and_derives_duration(db):
    day = (today_local() - timedelta(days=2)).isoformat()
    result = import_records(db, U1, _payload("swim", [SportImportRecordIn(
        date=day, distance_m=1500, duration_min=40, main_stroke="自由泳",
        avg_heart_rate=135, total_strokes=600, laps=30, calories=320,
    )]))

    assert result["status"] == "imported"
    row = db.query(SwimRecord).one()
    assert row.status == "recorded"
    assert row.distance_m == 1500
    assert row.duration_s == 2400
    assert row.main_stroke == "freestyle"


def test_dance_import_accepts_duration_min_and_converts_to_seconds(db):
    day = (today_local() - timedelta(days=3)).isoformat()
    result = import_records(db, U1, _payload("dance", [SportImportRecordIn(
        date=day, dance_type="爵士", stars=5, teacher="王老师",
        style="编舞·力量", duration_min=90, calories=350,
    )]))

    assert result["status"] == "imported"
    row = db.query(DanceRecord).one()
    assert row.status == "recorded"
    assert row.dance_type == "爵士"
    assert row.duration_s == 5400


def test_relative_date_and_missing_date_default_to_today(db):
    yesterday = (today_local() - timedelta(days=1)).isoformat()
    result = import_records(db, U1, _payload("swim", [
        SportImportRecordIn(date="昨天", distance_m=1000),
        SportImportRecordIn(distance_m=800),
    ]))

    assert result["imported"] == 2
    dates = [row.date for row in db.query(SwimRecord).order_by(SwimRecord.id).all()]
    assert dates[0].isoformat() == yesterday
    assert dates[1] == today_local()


def test_invalid_batch_writes_nothing(db):
    result = import_records(db, U1, _payload("swim", [
        SportImportRecordIn(date="2026-11-27", distance_m=1000, main_stroke="狗刨"),
    ]))

    assert result["status"] == "invalid"
    assert result["imported"] == 0
    assert result["failed"]
    assert db.query(SwimRecord).count() == 0


def test_empty_records_returns_empty_without_writing(db):
    result = import_records(db, U1, _payload("training", [SportImportRecordIn(
        date="2026-11-27", remark="今天没练",
    )]))

    assert result["status"] == "empty"
    assert result["imported"] == 0
    assert db.query(TrainingRecord).count() == 0


def test_user_isolation(db):
    training = _payload("training", [SportImportRecordIn(
        date="2026-11-27", items=[_train_item()],
    )])
    assert import_records(db, U1, training)["imported"] == 1
    assert import_records(db, U2, training)["imported"] == 1
    assert db.query(TrainingRecord).count() == 2


def test_record_schema_forbids_status_user_id_and_unknown_fields():
    with pytest.raises(ValidationError):
        SportImportRecordIn(date="2026-11-27", status="recorded")
    with pytest.raises(ValidationError):
        SportImportRecordIn(date="2026-11-27", user_id=1)
    with pytest.raises(ValidationError):
        SportImportRecordsIn(sport="training", records=[], user_id=1)


def test_clean_record_drops_other_sport_fields_and_converts_units():
    swim = SportImportRecordIn(
        date="2026-11-27", distance_m=1000, duration_s=1800,
        dance_type="爵士", items=[_train_item()],
    )
    cleaned = _clean_record("swim", swim)
    assert cleaned["duration_min"] == 30
    assert "duration_s" not in cleaned
    assert "dance_type" not in cleaned and "items" not in cleaned

    dance = SportImportRecordIn(date="2026-11-27", duration_min=60, distance_m=1000)
    cleaned = _clean_record("dance", dance)
    assert cleaned["duration_s"] == 3600
    assert "distance_m" not in cleaned


def test_tool_registered_as_write_and_training_coach_granted():
    options = {item["name"]: item for item in tool_options()}
    assert options["import_sport_records"]["kind"] == "write"
    assert options["import_sport_records"]["label"] == "导入运动记录"
    assert "import_sport_records" in TRAINING_COACH_TOOLS
