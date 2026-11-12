# 体序 BODY ALMANAC · 架构说明

## V2.0 AI 基础设施

V1 的页面/API 双轨和业务服务层保持不变。新增 `app/ai/models/`、
`app/ai/prompts/`、`app/ai/runtime/`、`app/ai/tools/`，分别负责
OpenAI 兼容模型选择、文件提示词版本、LangChain 调用与结构化校验、
未来受控领域工具适配。业务编排放在 `app/modules/electronic_trainer/`；
运动页 AI 入口在所属模块准备上下文，再复用共享运行时和业务服务。

四个已注册模型使用相同 `AI_API_KEY`、`AI_BASE_URL`，默认地址为
`https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1`。
`deepseek-v4.1-flash` 给出的 DashScope 原生 `/api/v1` 地址不用于
OpenAI 兼容客户端。模型能力以注册表显式声明；视觉只对 `qwen3-vl-plus` 声明
（2026-11-10 实测），工具调用暂不声明。
`/api/electronic-trainer/models` 和 `/probe` 使用现有登录门禁，
仅验证配置、提示词和结构化响应，暂不查询健康数据或持久化对话。
V2.0 无 ORM、数据库表或迁移变更。

**AI 导入链路（2026-11-10）**：`POST /api/{sport}/ai-import`（multipart：
`prompt` + 多张 `images`）→ `electronic_trainer/ai_import.py::run_import`
（校验图片、选模型、载入提示词、调用、规范化、校验、落库）→
`app/ai/runtime/invoke.py::invoke_ai_import`（`with_structured_output(..., method="json_schema", strict=True)`，
输出结构由服务端解码期强制）。各运动模块的 `ai_profile.py` 提供输出模型、
`normalize`、`validate`（复用 `json_import.validate_*`）与 `persist`
（复用 `json_import.persist_valid_*` / `service`）。导入数据统一 `recorded`；
不反向调用 `/import-json`，也不引入新的数据表。提示词只有 `{today}`、`{weekday}`
两个变量，正文不写 JSON 结构。

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
| 业务模块 | `app/modules/*` | auth / body / training / swim / dance / cycle / profile / overview / state_record |
| 视图 | `app/templates/` `app/static/` | Jinja2 模板与 CSS/JS/vendor/img |

## 4. 模块职责

| 模块 | 数据表 | 核心能力 |
| --- | --- | --- |
| auth | users | 登录/注册/登出；会话读写；bcrypt 密码哈希 |
| body | 4 张身材表 | 4 组 upsert + 未填字段继承；BMI；四档趋势聚合；剪影标注；Excel 导入/导出 |
| training | training_records / training_records_items / training_notes | 训练计划/记录状态机；动作明细（负荷可空）；容量计算；复制到今日；心得；Excel/JSON 导入 |
| swim | swim_records / swim_notes | 游泳记录/计划两态；配速/划频派生；心得；Excel/JSON 导入 |
| dance | dance_records / dance_notes | 舞蹈记录/计划两态；课程起止时间；心得；Excel/JSON 导入 |
| cycle | cycle_settings / period_records / daily_pain_logs | 周期设置；月经记录增改删；每日疼痛；按日期选锚点的七阶段推算、滚动预测 + 逐日四档状态 |
| profile | users（复用） | 基本资料修改 + 修改密码 |
| overview | 跨模块聚合（只读） | 健身/游泳/舞蹈 日/周/月聚合 + 单日详情 |
| state_record | appetite_record / myalgia_record / inflammation_record | 食欲/肌肉疼痛/炎症按天记录；三表 CRUD + 跨表合并分页 + 当日聚合；月历复用周期阶段三档归并；跨表批量删除带类型定位 |

## 5. 认证与会话

- `SessionMiddleware`：Cookie `sh_session`，`SameSite=Lax`（防 CSRF），`Secure` 由 `.env` 的 `SESSION_COOKIE_SECURE` 控制。
- `app/core/deps.py::get_current_user` 是业务路由统一门禁：无会话或用户不存在时，页面轨抛 `RedirectRequest`（303 → /login），API 轨抛 `AppError(401)`。
- 三运动主表 `user_id` 为指向 users 的数据库外键；所有业务查询仍按登录用户过滤。

## 6. 异常体系（app/core/exceptions.py）

