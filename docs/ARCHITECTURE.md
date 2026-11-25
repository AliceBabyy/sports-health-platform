# 体序 BODY ALMANAC · 架构说明

## 文档范围

本文档描述当前已实现的系统宏观架构、技术栈、业务模块、共同契约、数据层、目录结构和运维方式。AI 的详细架构、功能清单、工具注册和开发契约见 [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md)；前端规范见 [FRONTEND_GUIDELINES.md](FRONTEND_GUIDELINES.md)；运动模块规范见 [SPORT_MODULE_GUIDELINES.md](SPORT_MODULE_GUIDELINES.md)。业务字段和数据库明细见《数据库建表设计.md》，AI 版本规划和未实现设想见 [AIplan.md](AIplan.md)。

## AI 子模块概述

项目 AI 能力由模型注册与调用、提示词管理、结构化 AI 导入、AI Agent 会话、只读数据工具、按轮开启的联网搜索、受控写工具、对话中途提问和技能系统组成。相关能力位于 `app/ai/`、`app/modules/electronic_trainer/` 和 `app/modules/agent/`，使用独立的 AI 运行时与 LangGraph checkpointer；详细实现见 [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md)。AI 功能不改动既有业务表字段；Agent 消息由 `langgraph` schema 中的 checkpointer 表持久化，会话元数据由 `agent_conversations` 保存，技能定义与审计由 `agent_skills` / `agent_skill_versions` / `agent_skill_runs` 保存，多角色定义与版本由 `agent_personas` / `agent_persona_versions` 保存。
## 1. 技术栈

- **后端**：FastAPI（SSR 单体）+ SQLAlchemy 2.0（Mapped 声明式）+ PostgreSQL；ORM 用 psycopg2，AI Agent checkpointer 用 psycopg3 异步 + LangGraph
- **前端**：Jinja2 服务端渲染 + 原生 JS；图表 ECharts 5.5.1（本地 vendor，无外网依赖）；彩带为自研轻量 confetti.js
- **认证**：服务端会话 Cookie（SessionMiddleware，SameSite=Lax，无 JWT）
- **配置**：pydantic-settings 读 `.env`；端口 8010（默认）

## 2. 整体架构：页面与 API 双轨

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

- 页面轨负责 SSR 页面和表单提交；API 轨负责列表、增删改查、统计及导入导出。
- 每个业务模块同时提供 `router_pages` 和 `router_api` 两个 APIRouter，并由 `main.py` 统一注册。

## 3. 分层结构与目录职责

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 入口/装配 | `main.py` | app 创建、SessionMiddleware、静态目录、异常注册、路由注册、`/` 重定向 |
| 配置 | `config.py` | Settings：数据库连接、密钥、端口、会话 Cookie 开关 |
| 数据库 | `database.py` | engine / SessionLocal / Base / `get_db` 请求级会话依赖 |
| 模型注册 | `models_registry.py` | 汇总 import 全部模型，供 `create_all` 建表 |
| 核心 | `app/core/` | security（bcrypt）、deps（登录门禁）、constants（口径常量）、exceptions、pagination、templating（页面公共上下文） |
| 业务模块 | `app/modules/*` | auth / body / training / swim / dance / cycle / profile / overview / state_record / report / agent / system |
| 视图 | `app/templates/` `app/static/` | Jinja2 模板与 CSS/JS/vendor/img |

## 4. 业务模块职责

| 模块 | 数据表 | 核心能力 |
| --- | --- | --- |
| auth | users | 登录/注册/登出；会话读写；bcrypt 密码哈希 |
| body | 4 张身材表 | 4 组 upsert + 未填字段继承；BMI；五档趋势聚合；剪影标注；Excel 导入/导出 |
| training | training_records / training_records_items / training_notes | 训练计划/记录状态机；动作明细（负荷可空）；容量计算；复制到今日；心得；Excel/JSON 导入 |
| swim | swim_records / swim_notes | 游泳记录/计划两态；配速/划频派生；心得；Excel/JSON 导入 |
| dance | dance_records / dance_notes | 舞蹈记录/计划两态；课程起止时间；心得；Excel/JSON 导入 |
| cycle | period_setting / period_records / period_logs | 周期参考值；月经记录增改删（起止日期）；每日疼痛（仅 recorded 经期可填并归属记录）+ 当日 note；周期日志分页与「全部记录」两段切换；按记录分段推算七阶段、双份激素文案、只延伸一段 + 逐日四档状态 |
| profile | users（复用）+ health_profile | 基本资料修改 + 修改密码；健康/运动档案（一用户多行，固定 aspect 模板 + 最新一套角色定制问题，题目 key 固定、答案为文本） |
| overview | 跨模块聚合（只读） | 健身/游泳/舞蹈 日/周/月聚合 + 单日详情 |
| state_record | state_appetite_record / state_myalgia_record / state_inflammation_record / state_mood_record | 食欲/肌肉疼痛/炎症/情绪按天记录；四表 CRUD + 跨表合并分页 + 当日聚合；月历复用周期阶段三档归并；跨表批量删除带类型定位 |
| report | reports | AI 运动周报/月报：/reports 单页周/月切换；事实层确定性计算（三运动 + 身材 + 状态 + 周期）→ 叙事层结构化输出 → 依据层；同周期快照复用、过期检测、软删除；空数据走规则文案不调模型；由 system/scheduler 子包按周一/每月 1 日 cron 触发 |
| daily_advice | daily_advice | 侧栏「今日训练建议」：/api/daily-advice 读取与重新生成；事实层确定性计算（基础信息 + 身材 + 昨日/近 7 天负荷 + 状态 + 当天计划 + 女性周期）→ 硬约束由代码降档 → 模型只解释；一天一条，00:01 由 system/scheduler 子包触发，启动补跑缺失行 |
| system | scheduled_jobs / job_runs / agent_personas / agent_skills | 系统管理区：聚合页面前缀 `/system` 与 API 前缀 `/api/system`，**仅管理员可访问**（AdminGateMiddleware 按前缀拦截），子模块以相对前缀 router 挂入；当前含 `scheduler/`（定时任务）、`personas/`（内置角色 CRUD + 工具/技能白名单）与 `skills/`（平台内置技能管理：代码技能只读+启停，声明式技能 CRUD/版本/校验/试运行/运行记录），页面 `/system/scheduler`、`/system/personas`、`/system/skills` |
| agent | agent_conversations / agent_personas / agent_persona_versions / agent_skills / agent_skill_versions / agent_skill_runs | LangGraph 多会话/多轮问答；工具循环（agent ⇄ ToolNode）；8 个只读工具覆盖身材/状态记录/健身/游泳/舞蹈/生理周期/个人资料，范围与条数按意图可选、不传即全量；平台只读代码/声明式技能 + 用户私有提示词技能；斜杠自然语言触发、参数解析与追问续接；按用户技能集与角色授权装配图；多角色（营养师/电子私教/健康档案测试内置 + 用户自定义提示词角色，角色会话创建时固定版本、不可切换，角色定义只提供提示词；工具/技能默认范围由 `TOOL_PERSONA_SCOPES` 提供，管理员可写显式白名单；健康档案测试专用写工具默认仅该角色可用）；SSE 流式（含工具/技能事件）；会话 CRUD/归属隔离；模型下拉；最近一轮可重新生成并覆盖；生成中途可停止并保留半截回答，停止后可「继续」续写或重新生成；按轮开启的 Tavily 联网搜索（默认关闭，未开启时不装配 `web_search`）；硬删除 |

