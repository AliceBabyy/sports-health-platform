# 体序 BODY ALMANAC · 架构说明

> 个人健康管理平台 V1。本文件只描述实现层面的结构，业务口径详见 README「需求口径」与《数据库建表设计.md》。

## 1. 技术栈

- **后端**：FastAPI（SSR 单体）+ SQLAlchemy 2.0（Mapped 声明式）+ PostgreSQL（psycopg2）
- **前端**：Jinja2 服务端渲染 + 原生 JS；图表 ECharts 5.5.1（本地 vendor，无外网依赖）；彩带为自研轻量 confetti.js
- **认证**：服务端会话 Cookie（SessionMiddleware，SameSite=Lax，无 JWT）
- **配置**：pydantic-settings 读 `.env`；端口 8010（默认）

## 2. 整体架构：页面/API 双轨

所有请求经 FastAPI 路由进入，按返回类型分两轨：

```
浏览器请求
  ├─ 页面轨  router_pages.py   GET /xxx      → Jinja2 渲染 HTML（未登录 303 /login）
  └─ API 轨  router_api.py     /api/xxx      → JSON（未登录 401）
               ↓
          service.py（业务规则、派生计算、口径校验）
               ↓
          models.py（SQLAlchemy ORM）→ PostgreSQL
```

- 页面轨负责可浏览的 SSR 页面与表单提交；API 轨负责列表/增删改查/统计/导入导出。
- 每个业务模块同时挂 `router_pages` 与 `router_api` 两个 APIRouter，在 `main.py` 统一注册。

## 3. 分层结构

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 入口/装配 | `main.py` | app 创建、SessionMiddleware、静态目录、异常注册、路由注册、`/` 重定向 |
| 配置 | `config.py` | Settings：数据库连接、密钥、端口、会话 Cookie 开关 |
| 数据库 | `database.py` | engine / SessionLocal / Base / `get_db` 请求级会话依赖 |
| 模型注册 | `models_registry.py` | 汇总 import 全部模型，供 `create_all` 建表 |
| 核心 | `app/core/` | security（bcrypt）、deps（登录门禁）、constants（口径常量）、exceptions、pagination、templating（页面公共上下文） |
| 业务模块 | `app/modules/*` | auth / body / training / swim / dance / cycle / profile / overview |
| 视图 | `app/templates/` `app/static/` | Jinja2 模板与 CSS/JS/vendor/img |

## 4. 模块职责

| 模块 | 数据表 | 核心能力 |
| --- | --- | --- |
| auth | users | 登录/注册/登出；会话读写；bcrypt 密码哈希 |
| body | 4 张身材表 | 4 组 upsert + 未填字段继承；BMI；四档趋势聚合；剪影标注；Excel 导入/导出 |
| training | training_records / training_records_items / training_notes | 训练计划/记录状态机；动作明细（负荷可空）；容量计算；复制到今日；心得；Excel/JSON 导入 |
| swim | swim_records / swim_notes | 游泳记录/计划两态；配速/划频派生；心得；Excel/JSON 导入 |
| dance | dance_records / dance_notes | 舞蹈记录/计划两态；课程起止时间；心得；Excel/JSON 导入 |
| cycle | cycle_settings / period_records / daily_pain_logs | 周期设置；月经记录增改删；每日疼痛；按日期选锚点的七阶段推算、滚动预测 + 逐日四档状态；有真实记录时才输出运动联动建议 |
| profile | users（复用） | 基本资料修改 + 修改密码 |
| overview | 跨模块聚合（只读） | 健身/游泳/舞蹈 日/周/月聚合 + 单日详情 |

## 5. 认证与会话

- `SessionMiddleware`：Cookie `sh_session`，`SameSite=Lax`（防 CSRF），`Secure` 由 `.env` 的 `SESSION_COOKIE_SECURE` 控制。
- `app/core/deps.py::get_current_user` 是业务路由统一门禁：无会话或用户不存在时，页面轨抛 `RedirectRequest`（303 → /login），API 轨抛 `AppError(401)`。
- 三运动主表 `user_id` 为指向 users 的数据库外键；所有业务查询仍按登录用户过滤。

## 6. 异常体系（app/core/exceptions.py）

- `AppError(status, message)`：API 轨返回包含 `code`、`error` 的 JSON；页面轨渲染 `error.html`。
- `RedirectRequest(url)`：页面轨内部 303 重定向（如未登录跳登录页）。

## 7. 数据层设计

- 全库 **15 张表**（详见《数据库建表设计.md》），DDL 见 `scripts/schema.sql`，幂等迁移脚本见 `scripts/migrate_*.py`。
- **中文注释元数据**：全量建表脚本在 `scripts/schema.sql` 中维护列注释；既有库由迁移脚本同步。
- **外键**：三运动主表 `user_id` 引用 `users.id ON DELETE CASCADE`；动作与心得外键引用各自主表。其他业务表沿用原有归属策略。
- **派生值不落库**：BMI、配速、划频、趋势聚合、周期阶段均由 service 实时计算。
- **唯一约束支撑 upsert**：body 4 表按 `(user_id, record_date)` 唯一；`daily_pain_logs` 按 `(user_id, log_date)` 唯一。三运动同日可多条，按主表 id 定位。
- **统一两态**：健身/游泳/舞蹈均为 `status ∈ {planned, recorded}`；健身「完成训练」一键转 recorded；统计口径只计 recorded 行。
- **统一运动契约**：主表名为 `{sport}_records`，心得表为 `{sport}_notes`；主表必含 id/user_id/date/status/start_time/end_time/duration_s/remark/avg_heart_rate/max_heart_rate/calories/created_at/updated_at，心得必含 id、专属主表外键、rating、notes。各模块可增加字段和表，健身的 `training_records_items` 即专属表。ORM 共用 `SportRecordMixin`、`SportNoteMixin`；规则共用 `sport_ops.py`。详见《数据库建表设计.md》。
- **统一接口**：`/api/training`、`/api/swim-records`、`/api/dance-records` 均提供列表、新建、按 id 编辑/删除、`/daily`、`/stats`、`/template`、`/import`、`/import-json`、`/batch-delete`、`/{id}/note` 读写。列表包含计划和记录，批量删除限当前用户的所选 id，心得仅记录态可写。模块专属接口可额外提供。
- **账号状态与注销**：`users.status ∈ {启用, 停用}`，注册默认启用；登录和请求门禁拦截停用账号。`DELETE /api/profile/account` 要求当前密码，`retain` 停用并清会话，`purge` 在事务中删除用户及全部关联数据后清会话。停用账号通过注册页显式选择恢复、验证原密码后复用原 user_id。无管理员角色及管理员恢复接口。
- **时长存秒、距离存米**，界面按分钟/米展示，派生展示值实时换算。