- `AppError(status, message)`：API 轨返回包含 `code`、`error` 的 JSON；页面轨渲染 `error.html`。
- `RedirectRequest(url)`：页面轨内部 303 重定向（如未登录跳登录页）。

## 7. 数据层设计

- 全库 **18 张表**（详见《数据库建表设计.md》），DDL 见 `scripts/schema.sql`，幂等迁移脚本见 `scripts/migrate_*.py`。
- **中文注释元数据**：全量建表脚本在 `scripts/schema.sql` 中维护列注释；既有库由迁移脚本同步。
- **外键**：三运动主表与状态记录三表 `user_id` 引用 `users.id ON DELETE CASCADE`；动作与心得外键引用各自主表。其他业务表沿用原有归属策略。
- **派生值不落库**：BMI、配速、划频、趋势聚合、周期阶段均由 service 实时计算。
- **唯一约束支撑 upsert**：body 4 表按 `(user_id, record_date)` 唯一；`daily_pain_logs` 按 `(user_id, log_date)` 唯一；状态记录三表按 `(user_id, date)` 唯一（同类一天一行）。三运动同日可多条，按主表 id 定位。
- **统一两态**：健身/游泳/舞蹈均为 `status ∈ {planned, recorded}`；健身「完成训练」一键转 recorded；统计口径只计 recorded 行。
- **时间与时长展示口径统一**（2026-11-07）：三运动（健身/游泳/舞蹈）的表单（含计划态）均展示起止时间与时长，均可填、可空（不因计划态隐藏、不设必填）；导入三处同样带起止时间——Excel 模板新增「开始时间 / 结束时间」列（HH:MM，可空），JSON 导入支持 `start_time` / `end_time`（可空），未填时长时按起止时间推导；列表与「查看详情」弹窗对时段/时长/配速/划频等字段不做状态判断，有值即显示、无值显示「—」；**三处导入（Excel/JSON/AI）未填结束时间时保持为空、不补当前时刻**（2026-11-10 起，`create_plan(auto_end_time=False)`），手动新建仍沿用记录态默认记当前时刻的口径；总览日卡计划态时长一律按 0 计，仅 recorded 且有时长才拼时长；心得区块仍仅记录态且确有心得内容才展示。舞蹈的时间字段统一称「上课时间」。
- **统一运动契约**：主表名为 `{sport}_records`，心得表为 `{sport}_notes`；主表必含 id/user_id/date/status/start_time/end_time/duration_s/remark/avg_heart_rate/max_heart_rate/calories/created_at/updated_at，心得必含 id、专属主表外键、rating、notes。各模块可增加字段和表，健身的 `training_records_items` 即专属表。ORM 共用 `SportRecordMixin`、`SportNoteMixin`；规则共用 `sport_ops.py`。详见《数据库建表设计.md》。
- **统一接口**：`/api/training`、`/api/swim-records`、`/api/dance-records` 均提供列表、新建、按 id 编辑/删除、`/daily`、`/stats`、`/template`、`/import`、`/import-json`、`/ai-import`、`/batch-delete`、`/{id}/note` 读写。列表包含计划和记录，批量删除限当前用户的所选 id，心得仅记录态可写。模块专属接口可额外提供。
- **状态记录（非运动模块）**：`appetite_record` / `myalgia_record` / `inflammation_record` 三表结构同构，不套统一运动契约（无计划态、起止时间、时长、心率、热量），字段仅 id/user_id/date/star(0~5 可空；0=最低分，null=未评)/remark/created_at/updated_at。跨表列表在 service 内存合并分页；月历阶段复用 `cycle.service.calendar_month` 推算结果并归并经期/卵泡·排卵/黄体三档，男性或无周期记录时阶段置空。接口前缀 `/api/state-record`：列表（分页 + type 筛选）、`/daily`、`/calendar`、新建、按 id 编辑（body 带 type）、`DELETE /{id}?type=`、`/batch-delete`（items 自带 type）。
- **账号状态与注销**：`users.status ∈ {启用, 停用}`，注册默认启用；登录和请求门禁拦截停用账号。`DELETE /api/profile/account` 要求当前密码，`retain` 停用并清会话，`purge` 在事务中删除用户及全部关联数据后清会话。停用账号通过注册页显式选择恢复、验证原密码后复用原 user_id。无管理员角色及管理员恢复接口。
- **时长存秒、距离存米**，界面按分钟/米展示，派生展示值实时换算。