## 5. 认证与会话机制

- `SessionMiddleware`：Cookie `sh_session`，`SameSite=Lax`（防 CSRF），`Secure` 由 `.env` 的 `SESSION_COOKIE_SECURE` 控制。
- `app/core/deps.py::get_current_user` 是业务路由统一门禁：无会话或用户不存在时，页面轨抛 `RedirectRequest`（303 → /login），API 轨抛 `AppError(401)`。
- **角色与管理员区（2026-11-19）**：`users.role ∈ {管理员, 普通用户}`，注册默认普通用户。`app/core/access.py::AdminGateMiddleware` 按路径前缀 `("/system", "/api/system")` 统一拦截（含该前缀下全部现有与新增路由）：未登录页面 303 → `/login`、API 401；停用账号按未登录处理并清会话；已登录非管理员页面渲染 `error.html` 403、API 返回 `{"code":"FORBIDDEN","error":...}` 403。
- **中间件顺序**：`SessionMiddleware` 必须在外层（`AdminGateMiddleware` 先 `add_middleware`），否则管理员门禁读不到已解析的会话；门禁内不能抛 `AppError`，需直接构造响应（全局异常处理器包不到中间件）。
- **管理员产生**：`scripts/migrate_role.py` 在库中无管理员时把启用账号中 `id` 最小者提升为管理员；应用启动时 `app/modules/auth/admin.py::ensure_admin_accounts` 幂等兜底（只升不降），`.env` 的 `ADMIN_USERNAMES`（逗号分隔登录名）可指定追加管理员。
- **单路由管理员依赖**：`app/core/deps.py::get_admin_user` 供前缀之外仍需要管理员权限的个别路由使用；`/system` 与 `/api/system` 本身由中间件兜底，不重复挂依赖。
- 侧栏「系统设置」分组仅管理员可见（`app/core/templating.py` 注入 `is_admin` 并过滤导航），属展示层处理，安全边界只认中间件。
- 三运动主表 `user_id` 为指向 users 的数据库外键；所有业务查询仍按登录用户过滤。

## 6. 异常体系（app/core/exceptions.py）

- `AppError(status, message)`：API 轨返回包含 `code`、`error` 的 JSON；页面轨渲染 `error.html`。
- `RedirectRequest(url)`：页面轨内部 303 重定向（如未登录跳登录页）。

## 7. 数据层设计与统一契约

