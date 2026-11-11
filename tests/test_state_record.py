"""状态记录单测：三表 CRUD、跨表合并分页、当日聚合、跨表批量删除、月历阶段归并与有记录标记。"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.modules.state_record import service
from app.modules.state_record.schemas import StateRecordIn

U1 = 1


def _payload(day: str, type_key: str, star=None, remark=None) -> StateRecordIn:
    return StateRecordIn(date=date.fromisoformat(day), type=type_key, star=star, remark=remark)


def test_create_and_get_by_date(db):
    service.create_record(db, U1, _payload("2026-11-10", "appetite", 4, "胃口正常"))
    service.create_record(db, U1, _payload("2026-11-10", "myalgia", 2, "大腿酸胀"))
    service.create_record(db, U1, _payload("2026-11-10", "inflammation", None, None))

    day = service.get_by_date(db, U1, date(2026, 11, 10))
    assert day["appetite"]["star"] == 4
    assert day["appetite"]["type_label"] == "食欲"
    assert day["myalgia"]["remark"] == "大腿酸胀"
    assert day["inflammation"]["star"] is None  # 未评星可空
    assert day["inflammation"]["remark"] is None

    empty = service.get_by_date(db, U1, date(2026, 11, 11))
    assert empty == {"appetite": None, "myalgia": None, "inflammation": None}


def test_same_type_same_day_unique(db):
    service.create_record(db, U1, _payload("2026-11-10", "appetite", 3, "第一次"))
    with pytest.raises(AppError) as exc:
        service.create_record(db, U1, _payload("2026-11-10", "appetite", 5, "重复"))
    assert exc.value.status == 409
    # 不同类型同日不冲突
    service.create_record(db, U1, _payload("2026-11-10", "myalgia", 1, "疼痛"))


def test_list_merges_three_tables_and_sorts(db):
    service.create_record(db, U1, _payload("2026-11-08", "appetite", 3))
    service.create_record(db, U1, _payload("2026-11-10", "myalgia", 2))
    service.create_record(db, U1, _payload("2026-11-09", "inflammation", 4))

    res = service.list_records(db, U1)
    assert res["total"] == 3
    assert [r["date"] for r in res["list"]] == ["2026-11-10", "2026-11-09", "2026-11-08"]
    assert [r["type"] for r in res["list"]] == ["myalgia", "inflammation", "appetite"]

    filtered = service.list_records(db, U1, type_filter="appetite")
    assert filtered["total"] == 1
    assert filtered["list"][0]["type"] == "appetite"

    with pytest.raises(AppError) as exc:
        service.list_records(db, U1, type_filter="unknown")
    assert exc.value.status == 400


def test_list_pagination(db):
    for i in range(12):
        service.create_record(db, U1, _payload(f"2026-11-{i + 1:02d}", "appetite", i % 5 + 1))
    first = service.list_records(db, U1, page=1, page_size=10)
    second = service.list_records(db, U1, page=2, page_size=10)
    assert first["total"] == 12 and first["pages"] == 2
    assert len(first["list"]) == 10 and len(second["list"]) == 2
    # 日期倒序：第二页内 11-02 在前、11-01 最早
    assert [r["date"] for r in second["list"]] == ["2026-11-02", "2026-11-01"]


def test_update_record(db):
    row = service.create_record(db, U1, _payload("2026-11-10", "appetite", 2, "旧描述"))
    updated = service.update_record(db, U1, row["id"], _payload("2026-11-10", "appetite", 5, "新描述"))
    assert updated["star"] == 5
    assert updated["remark"] == "新描述"

    # 类型定位错误（另一张表无此 id）→ None
    missing = service.update_record(db, U1, row["id"], _payload("2026-11-10", "myalgia", 3))
    assert missing is None


def test_delete_record(db):
    row = service.create_record(db, U1, _payload("2026-11-10", "appetite", 3))
    assert service.delete_record(db, U1, "appetite", row["id"]) is True
    assert service.delete_record(db, U1, "appetite", row["id"]) is False


def test_batch_delete_cross_tables(db):
    a = service.create_record(db, U1, _payload("2026-11-10", "appetite", 3))
    m = service.create_record(db, U1, _payload("2026-11-10", "myalgia", 2))
    i = service.create_record(db, U1, _payload("2026-11-10", "inflammation", 1))

    result = service.batch_delete(db, U1, [
        {"id": a["id"], "type": "appetite"},
        {"id": m["id"], "type": "myalgia"},
        {"id": 9999, "type": "inflammation"},  # 不存在 → skipped
    ])
    deleted = {(x["id"], x["type"]) for x in result["deleted"]}
    assert deleted == {(a["id"], "appetite"), (m["id"], "myalgia")}
    assert result["skipped"] == [{"id": 9999, "type": "inflammation"}]

    remaining = service.get_by_date(db, U1, date(2026, 11, 10))
    assert remaining["appetite"] is None
    assert remaining["myalgia"] is None
    assert remaining["inflammation"]["id"] == i["id"]


def test_phase_group_map_covers_seven_phases():
    assert service.PHASE_GROUP_MAP["menstrual"] == "menses"
    assert service.PHASE_GROUP_MAP["follicular_pre"] == "foll"
    assert service.PHASE_GROUP_MAP["ovulation_day"] == "foll"
    assert service.PHASE_GROUP_MAP["follicular_post"] == "foll"
    assert service.PHASE_GROUP_MAP["luteal_early"] == "luteal"
    assert service.PHASE_GROUP_MAP["luteal_mid"] == "luteal"
    assert service.PHASE_GROUP_MAP["luteal_late"] == "luteal"


def test_calendar_marks_records_and_blank_phase_without_cycle(db):
    service.create_record(db, U1, _payload("2026-11-10", "appetite", 4))
    user = SimpleNamespace(id=U1, gender="女")
    cal = service.calendar_with_records(db, user, 2026, 11)
    by_date = {d["date"]: d for d in cal["days"]}
    assert by_date["2026-11-10"]["has_record"] is True
    assert by_date["2026-11-09"]["has_record"] is False
    # 无月经记录 → 阶段置空，不展示
    assert by_date["2026-11-10"]["phase_key"] is None
    assert by_date["2026-11-10"]["phase_group"] is None

    male = SimpleNamespace(id=U1, gender="男")
    male_cal = service.calendar_with_records(db, male, 2026, 11)
    assert all(d["phase_key"] is None for d in male_cal["days"])
