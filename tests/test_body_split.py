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


# ---------- 单条更新（基础/围度） ----------

def test_update_group_record_overwrites_submitted_only(db):
    """单条更新：只覆盖提交字段，未提交字段保留当日原值。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0, "height": 165.0})
    ok = body_service.update_group_record(db, USER, "basic", _d("2026-10-20"), {"weight": 62.0})
    assert ok is True
    snap = body_service.latest_snapshot(db, USER)
    assert snap["weight"]["value"] == 62.0
    assert snap["height"]["value"] == 165.0


def test_update_group_record_missing_row_returns_false(db):
    """当日该组无记录 → 返回 False（API 层转 404）。"""
    ok = body_service.update_group_record(db, USER, "basic", _d("2026-10-20"), {"weight": 62.0})
    assert ok is False


def test_update_girth_group_record(db):
    body_service.upsert_group(db, USER, "girth", _d("2026-10-20"), {"waist": 70.0, "chest": 88.0})
    ok = body_service.update_group_record(db, USER, "girth", _d("2026-10-20"), {"waist": 68.0})
    assert ok is True
    snap = body_service.latest_snapshot(db, USER)
    assert snap["waist"]["value"] == 68.0
    assert snap["chest"]["value"] == 88.0  # 未提交字段保留


def test_update_group_record_ignores_unknown_key(db):
    """提交不属于该组的字段：service 层直接忽略（API 层会先拒绝）。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0})
    body_service.update_group_record(db, USER, "basic", _d("2026-10-20"), {"weight": 62.0, "waist": 99.0})
    snap = body_service.latest_snapshot(db, USER)
    assert snap["weight"]["value"] == 62.0
    assert snap["waist"]["value"] is None


# ---------- 目标与进度 ----------

def test_goal_progress_compares_target_and_current(db):
    """目标值与对应当前值比较：remaining = 当前 − 目标，start 为最早记录值。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0, "body_fat": 22.0})
    body_service.upsert_group(db, USER, "goal", _d("2026-10-21"), {"target_weight": 55.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-21"), {"waist": 70.0})
    body_service.upsert_group(db, USER, "target", _d("2026-10-22"), {"target_waist": 65.0})
    gp = body_service.goal_progress(db, USER)
    assert gp["total"] == 2
    assert gp["missing"] == 6  # 其余 6 个目标未设置
    items = {i["key"]: i for i in gp["items"]}
    tw = items["target_weight"]
    assert tw["label"] == "目标体重"
    assert tw["unit"] == "kg"
    assert tw["target"] == 55.0
    assert tw["current"] == 60.0
    assert tw["start"] == 60.0  # 唯一一条历史记录即起始值
    assert tw["remaining"] == 5.0
    assert tw["reached"] is False
    assert tw["pct"] == 0.0  # 当前 == 起始 → 进度为 0
    assert "继续加油" in tw["msg"]
    twaist = items["target_waist"]
    assert twaist["current"] == 70.0
    assert twaist["remaining"] == 5.0


def test_goal_progress_uses_earliest_record(db):
    """进度从最早历史记录值起算：(起始 − 当前) / (起始 − 目标)。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-01"), {"weight": 70.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-10"), {"weight": 65.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0})
    body_service.upsert_group(db, USER, "goal", _d("2026-10-21"), {"target_weight": 55.0})
    gp = body_service.goal_progress(db, USER)
    items = {i["key"]: i for i in gp["items"]}
    tw = items["target_weight"]
    assert tw["start"] == 70.0  # 最早一条
    assert tw["current"] == 60.0  # 最新一条
    assert tw["remaining"] == 5.0
    assert tw["pct"] == round((70.0 - 60.0) / (70.0 - 55.0) * 100, 1)  # 66.7
    assert tw["reached"] is False
    assert "已完成" in tw["msg"] and "还差" in tw["msg"]


def test_goal_progress_reached_at_target(db):
    """当前值等于目标值 → reached=True、pct=100、文案为已达成。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 55.0})
    body_service.upsert_group(db, USER, "goal", _d("2026-10-21"), {"target_weight": 55.0})
    gp = body_service.goal_progress(db, USER)
    items = {i["key"]: i for i in gp["items"]}
    assert items["target_weight"]["reached"] is True
    assert items["target_weight"]["pct"] == 100
    assert items["target_weight"]["msg"] == "已达成目标"


def test_goal_progress_empty_when_no_goals(db):
    gp = body_service.goal_progress(db, USER)
    assert gp["items"] == []
    assert gp["total"] == 0
    assert gp["missing"] == 8


# ---------- 达成成就 ----------

def test_achievement_progress_always_returns_seven_items(db):
    """卡片固定 7 项（体重/体脂/臂围/腰围/臀围/大腿围/小腿围，不含胸围）；无数据时 has_data=False。"""
    ap = body_service.achievement_progress(db, USER)
    assert [i["key"] for i in ap["items"]] == ["weight", "body_fat", "arm", "waist", "hip", "thigh", "calf"]
    assert all(i["current"] is None and i["start"] is None for i in ap["items"])
    assert all(i["delta"] is None and i["has_change"] is False for i in ap["items"])
    assert ap["has_data"] is False


def test_achievement_progress_start_is_earliest_record(db):
    """首次 = 该指标最早一条历史记录；delta 以「首次 − 最新」计算并生成鼓励文案（不与目标比较）。"""
    body_service.upsert_group(db, USER, "basic", _d("2026-10-01"), {"weight": 70.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-10"), {"weight": 65.0})
    body_service.upsert_group(db, USER, "basic", _d("2026-10-20"), {"weight": 60.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-15"), {"waist": 80.0})
    body_service.upsert_group(db, USER, "girth", _d("2026-10-25"), {"waist": 76.0})
    ap = body_service.achievement_progress(db, USER)
    items = {i["key"]: i for i in ap["items"]}
    assert ap["has_data"] is True
    w = items["weight"]
    assert w["start"] == 70.0  # 最早一条
    assert w["current"] == 60.0  # 最新一条
    assert w["start_date"] == "2026.10.01"
    assert w["delta"] == 10.0
    assert w["direction"] == "down"
    assert w["change_msg"] == "已减 10.0 kg"
    assert w["has_change"] is True
    assert "target" not in w  # 与目标无关，不再携带目标字段
    wa = items["waist"]
    assert wa["start"] == 80.0
    assert wa["current"] == 76.0
    assert wa["start_date"] == "2026.10.15"
    assert wa["delta"] == 4.0
    assert wa["change_msg"] == "已减 4.0 cm"
    assert "chest" not in items  # 胸围不在卡片 7 项内