## 8. 关键业务口径（常量集中在 app/core/constants.py）

- 身材：4 组（basic/goal/girth/target）映射 4 表；新增记录未填字段沿用该维度最近一次非空值；趋势四档（week/month/half_year/year）窗口与锚点见常量。
- 周期：七阶段独立枚举；锚点=最近月经首日；排卵日 = 周期长度 − 14；四档状态按阶段内日序判定（黄体中期前 2 天良好、余下日期一般；黄体后期前 2 天一般、余下日期休息；经期前 3 天休息、第 4 天一般、第 5 天起良好），疼痛 ≥2 覆盖为休息。
- 经期标注：月历逐日的 period_state 由记录窗口判定——落在月经记录窗口内为 recorded（标「经期」；有结束日按结束日，无结束日按经期长度从首日推导）；今天及以后由周期推算得出、未被记录覆盖的经期日为 predicted（标「预测经期」），早于今天且未记录的经期日仍按推算阶段展示。
- 周期颜色由 `app/static/css/tokens.css` 统一提供：月历单元格底色只按四档状态显示浅蓝绿、浅绿、浅黄、浅粉；窄屏仍显示两字状态名；周期静态资源带版本号以避免旧样式缓存。四档底色 2026-11-11 统一向白混合 50% 再浅一档（`--tag-*-bg`），对应圆点/文字深阶不变。
- 运动类型编码色同由 tokens.css 提供：`--ov-fit`（健身·灰）、`--ov-swim`（游泳·蓝）、`--ov-dance`（舞蹈·粉），日视图色条、图例圆点、汇总卡 chip 共用；chip 底色为 `--ov-fit-soft/--ov-swim-soft/--ov-dance-soft`（同基色独立透明度）。ECharts 读不到 CSS 变量，`app/static/js/overview.js` 的 `COLORS` 与 `body.js` 的图表配色一律通过 `App.cssVar('--令牌名')` 运行时读取，不再维护手工副本。
- 记录 / 计划态标记统一取 `--state-plan`（计划·蓝绿）与 `--state-record`（记录·深灰）：总览页列表圆点、chip 圆点，以及 `App.statusTag` 输出的「计划 / 记录」标签同一口径，不得各自取色。
- 字体与渲染：`base.css` 的 `html, body` 逐字照搬 GitHub 原栈（`-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"`）。原栈不含中文字体，中文与中文标点走浏览器默认兜底：本机默认中文即微软雅黑（实测与显式雅黑宽度仅差约 1.5%，肉眼无差），但若换到默认中文为宋体的环境会明显发灰变虚，届时须在 `sans-serif` 之前插入 `"PingFang SC", "Microsoft YaHei", "Noto Sans SC"`（通用族一出现，其后的字体即失效）。按钮/输入框显式 `font-family: inherit`；JSON 导入文本框保留等宽 `ui-monospace/monospace`（代码语义，不并入 UI 字体）。`html, body` 设置 `letter-spacing: .03em` 放宽字距（雅黑下中文偏挤显扁），局部需要更紧的文案可自行覆盖。同时不设置 `-webkit-font-smoothing: antialiased`：该值在 Windows 会关闭 ClearType 次像素抗锯齿，10~12px 小字会发虚。
- 配色规范：颜色唯一来源是 `app/static/css/tokens.css`。CSS 与 Jinja 模板一律用 `var(--令牌)`；**SVG 不能把 `var()` 写进 `fill` / `stroke` 属性**（presentation attribute 不解析变量），必须改写 `style="fill:var(--…)"`。JS / ECharts 用 `App.cssVar(name, fallback)`。
- 同值但语义不同、**禁止合并**的令牌对（合并会让两条业务线绑死）：`#6b7280` = 次要文字 / 记录态 / 健身编码；`#17b3a6` = 品牌强调 / 计划态；`rgba(23,179,166,.10)` = hover 浅底 / 计划标签底；`rgba(27,36,52,.08)` = 焦点环 / 轻投影；`rgba(107,114,128,.10)` = 中性标签底 / 健身 chip 底。要“当前同值、将来可分”，用 `var()` 别名而非删令牌。
- 总览：`/api/overview` 按 day/week/month 聚合，逐日 per-sport 计数 + 汇总卡 + 图表序列；健身时长优先 duration_s，缺失时按 recorded 的 end_time−start_time 推导，游泳/舞蹈= duration_s；热量按记录字段汇总。
- 训练容量：Σ 重量 × 组数 × 每组个数首段数字（reps 为字符串，如 `"10+8+6"` 按 10 计），负荷任一为空跳过。
- 数值精度口径（2026-11-10 统一）：重量类字段 `weight_kg` / `target_weight_kg`（健身动作重量、身材体重/目标体重）统一 `numeric(10,2)`——任意数值、保留两位小数；Pydantic 不再设 `ge/le`，Excel/JSON 导入不做范围限值，前端 `step="0.01"` 且不设 `min`。仅组数保留 1~99 校验。