- 全库 **28 张业务表**（详见《数据库建表设计.md》），DDL 见 `scripts/schema.sql`，幂等迁移脚本见 `scripts/migrate_*.py`；另有调度表 `scheduled_jobs` / `job_runs` 与 `langgraph` schema 4 张 checkpointer 框架表（后者由应用 setup 管理），合计 34 张表。技能三表与角色两表为 V2.4 新增；报告表 `reports` 为 V2.5 新增；建议表 `daily_advice` 为 V2.8 新增；档案表 `health_profile` 为健康/运动档案新增，技能定义与运行审计不再塞进 checkpointer。
- **中文注释元数据**：全量建表脚本在 `scripts/schema.sql` 中维护列注释；既有库由迁移脚本同步。
- **外键**：三运动主表与状态记录四表 `user_id` 引用 `users.id ON DELETE CASCADE`；动作与心得外键引用各自主表。其他业务表沿用原有归属策略。
- **派生值不落库**：BMI、配速、划频、趋势聚合、周期阶段、经期长度与周期长度均由 service 实时计算。
- **唯一约束支撑 upsert**：body 4 表按 `(user_id, record_date)` 唯一；`period_logs` 按 `(user_id, log_date)` 唯一；状态记录四表按 `(user_id, date)` 唯一（同类一天一行）。三运动同日可多条，按主表 id 定位。
- **统一两态**：健身/游泳/舞蹈均为 `status ∈ {planned, recorded}`；健身「完成训练」一键转 recorded；统计口径只计 recorded 行。
- **状态记录（非运动模块）**：`state_appetite_record` / `state_myalgia_record` / `state_inflammation_record` / `state_mood_record` 四表结构同构，不套统一运动契约（无计划态、起止时间、时长、心率、热量），字段仅 id/user_id/date/star(0~5 可空；0=最低分，null=未评)/remark/created_at/updated_at。跨表列表在 service 内存合并分页；月历阶段复用 `cycle.service.calendar_month` 推算结果并归并经期/卵泡·排卵/黄体三档，男性或无周期记录时阶段置空。接口前缀 `/api/state-record`：列表（分页 + type 筛选）、`/daily`、`/calendar`、新建、按 id 编辑（body 带 type）、`DELETE /{id}?type=`、`/batch-delete`（items 自带 type）。
- **账号状态与注销**：`users.status ∈ {启用, 停用}`，注册默认启用；登录和请求门禁拦截停用账号。`DELETE /api/profile/account` 要求当前密码，`retain` 停用并清会话，`purge` 在事务中删除用户及全部关联数据后清会话。停用账号通过注册页显式选择恢复、验证原密码后复用原 user_id。角色见第 5 节（管理员 / 普通用户，仅管理员可进 `/system` 与 `/api/system`）；仍无管理员重置他人密码或恢复停用账号的接口，管理员账号由迁移与启动保障产生。
- **健康/运动档案（profile）**：`health_profile` 是单表行式存储，`id` 为主键、`user_id` 普通外键 + 索引（一用户多行），每行一个固定 `aspect` 下的记录。`aspect` 只能来自 `app/modules/profile/aspects.py`（目标、饮食、日常运动、训练、睡眠、生活习惯、伤病、周期、心理、环境、偏好、其他），模型不能自创；`item_key` 用户内唯一，固定题用 `questions.py` 的 key，定制题用 `probe_<set_id>_<qN>`。固定题与定制题共用一张表，答案为空的行保留为未答项；`source` 区分 fixed / probe / user。固定题按 key 合并保存，空串删除行；定制题空串只清空答案；全部无有效答案时删除该用户全部行，页面回到问卷态。`completed_at` 不再存库，有效答案 ≥3 时按已答行派生。角色定制问题按 `set_id` 分组，最多 20 套；同签名更新最新套，问题变化新增一套并保留历史，页面/API 只展示最新一套。Agent 经 `get_profile_info` 读取固定档案、最新定制问答、全部历史定制问答与按 `aspect` 的覆盖统计；角色在对话中逐个调用 `ask_user` 单题提问，答完再问下一题，全部问完后确认并静默写入；保存成功后图进入 `finalize_probe_save` 固定结束，不自动开始下一套。角色段固定追加 `persona_health_profile_test_guard.v2`：以全貌基础画像为目标，至少覆盖 3 个 aspect、单 aspect 最多 2 题、周期与近期事件各最多 1 题、优先补覆盖少的方面，旧版本角色会话同样生效。文本不做结构化解析：每日训练建议只把它作为模型参考（不参与 `hard_limits` 硬约束）。
- **时长存秒、距离存米**，界面按分钟/米展示，派生展示值实时换算。

## 8. 关键业务口径（常量集中在 app/core/constants.py）

