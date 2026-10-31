"""模板渲染公共件：Jinja2 实例与页面公共上下文注入。"""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parents[2]  # 项目根目录
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

NAV_ITEMS = [
    ("body", "/body", "身材数据"),
    ("training", "/training", "健身训练"),
    ("swim", "/swim", "游泳记录"),
    ("dance", "/dance", "舞蹈记录"),
    ("cycle", "/cycle", "生理周期"),
]


def _sidebar_cycle_info(user_id: int):
    """侧边栏左下角“今天”小卡：周期第 N 天 + 今日运动等级（延迟 import 防循环依赖）。"""
    from app.modules.cycle.service import get_today_summary

    return get_today_summary(user_id)


def render_page(request: Request, template_name: str, ctx: dict | None = None) -> object:
    """渲染业务页：自动注入登录用户、导航高亮、今日信息与常量。"""
    user = getattr(request.state, "user", None)
    today = request.app.state.today
    cycle_info = {}
    if user is not None:
        try:
            cycle_info = _sidebar_cycle_info(user.id)
        except Exception:  # 周期数据异常不阻塞页面
            cycle_info = {}
    from app.core import constants as C

    base = {
        "user": user,
        "today": today,
        "today_str": today.strftime("%Y.%m.%d"),
        "weekday_cn": WEEKDAY_CN[today.weekday()],
        "nav_items": NAV_ITEMS,
        "cycle_today": cycle_info,
        "C": C,
    }
    base.update(ctx or {})
    return templates.TemplateResponse(request, template_name, base)
