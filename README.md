# 体序 BODY ALMANAC · 个人健康管理平台（V1）

SSR 单体应用：**FastAPI + Jinja2 + SQLAlchemy + PostgreSQL**，端口 **8010**（避开 8000）。

V1 范围：注册/登录认证 + 六大模块（身材数据 BD / 健身训练 TR / 游泳 SW / 舞蹈 DA / 生理周期 MC / 个人信息 PR）。
严格按《个人健康管理平台开发需求文档》V1 + UI 设计图 + 技术栈实现。

> 2026-11 改版：**运动训练/计划统一「计划/记录」两态 + 跨运动总览（日/周/月）+ 单日详情跳转**。
> - 侧边栏改为分组结构：身材数据 / 运动训练·计划（健身、游泳、舞蹈）/ 生理周期 / 个人信息；
>   总览页 `/overview` 取代原「本周/本月一览」占位菜单。
> - 数据层：swim_records、dance_records 新增 `status`（planned|recorded，默认 recorded）+ `remark`；
>   记录必填列（距离/时长/舞种/星级）转可空；计划态弃用笼统字符串，改为结构化字段
>   （游泳=距离/时长/主泳姿/备注，舞蹈=舞种/星级/备注），原 `plan_text` 列已移除（内容保全至 remark）；
>   training_plans 新增 `remark`。健身保持既有三表特殊构造不动。
> - 接口：新增 `GET /api/overview?granularity=day|week|month&date=`（跨运动聚合）与
>   `GET /api/overview/day?date=`（单日详情）；swim/dance 新增 `GET /api/swim-records|dance-records/daily?date=`；
>   删除已弃用的 `GET /api/training/plans/week`（前端周面板已由总览承接，`service.week_plans` 一并移除，
>   原测试改造为总览聚合断言）。详见《数据库建表设计.md》与本章「2026-11 改版口径」。
> - 总览布局（2026-11-03）：日视图顶部仅保留「训练计划」卡，运动次数/时长并入底部「当日运动情况」；
>   周/月视图「每日运动」卡片置顶并加高、每条标签含时长，顶部聚合收敛为「运动次数+运动时长」并与
>   「每日运动时长」图合并为「运动情况」卡（月视图图表按每日粒度，labels=日号）；消耗估算卡已移除。

## 快速开始

### 0. 环境要求
- Python 3.13+，`uv`（推荐）或 pip
- PostgreSQL 本机运行（端口 5432，库名 `sports-health-platform`，含连字符，SQL 中需双引号）

### 1. 安装依赖

```powershell
uv sync --extra dev   # 或 pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`（已生成则跳过）。关键项：

```
DATABASE_URL=postgresql+psycopg2://postgres:123456@127.0.0.1:5432/sports-health-platform
PORT=8010
SESSION_COOKIE_SECURE=False
SECRET_KEY=<随机生成，勿提交仓库>
```

### 3. 建表 + 初始化账号

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
# 可选参数：--username <名> --password <密码> --display-name <昵称>，默认 admin / admin123
```

### 4. 启动

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8010

```

浏览器打开 http://127.0.0.1:8010，使用 **admin / admin123** 登录；或点击登录页下方
「注册新账号」自助注册（用户名/密码 + 昵称/性别/年龄；身高稍后在「身材数据」中记录）。

### 5. 测试

