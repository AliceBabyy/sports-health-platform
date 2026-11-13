"""模板渲染公共件：Jinja2 实例与页面公共上下文注入。"""
from datetime import date
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parents[2]  # 项目根目录
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 侧边栏分组结构（2026-11 改版）：运动训练/计划为分组头，健身/游泳/舞蹈为二级子菜单。
# short：折叠态（仅图标/两字）显示文本。
NAV_GROUPS = [
    {"key": "body", "url": "/body", "label": "身材数据", "short": "身材", "children": []},
    {"key": "state_record", "url": "/state-record", "label": "状态记录", "short": "状态", "children": []},
    {
        "key": "overview",
        "url": "/overview",
        "label": "运动训练/计划",
        "short": "训练",
        "children": [
            {"key": "training", "url": "/training", "label": "健身", "short": "健身"},
            {"key": "swim", "url": "/swim", "label": "游泳", "short": "游泳"},
            {"key": "dance", "url": "/dance", "label": "舞蹈", "short": "舞蹈"},
        ],
    },
    {"key": "cycle", "url": "/cycle", "label": "生理周期", "short": "周期", "children": []},
    {"key": "profile", "url": "/profile", "label": "个人信息", "short": "我的", "children": []},
    {"key": "agent", "url": "/agent", "label": "AI助手", "short": "AI", "children": []},
]

PAGE_TITLE = {g["key"]: g["label"] for g in NAV_GROUPS}
# 二级子菜单模块（健身/游泳/舞蹈）也应有面包屑标题
for g in NAV_GROUPS:
    for c in g.get("children", []):
        PAGE_TITLE[c["key"]] = c["label"]


def _sidebar_cycle_info(user_id: int):
    """侧边栏左下角“今天”小卡：周期第 N 天 + 今日运动等级（延迟 import 防循环依赖）。"""
    from app.modules.cycle.service import get_today_summary

    return get_today_summary(user_id)


def render_page(request: Request, template_name: str, ctx: dict | None = None) -> object:
    """渲染业务页：自动注入登录用户、分组导航高亮、今日信息与常量。

    性别联动：男性账号不显示“生理周期”导航入口与侧栏周期卡片（cycle_today 置空）。
    分组展开：active 落在分组头或其子菜单时，该分组默认展开（group_open）。
    面包屑：page_title 默认取当前 active 模块名，页面可显式覆盖。
    """
    user = getattr(request.state, "user", None)
    today = date.today()  # 按请求取当天：进程长跑跨天也不会把「今天」停留在启动日
    cycle_info = {}
    is_male = user is not None and user.gender == "男"
    if user is not None and not is_male:
        try:
            cycle_info = _sidebar_cycle_info(user.id)
        except Exception:  # 周期数据异常不阻塞页面
            cycle_info = {}
    from app.core import constants as C

    ctx = dict(ctx or {})
    active = ctx.get("active", "")
    nav_groups = [g for g in NAV_GROUPS if not (is_male and g["key"] == "cycle")]
    group_open = ""
    for g in nav_groups:
        if g.get("children") and active in (g["key"], *(c["key"] for c in g["children"])):
            group_open = g["key"]
            break
    nav_count = sum(1 + len(g.get("children", [])) for g in nav_groups)
    base = {
        "user": user,
        "today": today,
        "today_str": today.strftime("%Y.%m.%d"),
        "weekday_cn": WEEKDAY_CN[today.weekday()],
        "nav_groups": nav_groups,
        "nav_count": nav_count,
        "group_open": group_open,
        "page_title": ctx.get("page_title") or PAGE_TITLE.get(active, "主页"),
        "cycle_today": cycle_info,
        "C": C,
    }
    base.update(ctx)
    return templates.TemplateResponse(request, template_name, base)