## 8. 关键业务口径（常量集中在 app/core/constants.py）

- 身材：4 组（basic/goal/girth/target）映射 4 表；新增记录未填字段沿用该维度最近一次非空值；趋势四档（week/month/half_year/year）窗口与锚点见常量。
- 周期：七阶段独立枚举；锚点=最近月经首日；排卵日 = 周期长度 − 14；四档状态按阶段内日序判定（黄体中期前 2 天良好、余下日期一般；黄体后期前 2 天一般、余下日期休息；经期前 3 天休息、第 4 天一般、第 5 天起良好），疼痛 ≥2 覆盖为休息。
- 周期颜色由 `app/static/css/tokens.css` 统一提供：月历单元格底色只按四档状态显示浅蓝绿、浅绿、浅黄、浅粉；窄屏仍显示两字状态名；周期静态资源带版本号以避免旧样式缓存。
- 总览：`/api/overview` 按 day/week/month 聚合，逐日 per-sport 计数 + 汇总卡 + 图表序列；健身时长优先 duration_s，缺失时按 recorded 的 end_time−start_time 推导，游泳/舞蹈= duration_s；热量按记录字段汇总。
- 训练容量：Σ 重量 × 组数 × 每组个数首段数字（reps 为字符串，如 `"10+8+6"` 按 10 计），负荷任一为空跳过。

## 9. 导入导出

- **Excel**：body / training / swim / dance 均提供模板下载（`/template`）+ 导入（`/import`，openpyxl 解析、行级校验、错误明细回传）；body 另提供 `/export` 导出。Excel 列与校验规则集中在各模块 `excel_io.py`。
- **JSON**：training / swim / dance 提供 `/import-json`（字段校验、批量入库），逻辑在 `json_import.py`。
- 健身 Excel 新模板以 `(日期, 训练组编号)` 归属一条主表记录，组内各行是动作；不兼容旧模板。

## 10. 前端组织

- 页面模板 `app/templates`：`base.html` 提供公共布局与 `#modalDetail` 详情弹窗；`layout/sidebar.html` 为分组导航（身材 / 运动训练·计划[健身/游泳/舞蹈] / 生理周期 / 个人信息，男性账号隐藏周期入口）。
- `app/core/templating.py::render_page` 统一注入登录用户、导航高亮、面包屑、侧栏「今日」信息与常量。
- 静态资源 `app/static`：css（base/layout/pages/*）、js（common.js 共享弹窗与工具函数 + 各模块页面脚本）、vendor（echarts）、img。
- 三运动页顶部都有新建计划、新增记录、Excel/JSON 导入；主体为当日、档案、全部记录、周期联动四块。全部记录首列日期、次列类型、末列操作，含查看详情、编辑、删除及批量删除；窄屏表格横向滚动。

## 11. 目录结构

```
sports-health-platform/
├─ main.py / config.py / database.py / models_registry.py
├─ app/
│  ├─ core/            # security / deps / constants / exceptions / pagination / templating
│  ├─ modules/
│  │  ├─ auth/         # 登录/注册/登出/会话（users）
│  │  ├─ body/         # 身材 4 表 + 趋势 + Excel 导入导出
│  │  ├─ training/     # 健身计划/记录状态机 + 心得 + Excel/JSON 导入
│  │  ├─ swim/         # 游泳记录/计划 + 心得 + Excel/JSON 导入
│  │  ├─ dance/        # 舞蹈记录/计划 + 心得 + Excel/JSON 导入
│  │  ├─ cycle/        # 生理周期七阶段 + 疼痛 + 运动等级
│  │  ├─ profile/      # 个人资料 + 修改密码
│  │  └─ overview/     # 跨运动总览聚合（日/周/月）+ 单日详情
│  ├─ templates/       # Jinja2 页面
│  └─ static/          # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py       # 建表 + 初始化账号（幂等）
│  ├─ migrate_*.py     # 2026-10/11 增量迁移（幂等，可重复执行）
│  └─ schema.sql       # 全量建表 DDL（与《数据库建表设计.md》一致，含中文 COMMENT 段）
└─ tests/              # pytest 单元测试
```

## 12. 测试与运维

- 单元测试：`pytest tests/ -q`（趋势聚合、配速划频、周期阶段、训练状态机、个人信息、总览聚合等）。
- 建库/初始化：`python scripts/init_db.py`（幂等）；结构迁移按需执行 `scripts/migrate_*.py`。
- 启动：`uvicorn main:app --host 0.0.0.0 --port 8010`（或 .env 的 PORT）。
- 依赖：`uv sync --extra dev` 或 `pip install -r requirements.txt`。