- 身材：4 组（basic/goal/girth/target）映射 4 表；新增记录未填字段沿用该维度最近一次非空值；趋势五档（week/month/two_month/half_year/year）窗口与锚点见常量（`TREND_RANGES`、`TWO_MONTH_SPAN_DAYS`）：week=本周 7 天、month=本月整月逐日、two_month=最近 60 天（含今天）逐日当日值、half_year=每月 1/10/20 号 11 天窗口均值、year=每月 1/15 号 16 天窗口均值；无记录为 null。
- 周期分段（2026-11-12）：`period_records` 只存起止日期；经期长度 = 结束 − 开始 + 1（未填结束日为 null），周期长度 = 下一条开始 − 本条开始（无下一条为 null），两者仅展示、不落库。阶段以「段」为唯一单元：段内排卵日 = 段长 − 14（黄体固定 14 天），排卵后 1~2 / 3~6 / 7~10 / 11~14 天依次为排卵后期 / 黄体前期 / 中期 / 后期。四档状态按阶段内日序判定（黄体中期前 2 天良好、余下一般；黄体后期前 2 天一般、余下休息；经期前 3 天休息、第 4 天一般、第 5 天起良好），疼痛 ≥2 覆盖为休息。
- 段长与预测：相邻首日间隔 < max(22, 参考周期 + 15) 拒绝保存；22~45 为真实段；46~90 判漏记，按参考周期等分补推（余数摊前几段）；>90 不补推并留白。只推最新记录后的当前段与一个预测段，再往后留白；逾期 7 天内仍标预测，超过转「未推算 + 建议补录」；0 条记录完全不推，1 条按参考值铺当前段 + 预测段。
- 阶段激素文案（2026-11-17）：`app/core/constants.py` 的 `PHASE_HORMONE` 为七阶段各备两份文案；阶段天数为 n 时，前 `floor(n/2)` 天用前段、剩余天数用后段（n=1 只用前段），由 `service.hormone_text_for` 按段内日序取用并随月历逐日返回 `hormone_text`。单份 ≤70 字，固定两句话各占一行：上行客观激素状态，下行对心情 / 食欲 / 运动表现的影响。详情页只保留「激素水平」，已移除「运动建议」；疼痛填写入口只在 recorded 经期（`period_state == recorded`）出现，推算经期与预测经期不展示入口。
- 周期日志（2026-11-17）：`period_logs` 按 `(user_id, log_date)` 一天一行；`pain_level` 可空且仅 recorded 经期可写，写入时同时归属 `period_id`（对应 `period_records.id`）；`note` 每天可写，数据来源与存储均为该表。非经期日写 note 时把 `pain_level` / `period_id` 置为 null；经期日写 note 保留已有疼痛并刷新归属。页面右侧详情下方新增「今日 note」小卡（固定今天，Ctrl/⌘+Enter 快捷保存）。
- 参考值与三态：`period_setting` 单行仅作参考值（周期 22~45 默认 28、经期 2~8 默认 5，且 经期 + 15 ≤ 周期），只服务当前段、预测段、补推段与未填结束日的记录，页面「周期参数」单独修改。period_state 三态：recorded（真实记录窗口）/ inferred（漏记补推段）/ predicted（未来段），月历以边框样式区分，详情注明推算来源。
- 周期颜色由 `app/static/css/tokens.css` 统一提供：月历单元格底色只按四档状态显示浅蓝绿、浅绿、浅黄、浅粉；窄屏仍显示两字状态名；周期静态资源带版本号以避免旧样式缓存。四档底色 2026-11-11 统一向白混合 50% 再浅一档（`--tag-*-bg`），对应圆点/文字深阶不变。
- 运动类型编码色同由 tokens.css 提供：`--ov-fit`（健身·灰）、`--ov-swim`（游泳·蓝）、`--ov-dance`（舞蹈·粉），日视图色条、图例圆点、汇总卡 chip 共用；chip 底色为 `--ov-fit-soft/--ov-swim-soft/--ov-dance-soft`（同基色独立透明度）。ECharts 读不到 CSS 变量，`app/static/js/overview.js` 的 `COLORS` 与 `body.js` 的图表配色一律通过 `App.cssVar('--令牌名')` 运行时读取，不再维护手工副本。
- 记录 / 计划态标记统一取 `--state-plan`（计划·蓝绿）与 `--state-record`（记录·深灰）：总览页列表圆点、chip 圆点，以及 `App.statusTag` 输出的「计划 / 记录」标签同一口径，不得各自取色。
- 字体与渲染：`base.css` 的 `html, body` 逐字照搬 GitHub 原栈（`-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"`）。原栈不含中文字体，中文与中文标点走浏览器默认兜底：本机默认中文即微软雅黑（实测与显式雅黑宽度仅差约 1.5%，肉眼无差），但若换到默认中文为宋体的环境会明显发灰变虚，届时须在 `sans-serif` 之前插入 `"PingFang SC", "Microsoft YaHei", "Noto Sans SC"`（通用族一出现，其后的字体即失效）。按钮/输入框显式 `font-family: inherit`；JSON 导入文本框保留等宽 `ui-monospace/monospace`（代码语义，不并入 UI 字体）。`html, body` 设置 `letter-spacing: .03em` 放宽字距（雅黑下中文偏挤显扁），局部需要更紧的文案可自行覆盖。同时不设置 `-webkit-font-smoothing: antialiased`：该值在 Windows 会关闭 ClearType 次像素抗锯齿，10~12px 小字会发虚。
- 配色规范：颜色唯一来源是 `app/static/css/tokens.css`。CSS 与 Jinja 模板一律用 `var(--令牌)`；**SVG 不能把 `var()` 写进 `fill` / `stroke` 属性**（presentation attribute 不解析变量），必须改写 `style="fill:var(--…)"`。JS / ECharts 用 `App.cssVar(name, fallback)`。
- 同值但语义不同、**禁止合并**的令牌对（合并会让两条业务线绑死）：`#6b7280` = 次要文字 / 记录态 / 健身编码；`#17b3a6` = 品牌强调 / 计划态；`rgba(23,179,166,.10)` = hover 浅底 / 计划标签底；`rgba(27,36,52,.08)` = 焦点环 / 轻投影；`rgba(107,114,128,.10)` = 中性标签底 / 健身 chip 底。要“当前同值、将来可分”，用 `var()` 别名而非删令牌。
- 总览：`/api/overview` 按 day/week/month 聚合，逐日 per-sport 计数 + 汇总卡 + 图表序列；健身时长优先 duration_s，缺失时按 recorded 的 end_time−start_time 推导，游泳/舞蹈= duration_s；热量按记录字段汇总。
- AI 运动报告（2026-11-17）：周报=周一~周日（`monday_of`），月报=自然月 1 日~月末；未结束周期 `period_end` 仍存周日/月末，事实截至 `as_of=min(end,today)` 并标 `partial`，未来周期禁止生成；进行中周期的环比只取上期同期天数（标「较上期同期」），不与整期直接比较。统计只计 `recorded`，计划单独计数；不做「计划完成率」（planned→recorded 原地改状态、无溯源）。热量沿用总览口径只汇总游泳+舞蹈，健身热量单列。事实快照 `facts` 存 JSON，`data_hash` = facts（剔除 `as_of`/`partial`）的 SHA-256，用于同周期过期检测；`narrative` 为结构化叙事，`evidence` 只能引用 `facts.metrics` 中真实存在的键，服务端二次过滤。生成状态机 `generating → ready/failed`，唯一约束 `(user_id, period_type, period_start)` 兜底并发；删除为软删除（`status=deleted`），扫描任务跳过 deleted，避免把用户删掉的报告重新生成；若报告是在周期未结束时生成的（快照 `facts.partial=true`），周期结束后扫描会带 `force` 重写，避免月报停留在半程数据。空数据周期走 `mode=rule` 规则文案，不调用模型。周期分析仅对 `gender != 男` 且存在月经记录的账号生成，真实/推算/预测分开统计，预测段不得当事实。自动生成由应用内调度器触发：`scheduled_jobs` 里 `report.weekly`（cron `0 8 * * mon`）生成上周周报、`report.monthly`（cron `0 8 1 * *`）生成上月月报，两者共用 `report.service.generate_due` 并靠 `ready`/软删除跳过保证幂等；错过执行窗口不补跑，用户在 `/system/scheduler` 页面手动执行或跑 `report.scan` 兜底。报告是非流式结构化调用，模型在整段 JSON 完成前不返回字节，长思考会顶满 60s 读超时，因此默认对 `qwen*` 关闭思考（`REPORT_ENABLE_THINKING=False`）；报告页 hero 只显示生成时间与操作，不展示模型名。
- 训练容量：Σ 重量 × 组数 × 每组个数首段数字（reps 为字符串，如 `"10+8+6"` 按 10 计），负荷任一为空跳过。
- 每日训练建议（2026-11-17，V2.8）：一天一条，`UNIQUE (user_id, advice_date)`，不设软删除。事实层全部由代码算：基础信息（性别/年龄）、身材快照与近 30 天体重差、昨日三运动、近 3/7 天负荷与部位分布、今天/昨天/近 3 天状态、当天计划、女性周期（仅 `gender != 男` 且有月经记录，真实/补推/预测分开标注）。只计 `recorded`，`planned` 只标计划。硬约束（今日疼痛 ≥2、周期四档=休息、炎症 ≤1、昨日容量 ≥8000 或时长 ≥120 分钟、昨日 ≥5000 或 ≥90 分钟、今日已练力量、情绪 ≤1）由代码判定并作为上限，模型输出后 `sanitize` 二次降档（强度 低<中<高、结论 休息<克制<适合），休息时方向改恢复并清空部位、力量被禁时降为有氧并清空部位、部位去重≤2 个、正文整理为三段要点（今日建议 ≤20 字、健身建议 ≤20 字、依据 ≤40 字，每行以「- 」开头、句末不带句号），最近 2 天练过的部位（`recent_load.recent_parts_2d`）不再安排。模型固定 `ai_default_model`，一次 `invoke_structured`，不查库、不调工具、不写会话；无任何记录走 `mode=rule` 固定文案不调模型。`00:01` 由 `advice.daily` 生成，`ready` 即跳过；启动后按 `advice_startup_catchup_seconds` 补跑当天缺失行（直接调 service，不写 `job_runs`）。当天新建计划不自动重算，只有侧栏刷新按钮（`force`，60 秒冷却）。要点正文并进 `.today-card`，占 `.d3` 与周期四档标签之间的位置，刷新图标在「今天」标题行右侧。
- 数值精度口径（2026-11-10 统一）：重量类字段 `weight_kg` / `target_weight_kg`（健身动作重量、身材体重/目标体重）统一 `numeric(10,2)`——任意数值、保留两位小数；Pydantic 不再设 `ge/le`，Excel/JSON 导入不做范围限值，前端 `step="0.01"` 且不设 `min`。仅组数保留 1~99 校验。