## 9. 导入导出

- **Excel**：body / training / swim / dance 均提供模板下载（`/template`）+ 导入（`/import`，openpyxl 解析、行级校验、错误明细回传）；body 另提供 `/export` 导出。Excel 列与校验规则集中在各模块 `excel_io.py`。
- **JSON**：training / swim / dance 提供 `/import-json`（字段校验、批量入库），逻辑在 `json_import.py`。
- **AI 导入**：三运动提供 `/ai-import`（文字 + 可选图片，最多 3 张、单张 ≤ 2MB）。结构化输出由 `json_schema` 硬约束，清洗后复用 `json_import` 的校验与 `persist_valid_*` 落库，统一 `recorded`；单条记录日期缺失时按当天处理，起止时间只给一端则整对丢弃，缺关键字段的记录跳过并在 `ai.warnings` 说明。前端一次完成 + 结果就地展示 + 可撤销（批量删除本次新建 id），校验失败可回填 JSON 面板手动修正。
- 健身 Excel 新模板以 `(日期, 训练组编号)` 归属一条主表记录，组内各行是动作；不兼容旧模板。模板含「开始时间 / 结束时间」「平均心率 bpm / 最大心率 bpm / 热量 kcal」三列可选训练级字段，与备注同规则：同组多行取首个非空值；心率 1~300、热量 ≥0。JSON 导入的 plan 对象支持同名字段（`avg_heart_rate`/`max_heart_rate`/`calories`）。三处导入未填结束时间时 `end_time` 留空，不写当前时刻（2026-11-10）。

## 10. 前端组织

