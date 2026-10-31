"""游泳计算单测（SW-02）：配速、平均划频。"""
from app.modules.swim.service import calc_pace, calc_stroke_rate


def test_pace_basic():
    # 1500m / 33min → 2.2 min/100m（33*60/1500*100/60 = 2.2）
    assert calc_pace(33 * 60, 1500) == 2.2


def test_pace_rounding():
    # 1000m / 25m20s = 1520s → 1520/1000*100/60 = 2.5333 → 2.5
    assert calc_pace(1520, 1000) == 2.5


def test_pace_zero_distance():
    assert calc_pace(600, 0) is None
    assert calc_pace(0, 500) is None


def test_stroke_rate():
    # 742 次 / 33min → 742/(33) = 22.48 → 22.5
    assert calc_stroke_rate(742, 33 * 60) == 22.5


def test_stroke_rate_none():
    assert calc_stroke_rate(None, 600) is None
    assert calc_stroke_rate(100, 0) is None