```powershell
# 单元测试（趋势聚合 / 配速划频 / 周期阶段 / 训练状态机 / 个人信息）
.\.venv\Scripts\python.exe -m pytest tests\ -q

# 端到端冒烟（需服务已启动，写链路会写入临时数据并自动清理；注意：共享库中
# 若已存在 今日/昨日 的真实身材记录，冒烟的按日清理会覆盖，跑前请留意）
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

## 目录结构

```
sports-health-platform/
├─ main.py                 # 入口：SessionMiddleware、路由装配、端口取 .env
├─ config.py               # pydantic-settings 配置
├─ database.py             # SQLAlchemy 引擎 / SessionLocal / Base
├─ models_registry.py      # 全部模型集中注册（建表入口）
├─ app/
│  ├─ core/                # security / deps(登录门禁) / constants / exceptions / pagination / templating
│  ├─ modules/
│  │  ├─ auth/             # 登录/注册/登出/会话（users 表含性别年龄）
│  │  ├─ body/             # 身材数据：4 表拆分 upsert + 未填继承 + 四档趋势 + BMI + 剪影
│  │  ├─ training/         # 训练计划（「完成训练」一键转记录）/历史
│  │  ├─ swim/             # 游泳记录/计划 + 配速/划频计算 + 单日视图
│  │  ├─ dance/            # 舞蹈记录/计划 + 舞种汇总 + 单日视图
│  │  ├─ overview/         # 运动训练/计划总览：日/周/月聚合 + 单日详情（2026-11 新增）
│  │  ├─ cycle/            # 生理周期：七阶段推算 + 月历 + 疼痛 + 运动等级
│  │  └─ profile/          # 个人信息：基本资料（昵称/性别/年龄）+ 修改密码（复用 users 表）
│  ├─ templates/           # Jinja2（base/侧栏/七模块页面 + auth/register + profile）
│  ├─ static/              # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py           # 建表 + 账号幂等
│  ├─ migrate_plan_status.py  # 2026-11：swim/dance 加 status、记录列转可空（幂等）
│  ├─ migrate_remark.py       # 2026-11：三表加 remark、swim/dance 移除 plan_text（幂等）
│  ├─ smoke_test.py        # 端到端冒烟 57 项（含总览/计划态/个人信息）
│  ├─ e2e_checklist.md     # 需求编号 → 实现落点核对表
│  └─ schema.sql           # 全量建表 DDL（整改后结构）
└─ tests/                  # pytest 单测（60 项，含总览聚合 4 项）
```

## 需求口径（锁定实现）

- 配速 pace = duration_s ÷ distance_m × 100 ÷ 60，保留 1 位；划频 = total_strokes ÷ (duration_s ÷ 60)
- BMI = 体重kg ÷ 身高m²，健康区间 18.5~23.9
- 身材数据为 4 张拆分表（基础/期望/围度/目标围度），每表 (user_id, record_date) 唯一；
  页面默认显示记录日期最新一条；4 个分类添加按钮分别写入对应表；
  新增记录未填字段自动沿用该字段最近一次非空值；同日同组重复保存只覆盖当日已提交字段
- 趋势四档：week=本周周一~周日 7 点当日值；month=本月每日；half_year=近 6 个月每月 1/10/20 号、窗口 [锚点-10 天,锚点] 11 天均值；year=近 12 个月每月 1/15 号、窗口 [锚点-15 天,锚点] 16 天均值；无记录断线不插值；基础+围度 11 维可趋势，目标值不参与
- 训练负荷宽松化：动作名称必填，部位/重量/组数/每组个数可空；每组个数为字符串（如 "10+8+6"），容量 = Σ 重量×组数×个数首段数字；期望突破重量计划/记录均可填
- 七阶段：经期 N≤period_length；排卵日 N=cycle_length-14；排卵后 1~2 天排卵后期、3~6 黄体前期、7~10 黄体中期、11 起黄体后期；其余排卵期前期（默认 28/5）
- 运动三档：疼痛 ≥2 → 适合休息（最高优先）；排卵日/排卵前后且疼痛 0 → 精力旺盛；排卵前期/黄体前中期且疼痛 ≤1 → 状态良好；其余适合休息
- 训练状态机：planned → recorded 由「完成训练」一键完成（2026-11-03 移除计时记录模式/庆祝/心得入口）；写 saved_at、不写计时 started_at；已记录当日锁定、不可再改/删
- 周期锚点：最近月经首日；无记录时锚点=今天，锚点前日期不推算阶段
- 心得文本（training_notes.status_text）、游泳主泳姿（swim_records.main_stroke）均可空

## 2026-11 改版口径（运动训练/计划）

- **统一两态**：所有运动均为「计划 planned / 记录 recorded」。健身 = 特殊构造（训练动作 items 量身定制，
  沿用 training_plans/training_plan_items/training_notes 三表；计划练完点「完成训练」二次确认后转 recorded）；
  游泳/舞蹈的计划态为结构化字段：游泳=距离/时长/主泳姿/备注，舞蹈=舞种/星级/备注（不再使用笼统字符串）。
- **数据层**：`scripts/migrate_plan_status.py`（幂等）为 swim/dance 加 `status`、记录必填列转可空、
  建 `(user_id, record_date)` 联合索引；`scripts/migrate_remark.py`（幂等）三表加 `remark`
  （swim/dance 移除 `plan_text`，旧计划文本保全至 remark）。API 层按状态校验必填
  （游泳计划=距离+时长+主泳姿、记录=距离+时长；舞蹈计划=舞种+星级、记录=舞种+星级+时长；泳姿合法）。
  统计口径：stats 只统计 recorded 行；总览聚合中 planned 计 plans、recorded 计 records/时长/热量。
- **总览**：`GET /api/overview?granularity=day|week|month&date=` 返回逐日 per-sport 计数、汇总卡与图表序列
  （week=周一~周日逐日分钟堆叠；month=当月逐日分钟堆叠，labels=1..月末日号；day=chart 为空）；
  `GET /api/overview/day?date=` 返回当日三运动全部条目。页面 `/overview` 默认周视图，
  点击「某天 × 某运动」标签弹单日详情，可一键跳转 `/{sport}?date=某日`。
- **单日页**：健身/游泳/舞蹈页支持 `?date=` 参数 + 前后翻页导航，默认当天；
  总览跳转某日即某日；非当日健身计划不开放「完成训练」（后端同口径校验）。
- **清理**：删除已无前端的 `GET /api/training/plans/week` 与 `service.week_plans`；
  对应测试 `test_week_plans_multi` 改造为 `test_overview_week_includes_training`，
  新增 `tests/test_overview.py`（聚合口径/单日详情/计划态）。

## V1 边界（需求 10.2 / 10.3）

- 不实现：原型演示数据、CSV 导出、顶栏搜索、计划模板、风格面板
- 趋势窗口按需求定稿 11/16 天（含锚点）；body_fat 作为第 8 个体脂指标 Key 纳入

## 交付环境

- 端口：8010（.env 的 PORT 控制）
- 默认账号：admin / admin123（生产部署前请修改，见 scripts/init_db.py 参数）
- 数据库：本地 PostgreSQL `sports-health-platform`（连接信息见 sh-database Skill）
- 图表：echarts 5.5.1（本地 vendor，无外网依赖）；彩带特效为自研轻量 confetti.js（无外部 CDN）
