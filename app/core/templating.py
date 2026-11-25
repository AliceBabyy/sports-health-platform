"""模板渲染公共件：Jinja2 实例与页面公共上下文注入。"""
from datetime import date
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.access import ADMIN_ROLE

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
            {"key": "reports", "url": "/reports", "label": "周/月运动报告", "short": "周/月运动报告"},
            {"key": "training", "url": "/training", "label": "健身", "short": "健身"},
            {"key": "swim", "url": "/swim", "label": "游泳", "short": "游泳"},
            {"key": "dance", "url": "/dance", "label": "舞蹈", "short": "舞蹈"},
        ],
    },
    {"key": "cycle", "url": "/cycle", "label": "生理周期", "short": "周期", "children": []},
    {"key": "agent", "url": "/agent", "label": "AI助手", "short": "AI", "children": [
        {"key": "agent_chat", "url": "/agent", "label": "对话", "short": "对话"},
        {"key": "agent_skills", "url": "/agent/skills", "label": "技能管理", "short": "技能管理"},
        {"key": "agent_personas", "url": "/agent/personas", "label": "角色管理", "short": "角色管理"},
    ]},
    {"key": "profile", "url": "/profile", "label": "个人信息", "short": "我的", "children": [
        {"key": "profile_basic", "url": "/profile", "label": "账号资料", "short": "资料"},
        {"key": "health_profile", "url": "/profile/health-profile", "label": "健康/运动档案", "short": "档案"},
    ]},
    {
        "key": "system",
        "url": "/system/scheduler",
        "label": "系统设置",
        "short": "系统",
        "children": [
            {"key": "scheduler", "url": "/system/scheduler", "label": "定时任务", "short": "定时"},
            {"key": "system_personas", "url": "/system/personas", "label": "内置角色", "short": "角色"},
            {"key": "system_skills", "url": "/system/skills", "label": "内置技能", "short": "技能"},
        ],
    },
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


def _sidebar_daily_advice(user_id: int, today: date) -> dict:
    """侧边栏「今日训练建议」轻量读取：一条索引查询，不调模型（延迟 import 防循环依赖）。"""
    from app.modules.daily_advice.service import get_for_sidebar

    return get_for_sidebar(user_id, today)


def render_page(request: Request, template_name: str, ctx: dict | None = None) -> object:
    """渲染业务页：自动注入登录用户、分组导航高亮、今日信息与常量。

    性别联动：男性账号不显示“生理周期”导航入口与侧栏周期卡片（cycle_today 置空）。
    角色联动：非管理员不显示「系统设置」分组，进入管理员区由 AdminGateMiddleware 拦截。
    分组展开：active 落在分组头或其子菜单时，该分组默认展开（group_open）。
    面包屑：page_title 默认取当前 active 模块名，页面可显式覆盖。
    """
    user = getattr(request.state, "user", None)
    today = date.today()  # 按请求取当天：进程长跑跨天也不会把「今天」停留在启动日
    is_admin_user = user is not None and user.role == ADMIN_ROLE
    cycle_info = {}
    is_male = user is not None and user.gender == "男"
    if user is not None and not is_male:
        try:
            cycle_info = _sidebar_cycle_info(user.id)
        except Exception:  # 周期数据异常不阻塞页面
            cycle_info = {}
    advice_info = None
    if user is not None:
        try:
            advice_info = _sidebar_daily_advice(user.id, today)
        except Exception:  # 建议读取异常不阻塞页面，侧栏降级为缺失态
            advice_info = None
    from app.core import constants as C

    ctx = dict(ctx or {})
    active = ctx.get("active", "")
    nav_groups = [
        g
        for g in NAV_GROUPS
        if not (is_male and g["key"] == "cycle") and (g["key"] != "system" or is_admin_user)
    ]
    group_open = ""
    for g in nav_groups:
        if g.get("children") and active in (g["key"], *(c["key"] for c in g["children"])):
            group_open = g["key"]
            break
    nav_count = sum(1 + len(g.get("children", [])) for g in nav_groups)
    base = {
        "user": user,
        "is_admin": is_admin_user,
        "today": today,
        "today_str": today.strftime("%Y.%m.%d"),
        "weekday_cn": WEEKDAY_CN[today.weekday()],
        "nav_groups": nav_groups,
        "nav_count": nav_count,
        "group_open": group_open,
        "page_title": ctx.get("page_title") or PAGE_TITLE.get(active, "主页"),
        "cycle_today": cycle_info,
        "daily_advice": advice_info,
        "C": C,
    }
    base.update(ctx)
    return templates.TemplateResponse(request, template_name, base)