## 9. 导入导出

- **Excel**：body / training / swim / dance 均提供模板下载（`/template`）+ 导入（`/import`，openpyxl 解析、行级校验、错误明细回传）；body 另提供 `/export` 导出。Excel 列与校验规则集中在各模块 `excel_io.py`。
- **JSON**：training / swim / dance 提供 `/import-json`（字段校验、批量入库），逻辑在 `json_import.py`。
- **AI 导入**：三运动提供 `/ai-import`；具体输入约束、结构化校验、复用的落库链路和结果处理见 [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md)。
- 健身 Excel 新模板以 `(日期, 训练组编号)` 归属一条主表记录，组内各行是动作；不兼容旧模板。模板含「开始时间 / 结束时间」「平均心率 bpm / 最大心率 bpm / 热量 kcal」三列可选训练级字段，与备注同规则：同组多行取首个非空值；心率 1~300、热量 ≥0。JSON 导入的 plan 对象支持同名字段（`avg_heart_rate`/`max_heart_rate`/`calories`）。三处导入未填结束时间时 `end_time` 留空，不写当前时刻（2026-11-10）。

## 10. 前端组织

- 页面模板 `app/templates`：`base.html` 提供公共布局与 `#modalDetail` 详情弹窗；`layout/sidebar.html` 为分组导航（身材数据 / 状态记录 / 运动训练·计划[健身/游泳/舞蹈/报告] / 生理周期 / 个人信息 / 系统设置[定时任务]，男性账号隐藏周期入口；状态记录对男女开放，不做男性重定向）。
- `app/core/templating.py::render_page` 统一注入登录用户、导航高亮、面包屑、侧栏「今日」信息与常量；`today` 按请求取当天（`date.today()`），进程长跑跨天不会停留在启动日。侧栏「今日训练建议」以 `daily_advice` 轻量对象注入（一次索引查询，异常降级 `None` 不阻塞页面），卡片位于 `.today-card` 下方，收起侧栏时一并隐藏；`.sidebar-nav` 为 `flex:1 1 auto; min-height:0; overflow-y:auto`，避免小高度屏导航被卡片挤出。
- 静态资源 `app/static`：css（base/layout/pages/*）、js（common.js 共享弹窗与工具函数 + 各模块页面脚本）、vendor（echarts）、img。
- 三运动页顶部都有新建计划、新增记录、Excel/JSON/AI 导入（AI 弹窗为第三个面板：文字 + 图片 + 识别结果）；主体为当日、档案、全部记录三块。全部记录首列日期、次列类型、末列操作，含查看详情、编辑、删除及批量删除；健身全部记录列出类型/备注/时长/动作/容量（备注列 2026-11-10 由「训练内容」替换，训练内容仍在详情展示）。共用双栏使用可收缩网格列，宽表在卡片内部横向滚动；健身动作表和编辑动作区单独滚动。
- 生理周期页 `/cycle`：左列月历 + 「全部记录」，右列当日详情（激素文案固定两行、疼痛仅 recorded 经期可填、周期概览）与「今日 note」小卡；「全部记录」用分段控件在月经记录 / 周期日志两段切换，均为表格 + 分页，日志行展示日期、疼痛、所属经期与 note，详情复用公共 `#modalDetail`。note 固定今天，读写 `period_logs.note`，非经期日保存时同时清空疼痛等级与 `period_id`。页级脚本 `app/static/js/cycle.js`，样式 `css/pages/cycle.css`。
- 状态记录页 `/state-record`：三卡片自上而下纵向堆叠（`three-row-stack`，内容随卡片宽度自适应铺满），依次为月历（阶段三档圆点 + 有记录标记，翻月/选日联动）、「当日状态」四类块（食欲/肌肉疼痛/炎症/情绪）就地填写——每块内联星级（五星 + 「0」最低分按钮，未评存空）+ 描述 + 保存，有记录时块内可删除，不再弹新增表单、「全部记录」列表（类型分段筛选 + 勾选跨表批量删除 + 分页，操作列查看详情/编辑/删除，行内「编辑」才弹出表单弹窗）。类型标签：食欲橙 / 肌肉疼痛灰 / 炎症红 / 情绪紫。详情复用公共 `#modalDetail`；无 Excel/JSON/AI 导入入口。页级脚本 `app/static/js/state_record.js`，页级样式 `css/pages/state_record.css`。
- 总览页周期切换（2026-11-08）：顶部 `‹ ›` 按当前视图步进锚点并重拉 `/api/overview`（日 ±1 天、周 ±7 天、月 ±1 月；跨月在目标月把日号夹到最后一天，如 1/31 → 2/28）。右上标签显示当前区间（日=`月日 周几`、周=`起止月日`、月=`年月`，跨年补年份），区间不含今天时显示「回到今天」。周视图每日卡在周几右侧带灰色「月/日」（`11/2`）。切视图不改锚点，`?mode=&date=` 始终同步；「今天」取浏览器本地日期，不依赖服务端启动日。
- 弹窗多行文本框自适应（2026-11-10）：`base.css` 给 `.modal textarea` 统一 `resize:none`、`overflow-y:auto`、`max-height:min(300px,42vh)`；`common.js` 的 `autoGrowTextareas` 以 `rows` 撑起的初始高度为下限、CSS `max-height` 为上限，在输入（含中文输入法组字结束）、弹窗打开、弹窗内动态插入条目时重算高度。个别字段用更具体的 `max-height` 收窄上限（如总览单日详情备注框 84px）。新增弹窗无需额外代码，只要把多行输入用 `textarea` 写进 `.modal`。
- 个人信息：侧栏「个人信息」为分组，子项「账号资料」（`/profile`）与「健康/运动档案」（`/profile/health-profile`）。账号资料页保持左栏只读概览 + 右栏基本资料/修改密码；健康/运动档案页未填写时直接展示问卷（按「目标与节奏 / 训练方式与条件 / 习惯与限制」三组卡片逐题文本框），已填写时展示只读答案卡，提供「编辑档案 / 清空档案」，编辑态可「清空重写」；存在「健康档案测试」生成的定制问题时，只读态与编辑态都追加「定制问题」卡片（只展示最新一套，带生成时间）。保存为合并语义（未传的题保留、空串清空），全部清空即删除该用户档案行回到问卷态。固定题 key 与文案由 `app/modules/profile/questions.py` 单一维护，固定题 aspect 映射与全量模板由 `app/modules/profile/aspects.py` 维护，定制问题由 `app/modules/profile/probe.py` 管理；数据库已改为一行一条的 `health_profile` 行式表，页面仍通过 service 聚合出的 `answers` 与最新一套问题渲染；页级脚本 `health_profile.js`、样式 `pages/health_profile.css`。
- AI 助手页 `/agent`：提供多会话、多轮问答、工具/技能调用和 SSE 流式交互；生成中发送按钮切换为停止按钮，可随时中断，中断后可就地「继续」续写；顶部「新建会话」与「新建角色会话」，后者点击弹出角色选择弹窗，创建后整段会话固定该角色、不可切换，侧栏会话显示「人形图标 + 角色名」徽标；输入框支持 `/技能名 自然语言`，输入 `/` 会浮出可用技能建议并支持键盘选择；输入框底行左端是「联网」开关（默认关闭，开启后本轮才可检索外部网页，未配置密钥时置灰）；详细页面交互、事件协议和工具状态展示见 [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md)。
- 技能管理页 `/agent/skills`：整页白底铺满、左侧平台/我的技能列表 + 右侧编辑区；用户技能只提供提示词文本域，平台代码/声明式技能只读展示；校验/保存/发布/停用/删除/试运行/运行记录；平台技能只读。页面挂在侧栏「AI助手」分组下，`active=agent_skills`。
- 角色管理页 `/agent/personas`：挂在侧栏「AI助手 → 角色管理」（`active=agent_personas`），布局与技能页一致；左侧平台角色（营养师/电子私教/健康档案测试）与我的角色，右侧角色名、角色键、定位与提示词编辑区；平台角色普通用户只读，用户角色保存即生成新版本并生效，支持启停与删除（被会话引用时提示先删会话）。
- 内置角色管理页 `/system/personas`：挂在侧栏「系统设置 → 内置角色」（`active=system_personas`），仅管理员可见；左侧内置角色列表，右侧角色名/键/排序/状态/提示词编辑，以及按只读、交互、写入分组的工具勾选和按代码/声明式分组的平台技能勾选。支持新建、保存、删除、恢复默认范围；被会话引用删除返回 409。页级脚本 `app/static/js/system_personas.js`，样式 `css/pages/system_personas.css`，模板 `app/templates/system/personas.html`。
- 内置技能管理页 `/system/skills`：挂在侧栏「系统设置 → 内置技能」（`active=system_skills`），仅管理员可见；左侧代码/声明式技能分组，右侧技能名/键/别名/分类/状态/能力描述与定义编辑。代码技能定义只读、仅可启停；声明式技能可新建、编辑、版本化保存、校验、试运行、启停与删除；被内置角色显式白名单引用时删除返回 409。保存/启停/删除后重建常驻系统图并清空按用户图缓存，立即生效。页级脚本 `app/static/js/system_skills.js`，样式 `css/pages/system_skills.css`，模板 `app/templates/system/skills.html`。
- 报告页 `/reports`：周报/月报单页（`?type=weekly|monthly&anchor=YYYY-MM-DD`），侧栏「运动训练/计划」第四项；顶部周期步进 + 进行中标记 + 生成/重新生成；4 张事实卡 → 叙事（亮点/留意/建议/周期视角/数据说明）→ 判断依据（运动/身体/状态/周期/完整度）→ 历史报告（软删除）。总览页顶部提供「周报」「月报」入口。页级脚本 `app/static/js/report.js`，样式 `css/pages/report.css`。
- 定时任务页 `/system/scheduler`：挂在侧栏「系统设置」分组下（`active=scheduler`）；任务卡列表（任务名与说明、表达式中文化、下次执行、上次结果与累计次数、启用状态）+ 新建/编辑弹窗（触发类型 cron/interval/date、表达式、时区、参数）+ 执行历史（时间/来源/结果/耗时/摘要，分页）；卡片操作「立即执行 / 编辑 / 停用启用 / 删除」。页级脚本 `app/static/js/system_scheduler.js`，样式 `css/pages/system_scheduler.css`，模板 `app/templates/system/scheduler.html`。

## 专项规范索引

前端规范见 [FRONTEND_GUIDELINES.md](FRONTEND_GUIDELINES.md)。
运动模块规范见 [SPORT_MODULE_GUIDELINES.md](SPORT_MODULE_GUIDELINES.md)。

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
│  │  ├─ state_record/ # 状态记录：食欲/肌肉疼痛/炎症/情绪四表 CRUD + 月历阶段归并
│  │  ├─ report/       # AI 运动报告：reports 表 + 事实快照 + 叙事 + 自动生成
│  │  ├─ daily_advice/ # 侧栏每日训练建议：facts + sanitize + service + /api/daily-advice
│  │  ├─ system/       # 系统管理区：聚合 /system 页面与 /api/system API；scheduler/ 定时任务、personas/ 内置角色、skills/ 内置技能
│  │  └─ agent/        # AI 助手：LangGraph 图 + checkpointer + 会话/SSE + skills 技能子系统
│  ├─ templates/       # Jinja2 页面
│  └─ static/          # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py       # 建表 + 初始化账号（幂等）
│  ├─ migrate_*.py     # 2026-10/11 增量迁移（幂等，可重复执行）
│  └─ schema.sql       # 全量建表 DDL（与《数据库建表设计.md》一致，含中文 COMMENT 段）
└─ tests/              # pytest 单元测试
```

## 12. 测试与运维

- 单元测试：`pytest tests/ -q`（趋势聚合、配速划频、周期阶段、训练状态机、个人信息、总览聚合、状态记录四表 CRUD/合并分页/跨表批量删除、报告周期归一/事实快照/生成/软删除/扫描/evidence 校验、每日建议事实/硬约束/清洗/生成状态机/扫描/任务表达式、内置技能的声明式 CRUD/版本/代码只读/引用保护/试运行等）。
- 建库/初始化：`python scripts/init_db.py`（幂等）；结构迁移按需执行 `scripts/migrate_*.py`；报告表迁移 `python scripts/migrate_reports.py`，建议表迁移 `python scripts/migrate_daily_advice.py`。
- 报告自动生成：应用内调度器按 cron 触发（`report.weekly` 周一 08:00、`report.monthly` 每月 1 日 08:00，时区 Asia/Shanghai）；管理页 `/system/scheduler` 可改表达式、启停与立即执行；日志 `logs/scheduler.log`（命令行补跑）与 `job_runs` 表（所有触发来源）；`python scripts/generate_reports.py --scan --dry-run` 只列到期周期，`--type/--anchor/--user` 可手动生成单个周期。
- 启动：`python main.py`（推荐；Windows 下 psycopg3 异步要求 SelectorEventLoop，命令行 `uvicorn main:app` 会在 import 本模块前用默认 ProactorEventLoop 建好 loop、导致启动失败，main.py 已内置显式 selector loop 的编程式启动）。
- 依赖：`uv sync --extra dev` 或 `pip install -r requirements.txt`。

## 13. 应用内定时任务（V2.7，2026-11-17）

- **位置**：`app/modules/system/scheduler/`（`models` / `schemas` / `triggers` / `registry` / `runner` / `engine` / `service` / 两个 router），`main.py` 的 lifespan 内启停。替代原「Windows 任务计划程序每 30 分钟跑一次 CLI」的方案，`scripts/register_report_task.ps1` 已移除。
- **三种触发**：`cron`（标准五段式「分 时 日 月 星期」）、`date`（某时刻只跑一次，必须晚于当前时间）、`interval`（`30s`/`10m`/`2h`/`1d`，最小 60 秒）。cron 的星期字段**只接受 mon~sun 英文缩写**：APScheduler 的 `day_of_week` 以 0=周一，与 crontab 的 0=周日 差一位，数字写法会被静默错一天，因此 `triggers.parse_trigger` 直接拒绝数字。
- **唯一事实源**：任务定义存 `scheduled_jobs`，内存作业不持久化。启动时 `service.bootstrap()` 先 `seed_defaults`（注册表里带默认排期的任务，库里没有就补一条，幂等），再 `reconcile()` 按表全量重建内存作业并移除已不存在的作业。不使用 APScheduler 自带的 `SQLAlchemyJobStore`，避免 job store 与业务表两套状态互相覆盖。
- **不存 callable**：库里只存 `job_key` 与表达式，执行时由 `registry.REGISTRY` 查到函数；重构函数名、挪模块都不会让已存任务失效。参数由注册表的 pydantic schema 校验（`extra=forbid`），页面不能传任意字段。
- **错过不补**：`misfire_grace_time` 默认 300 秒（`SCHEDULER_MISFIRE_GRACE_SECONDS`），超时触发由 `EVENT_JOB_MISSED` 记为 `job_runs.status=skipped`，任务状态同步为 skipped；补跑由用户在 `/system/scheduler` 点「立即执行」，不自动重试。
- **互斥**：`runner.run_task` 用 PostgreSQL advisory lock `pg_try_advisory_lock(hashtext(lock_scope))` 串行化同域任务；三条报告任务共用 `lock_scope="report"`，周报、月报、兜底扫描不会同时生成。演示/测试环境（非 PostgreSQL）自动跳锁。
- **执行记录**：定时触发、页面手动、命令行三个来源都写入 `job_runs`（来源、状态、耗时、摘要、明细），并回写 `scheduled_jobs` 的 `last_run_at / last_status / last_duration_ms / run_count`。异常在 `run_task` 内收敛为 `failed`，不抛回调度线程。
- **报表接入**：`report.service.generate_due(db, period_types=...)` 是调度器与 CLI 的共用入口，内部复用 `scan_due` 的幂等判断（已 `ready`、软删除、`attempts` 超限、注册前周期、进行中报告到期重写）。默认任务：`report.weekly`（`0 8 * * mon`）、`report.monthly`（`0 8 1 * *`）；`report.scan` 不排期，供页面/CLI 手动兜底（忽略 `report_auto_enabled`）。
- **每日建议接入（V2.8）**：`advice.daily`（cron `1 0 * * *`，`lock_scope="advice"`，`EmptyParams`）调 `daily_advice.service.generate_due`，跳过已 `ready`、`failed` 达 `advice_max_attempts`、生成中未超 5 分钟的卡死行；`advice.scan` 不排期，供手动补跑（忽略 `advice_auto_enabled`）。启动补跑是「错过不补」的显式例外：`engine.start_scheduler()` 在 `bootstrap()` 后用内存一次性 `date` 触发器（`now + advice_startup_catchup_seconds`）调 `generate_due`，不经过 `run_task`，因此不写 `job_runs`；作业 id `advice-catchup` 不在注册表，`pk_of` 返回 `None`，事件自动忽略。
- **页面与接口**：`/system/scheduler`（侧栏「系统设置」分组下的「定时任务」）任务卡列表 + 新建/编辑弹窗 + 执行历史；API 见 `docs/API_REFERENCE.md` 第 15 节。任务表是实例级配置，不挂 `user_id`：任务对所有启用账号生效，归属口径在各业务函数内部（如报告只处理 `status=启用` 的用户）。
- **部署约束**：调度器在进程内，只在单进程成立。`uvicorn --workers > 1` 或多实例部署会重复注册作业，此时要么单独跑一个调度进程，要么依赖 advisory lock + 业务幂等兜底；不要用多 worker 跑同一套定时任务。
- **旧方案卸载**：若某台机器仍注册过系统计划任务，执行 `Unregister-ScheduledTask -TaskName "SH-Report-Auto" -Confirm:$false` 卸载，注册脚本已随本次改动删除。

