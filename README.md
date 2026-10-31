# 体序 BODY ALMANAC · 个人健康管理平台（V1）

SSR 单体应用：**FastAPI + Jinja2 + SQLAlchemy + PostgreSQL**，端口 **8010**（避开 8000）。

V1 范围：注册/登录认证 + 五大模块（身材数据 BD / 健身训练 TR / 游泳 SW / 舞蹈 DA / 生理周期 MC）。
严格按《个人健康管理平台开发需求文档》V1 + UI 设计图 + 技术栈实现。

> 2026-10 建模整改：users 新增性别/年龄 + 注册功能（身高移除，统一走 body_basic_records）；
> body_metric_records 宽表拆为 4 张表（基础/期望/围度/目标围度，均含 created_at/updated_at，
> 新增记录未填字段沿用最近一次非空值）；training_plan_items 负荷四字段可空、reps 字符串化、
> 期望突破重量计划态亦可填；training_notes.status_text、swim_records.main_stroke 可空。
> 详见《数据库建表设计.md》。

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
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8010
```

浏览器打开 http://127.0.0.1:8010，使用 **admin / admin123** 登录；或点击登录页下方
「注册新账号」自助注册（用户名/密码 + 昵称/性别/年龄；身高稍后在「身材数据」中记录）。

### 5. 测试

```powershell
# 单元测试（趋势聚合 / 配速划频 / 周期阶段 / 训练状态机）
.\.venv\Scripts\python.exe -m pytest tests\ -q

# 端到端冒烟（需服务已启动，写链路会写入临时数据并自动清理）
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
│  │  ├─ training/         # 训练计划/记录模式状态机/庆祝/心得/历史
│  │  ├─ swim/             # 游泳记录 + 配速/划频计算
│  │  ├─ dance/            # 舞蹈记录 + 舞种汇总
│  │  └─ cycle/            # 生理周期：七阶段推算 + 月历 + 疼痛 + 运动等级
│  ├─ templates/           # Jinja2（base/侧栏/五模块页面 + auth/register）
│  ├─ static/              # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py           # 建表 + 账号幂等
│  ├─ smoke_test.py        # 端到端冒烟 37 项（含注册/4 表拆分/继承/训练 reps）
│  ├─ e2e_checklist.md     # 需求编号 → 实现落点核对表
│  └─ schema.sql           # 全量建表 DDL（整改后结构）
└─ tests/                  # pytest 单测（35 项）
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
- 训练状态机：status 只存终态 recorded；started_at 区分「仅编辑/开始训练」；时长后端算（saved_at - started_at）；已保存当日锁定
- 周期锚点：最近月经首日；无记录时锚点=今天，锚点前日期不推算阶段
- 心得文本（training_notes.status_text）、游泳主泳姿（swim_records.main_stroke）均可空

## V1 边界（需求 10.2 / 10.3）

- 不实现：原型演示数据、CSV 导出、顶栏搜索、计划模板、风格面板
- 趋势窗口按需求定稿 11/16 天（含锚点）；body_fat 作为第 8 个体脂指标 Key 纳入

## 交付环境

- 端口：8010（.env 的 PORT 控制）
- 默认账号：admin / admin123（生产部署前请修改，见 scripts/init_db.py 参数）
- 数据库：本地 PostgreSQL `sports-health-platform`（连接信息见 sh-database Skill）
- 图表：echarts 5.5.1（本地 vendor，无外网依赖）；彩带特效为自研轻量 confetti.js（无外部 CDN）