- 页面模板 `app/templates`：`base.html` 提供公共布局与 `#modalDetail` 详情弹窗；`layout/sidebar.html` 为分组导航（身材数据 / 状态记录 / 运动训练·计划[健身/游泳/舞蹈] / 生理周期 / 个人信息，男性账号隐藏周期入口；状态记录对男女开放，不做男性重定向）。
- `app/core/templating.py::render_page` 统一注入登录用户、导航高亮、面包屑、侧栏「今日」信息与常量；`today` 按请求取当天（`date.today()`），进程长跑跨天不会停留在启动日。
- 静态资源 `app/static`：css（base/layout/pages/*）、js（common.js 共享弹窗与工具函数 + 各模块页面脚本）、vendor（echarts）、img。
- 三运动页顶部都有新建计划、新增记录、Excel/JSON/AI 导入（AI 弹窗为第三个面板：文字 + 图片 + 识别结果）；主体为当日、档案、全部记录三块。全部记录首列日期、次列类型、末列操作，含查看详情、编辑、删除及批量删除；健身全部记录列出类型/备注/时长/动作/容量（备注列 2026-11-10 由「训练内容」替换，训练内容仍在详情展示）。共用双栏使用可收缩网格列，宽表在卡片内部横向滚动；健身动作表和编辑动作区单独滚动。
- 状态记录页 `/state-record`：三卡片自上而下纵向堆叠（`three-row-stack`，内容随卡片宽度自适应铺满），依次为月历（阶段三档圆点 + 有记录标记，翻月/选日联动）、「当日状态」三类块（食欲/肌肉疼痛/炎症）就地填写——每块内联星级（五星 + 「0」最低分按钮，未评存空）+ 描述 + 保存，有记录时块内可删除，不再弹新增表单、「全部记录」列表（类型分段筛选 + 勾选跨表批量删除 + 分页，操作列查看详情/编辑/删除，行内「编辑」才弹出表单弹窗）。详情复用公共 `#modalDetail`；无 Excel/JSON/AI 导入入口。页级脚本 `app/static/js/state_record.js`，页级样式 `css/pages/state_record.css`。
- 总览页周期切换（2026-11-08）：顶部 `‹ ›` 按当前视图步进锚点并重拉 `/api/overview`（日 ±1 天、周 ±7 天、月 ±1 月；跨月在目标月把日号夹到最后一天，如 1/31 → 2/28）。右上标签显示当前区间（日=`月日 周几`、周=`起止月日`、月=`年月`，跨年补年份），区间不含今天时显示「回到今天」。周视图每日卡在周几右侧带灰色「月/日」（`11/2`）。切视图不改锚点，`?mode=&date=` 始终同步；「今天」取浏览器本地日期，不依赖服务端启动日。
- 弹窗多行文本框自适应（2026-11-10）：`base.css` 给 `.modal textarea` 统一 `resize:none`、`overflow-y:auto`、`max-height:min(300px,42vh)`；`common.js` 的 `autoGrowTextareas` 以 `rows` 撑起的初始高度为下限、CSS `max-height` 为上限，在输入（含中文输入法组字结束）、弹窗打开、弹窗内动态插入条目时重算高度。个别字段用更具体的 `max-height` 收窄上限（如总览单日详情备注框 84px）。新增弹窗无需额外代码，只要把多行输入用 `textarea` 写进 `.modal`。

### 新增运动模块需求确认

用户只需提出“新增一个运动模块：xxx（如跑步、羽毛球...），阅读 AGENTS.md、ARCHITECTURE.md”。AI 先核对现有代码和上述统一契约，再就用户尚未说明的模块专属需求给出建议并追问；已有答案不重复问，确认后再开发。不要要求用户指定 SQL 类型、CSS 类名或实现函数。

统一默认项无需追问：计划态和记录态均必填 `date`，`status` 分别为 `planned`、`recorded`；其他必填业务字段由用户决定。当天卡默认显示状态和备注；运动档案默认显示本周、本月已完成记录次数；全部记录默认依次显示日期、状态（计划/记录标签；现有三页列名为“类型”）、操作（查看详情、编辑、删除），并支持批量删除；编辑与详情默认展示日期、状态。统一表字段、接口、导入入口、总览接入和响应式布局仍按本文件契约实现。

对尚未明确的项目，向用户提供建议选项并询问：

1. 模块中文名、英文标识及页面/API 路径（先按名称提出建议）。
2. `records` 主表还需哪些业务字段；计划态除日期外哪些字段必填；记录态除日期外哪些字段必填。
3. `notes` 心得表除 `rating`、`notes` 外还需哪些字段；是否需要动作、局数等额外表及其归属关系。
4. 是否需要统一接口之外的专属接口或操作；Excel/JSON 导入的一条主记录如何归组。
5. 当天卡、运动档案、全部记录、编辑和详情各需增加展示哪些内容；总览中每条活动的简短摘要与专属统计口径。
6. 该运动在总览中的专属编码色。计划/记录状态色沿用 `--state-plan`、`--state-record`，不为新运动另设状态色。

用户可回答“无额外字段/表/接口/展示”，此时保持统一默认项。业务字段的类型、空值、校验范围和具体布局由 AI 根据已确认需求设计，并与现有模块保持一致。

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
│  │  ├─ overview/     # 跨运动总览聚合（日/周/月）+ 单日详情
│  │  └─ state_record/ # 状态记录：食欲/肌肉疼痛/炎症三表 CRUD + 月历阶段归并
│  ├─ templates/       # Jinja2 页面
│  └─ static/          # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py       # 建表 + 初始化账号（幂等）
│  ├─ migrate_*.py     # 2026-10/11 增量迁移（幂等，可重复执行）
│  └─ schema.sql       # 全量建表 DDL（与《数据库建表设计.md》一致，含中文 COMMENT 段）
└─ tests/              # pytest 单元测试
```

## 12. 测试与运维

- 单元测试：`pytest tests/ -q`（趋势聚合、配速划频、周期阶段、训练状态机、个人信息、总览聚合、状态记录三表 CRUD/合并分页/跨表批量删除等）。
- 建库/初始化：`python scripts/init_db.py`（幂等）；结构迁移按需执行 `scripts/migrate_*.py`。
- 启动：`uvicorn main:app --host 0.0.0.0 --port 8010`（或 .env 的 PORT）。
- 依赖：`uv sync --extra dev` 或 `pip install -r requirements.txt`。
