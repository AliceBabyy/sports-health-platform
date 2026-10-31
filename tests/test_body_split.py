"""身材 4 表拆分单测：分组 upsert（同日覆盖）、新日期未填字段继承最近非空值、
最新快照跨组合并、按日期合并列表、按日删除 4 组。"""
from datetime import date

from app.modules.body import service as body_service

USER = 1


def _d(day: str) -> date:
    return date.fromisoformat(day)


def test_upsert_new_row_inherits_last_value(db):
    """新日期只填体重 → 身高/体脂率继承最近一次非空值。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0, "height": 165.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-21"), {"weight": 61.0})
    snap = body_service.latest_snapshot(db, USER)
    assert snap["weight"]["value"] == 61.0
    assert snap["height"]["value"] == 165.0  # 继承 10-20 的身高


def test_upsert_same_day_overwrites_submitted_only(db):
    """同日重复添加同组：只覆盖提交字段，未提交字段保留当日原值。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0, "height": 165.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 62.0})
    snap = body_service.latest_snapshot(db, USER)
    assert snap["weight"]["value"] == 62.0
    assert snap["height"]["value"] == 165.0


def test_upsert_rejects_unknown_key(db):
    """提交不属于该组的字段会被 API 拒绝；service 层直接忽略（不抛错、不落库）。"""
    body_service.upsert_group(db, USER, "goal", _d("2026-10-20"), {"target_weight": 55.0, "weight": 99.0})
    snap = body_service.latest_snapshot(db, USER)
    assert snap["target_weight"]["value"] == 55.0
    assert snap["weight"]["value"] is None  # weight 不属于 goal 组，未写入


def test_latest_snapshot_merges_groups_and_bmi(db):
    """4 组最新值合并 + BMI 由最新身高体重计算。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"height": 170.0, "weight": 60.0})
    body_service.upsert_group(db, USER, "goal", _d("2026-10-21"), {"target_weight": 55.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-21"), {"waist": 68.0, "chest": 88.0})
    body_service.upsert_group(db, USER, "target", _d("2026-10-22"), {"target_waist": 65.0})
    snap = body_service.latest_snapshot(db, USER)
    assert snap["weight"]["value"] == 60.0
    assert snap["height"]["value"] == 170.0
    assert snap["target_weight"]["value"] == 55.0
    assert snap["waist"]["value"] == 68.0
    assert snap["target_waist"]["value"] == 65.0
    assert snap["bmi"] == round(60.0 / (1.70 ** 2), 1)


def test_list_records_merges_by_date(db):
    """不同日期的 4 组记录按日期合并，同一日期合并为一行的 values。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-20"), {"waist": 68.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-21"), {"weight": 61.0})
    res = body_service.list_records(db, USER, 1, 10)
    assert res["total"] == 2
    by_date = {r["record_date"]: r["values"] for r in res["list"]}
    assert by_date["2026-10-21"]["weight"] == 61.0
    assert by_date["2026-10-20"]["weight"] == 60.0
    assert by_date["2026-10-20"]["waist"] == 68.0


def test_delete_day_removes_all_groups(db):
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-20"), {"waist": 68.0})
    deleted = body_service.delete_day(db, USER, _d("2026-10-20"))
    assert deleted == 2
    assert body_service.list_records(db, USER, 1, 10)["total"] == 0
