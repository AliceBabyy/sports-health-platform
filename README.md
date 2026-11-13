# 体序 BODY ALMANAC · 个人健康管理平台（V1）

## V2.0 AI 基础骨架

V2 路线以 `docs/AIplan.md` 为准。已完成模型骨架、三运动的一次性 AI 导入、
**V2.2 基础问答**与 **V2.3 数据问答**。Agent 独立模块 `app/modules/agent/`，页面
`/agent`、API `/api/agent`，基于 LangGraph `StateGraph` + `AsyncPostgresSaver`
checkpointer，支持多会话、多轮对话、SSE 流式与 PostgreSQL 持久化、登录用户隔离。
V2.3 把图升级为工具循环（`agent ⇄ tools`），模型按需调用 8 个**只读工具**查询现有
业务表后基于事实回答，不新建表、不写数据。后续依次建设 Skill 管理与多角色智能体
（V2.4）、LangGraph Store 跨会话画像（V2.5）和暂停追问后恢复（V2.6），这些尚未实现。

AI 基础设施已接入 LangChain 与 OpenAI 兼容协议，当前注册
`deepseek-v4.1-flash`、`qwen3.8-flash`、`qwen3.8-2.4t-a95b`、`qwen3-vl-plus`。
四个模型共用 `AI_API_KEY` 和 `AI_BASE_URL`，默认模型由
`AI_DEFAULT_MODEL` 选择。示例见 `.env.example`；真实密钥仅放在被 Git 忽略的
`.env`。统一使用 `/compatible-mode/v1`；`/api/v1` 是原生接口地址，
不能直接作为 OpenAI 兼容客户端的 `base_url`。

`app/ai/models/` 管模型注册，`app/ai/prompts/` 管版本化文件提示词，
`app/ai/runtime/` 管调用和结构化校验，`app/ai/tools/` 预留外部工具适配入口
（Agent 的只读业务工具在 `app/modules/agent/tools/`）。
受登录保护的 `GET /api/electronic-trainer/models` 返回已注册模型；
`POST /api/electronic-trainer/probe` 接收 `{"model": "...", "text": "..."}`
并验证结构化输出。这两个旧命名接口仅用于 V2.0 连接验证，
不读取运动数据，也不写库；不作为未来 Agent 主功能的路由约定。
视觉能力只对 `qwen3-vl-plus` 声明（2026-11-10 实测通过）；四个模型的工具调用
（function calling）已于 2026-11-13 实测通过，capabilities 均含 `tools`。

**AI 导入（2026-11-10）**：健身、游泳、舞蹈三页顶部均有「✦ AI 导入」入口。
用户填一段文字、可选多张图片（最多 3 张、单张 ≤ 2MB），后端用
`with_structured_output(输出模型, method="json_schema", strict=True)` 在解码期强制
输出结构，纯文字默认 `qwen3.8-flash`、带图默认 `qwen3-vl-plus`（可用
`AI_IMPORT_MODEL` / `AI_IMPORT_VISION_MODEL` 调整）。识别结果经规范化后复用各模块
`json_import` 的校验与落库函数，导入数据统一为 `recorded`；全程不反向调用
`/import-json`。接口为 `POST /api/training/ai-import`、`/api/swim-records/ai-import`、
`/api/dance-records/ai-import`（multipart：`prompt` + `images`）。前端一次完成，
结果就地展示，可「撤销本次导入」（批量删除本次新建记录），校验失败时可一键回填到
JSON 面板手动修正。

**V2.2 基础问答（2026-11-12）**：侧栏末项「AI助手」进入 `/agent`。会话元数据存
`agent_conversations` 表（用户归属、标题、uuid `thread_id`、模型、`last_message_at`）；
消息不建消息表，由 checkpointer 在独立 `langgraph` schema 的框架表（checkpoints /
checkpoint_blobs / checkpoint_writes / checkpoint_migrations）承载，应用启动 lifespan
建池并 `setup()`，按 `thread_id` 自动重放。回复走 SSE 流式（`start/delta/done/error`），
前端 `fetch` + `ReadableStream` 解析；`trim_messages` 用 `token_counter=len` 按消息条数
（上限 20）裁剪上下文；会话硬删除、历史永久保留、首条消息前 12 字自动标题、会话级模型
下拉。checkpointer 用 psycopg3 异步，ORM 仍用 psycopg2；Windows 下启动前切换
`WindowsSelectorEventLoopPolicy`。2026-11-13 前端改版：整页白底无卡片、会话侧栏细线分隔且可
收起，空会话居中欢迎页与输入框，进入页面默认新会话（首条消息发送时才惰性建会话）。

**V2.3 数据问答（2026-11-13；2026-11-14 覆盖全部模块）**：图从线性单节点升级为工具循环——
`START → agent ⇄ tools → END`，`agent` 用 `bind_tools` 后的模型，条件边按 `tool_calls` 决定进
`ToolNode` 还是结束，`recursion_limit=10` 防无限循环。工具集中在 `app/modules/agent/tools/`，
按业务域注册 8 个只读工具：`get_workout_summary`（跨三运动汇总，复用 overview 口径）、
`get_fitness_records`（健身明细含动作与容量）、`get_swim_records`（游泳明细含配速/划频）、
`get_dance_records`（舞蹈明细）、`get_body_measurements`（身材 4 组，`metric=all` 取整表或单指标趋势，
未测量日期不补值）、`get_state_records`（食欲/肌肉疼痛/炎症）、`get_cycle_records`
（参考值 + 月经记录 + 每日疼痛 + 今日阶段）、`get_profile_info`（昵称/性别/年龄，不含密码）。
取数范围由模型按用户意图决定：`days_back`、`start_date + end_date`、`limit` 均可选，
**不传任何范围参数即取全部历史**，已移除原 366 天 / 20 条硬上限；一次拉全量或只拉最近几次
都由意图决定。`user_id` 经 `RunnableConfig` 服务端注入、模型不可填，工具内部用独立短 session；
工具全部只读、不接受模型 SQL，参数只保留日期范围、条数与枚举。SSE 新增
`tool_start/tool_result`（`stream_mode=["messages","updates"]`），气泡显示“正在查询…“，
回答为汇总 + 关键依据、明细折叠（最多渲染 50 行）。本版无数据库结构变更、不引入 Redis/pgvector。

安装依赖：`uv sync --extra dev`。

SSR 单体应用：**FastAPI + Jinja2 + SQLAlchemy + PostgreSQL**，端口 **8010**（避开 8000）。

V1 范围：注册/登录认证 + 模块（身材数据 BD / 状态记录 SR / 健身训练 TR / 游泳 SW / 舞蹈 DA / 生理周期 MC / 个人信息 PR）。

账号注销：个人信息页可退出登录，或在输入当前密码后选择“注销但保留数据”（users.status=停用，禁止登录）和“注销并清除所有数据”（删除用户及所有关联记录）。停用账号可在注册页勾选恢复并凭同名账号、原密码恢复原 user_id 和数据。当前无管理员角色或管理员接口；管理员恢复需通过受控数据库操作。现有库运行 `python scripts/migrate_user_status.py` 增加状态列。
严格按《个人健康管理平台开发需求文档》V1 + UI 设计图 + 技术栈实现。

> 2026-11 改版：**运动训练/计划统一「计划/记录」两态 + 跨运动总览（日/周/月）+ 单日详情跳转**。
> - 侧边栏改为分组结构：身材数据 / 运动训练·计划（健身、游泳、舞蹈）/ 生理周期 / 个人信息；
>   总览页 `/overview` 取代原「本周/本月一览」占位菜单。
> - 数据层：三运动统一 `{sport}_records` 主表与 `{sport}_notes` 心得表，必备列和外键见
>   [`数据库建表设计.md`](docs/数据库建表设计.md)。健身另有 `training_records_items` 动作明细。现有库运行
>   `scripts/migrate_sport_contract.py`，迁移保留原有数据与模块专属字段。
> - 接口：新增 `GET /api/overview?granularity=day|week|month&date=`（跨运动聚合）与
>   `GET /api/overview/day?date=`（单日详情）；swim/dance 新增 `GET /api/swim-records|dance-records/daily?date=`；
>   健身接口统一挂在 `/api/training`；三运动均提供列表、单日、增改删、批量删除、心得及导入接口。
> - 总览布局（2026-11-03）：日视图顶部仅保留「训练计划」卡，运动次数/时长并入底部「当日运动情况」；
>   周/月视图「每日运动」卡片置顶并加高、每条标签含时长，顶部聚合收敛为「运动次数+运动时长」并与
>   「每日运动时长」图合并为「运动情况」卡（月视图图表按每日粒度，labels=日号）；消耗估算卡已移除。
> - 总览三视图整改（2026-11-04）：周/月每日卡每条计划/记录独立标签（不再合并计数）、remark 显示在
>   标签内部、圆点按类型着色（计划=蓝绿 `#17b3a6`、记录=深灰 `#6b7280`）；日视图三运动卡各占一行
>   全宽、用 4px 小色条标识（禁大面积背景色）、完整展示计划内容（逐动作明细/距离/时长/热量等）；
>   当日详情弹窗内置每条 remark 编辑框，可直接保存并联动刷新。
> - 三运动页「全部记录」查看详情（2026-11-04）：健身/游泳/舞蹈「全部记录」卡片操作列统一新增
>   「查看详情」按钮，点击弹窗展示该条完整信息——健身含动作明细表（动作/部位/重量/组数/次数/目标
>   重量）+ 容量/心得，游泳与舞蹈展示全部字段（含时段与时长，字段无值显示 —，计划态同）；
>   心得区块仅记录态且确有内容才展示；共用公共
>   弹窗（base.html `#modalDetail`）与 `App.openDetail(kind, row)`（common.js），数据直接取行内
>   全量 JSON，无需额外请求。
> - 练后庆祝 + 心得（2026-11-04）：三运动完成训练记录后统一弹「恭喜完成训练，又是自律的一天！」
>   彩带庆祝弹窗，按钮为「记录心得」/「👏」；导入全部成功同样庆祝，仅恰好导入 1 条才显示心得按钮，
>   多条只庆祝、部分失败走原明细流程。新增 `training_notes` 四字段（自我评估星/最佳动作/复盘反思/
>   下一步想法）与全新 `swim_notes`、`dance_notes`；列表只显示星级，编辑「记录态」时弹窗内联心得区块
>   一并保存，历史记录可随时点「心得」补写。
> - 总览周期切换（2026-11-08）：页面右上 `‹ ›` 按视图切换前后周期（日 ±1 天、周 ±7 天、月 ±1 月，
>   跨月把日号夹到目标月最后一天），`‹` 与 `›` 之间的标签显示当前区间（日=`11月7日 周六`、
>   周=`11月2日 – 11月8日`、月=`2026年11月`），区间不含今天时多出「回到今天」；周视图
>   「每日运动」卡每天在周几旁加灰色「月/日」（如 `周一 11/2`）。卡片标题去掉「本周/本月」前缀，
>   周期统一由顶部标签表达。另修正 `render_page` 的 `today` 按请求取当天（原先取启动日，
>   服务长跑跨天会把「今天」停留在旧日期）。
> - 健身列表列与心率/热量（2026-11-10）：健身「全部记录」第三列由「训练内容」替换为「备注」
>   （接口响应字段不变，训练内容仍在查看详情展示）；主表 `avg_heart_rate`/`max_heart_rate`/`calories`
>   三列打通四入口——Excel 模板新增「平均心率 bpm / 最大心率 bpm / 热量 kcal」、JSON 导入新增同名字段、
>   新建/编辑弹窗新增三项输入（计划/记录均可填、可空）、详情弹窗展示三项（无值显示 —）。
>   校验口径：心率 1~300 整数、热量 ≥0；`create_plan`/`update_plan` 不再按状态限制写入。

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
.\.venv\Scripts\python.exe main.py
```

> Windows 下 psycopg3 异步要求 SelectorEventLoop，直接用 `python -m uvicorn main:app`
> 会在导入前用 ProactorEventLoop 建 loop 导致启动失败；`main.py` 已内置显式 selector loop。

浏览器打开 http://127.0.0.1:8010，使用 **admin / admin123** 登录；或点击登录页下方
「注册新账号」自助注册（用户名/密码 + 昵称/性别/年龄；身高稍后在「身材数据」中记录）。

### 5. 测试

```powershell
# 单元测试（趋势聚合 / 配速划频 / 周期阶段 / 训练状态机 / 总览聚合 / 个人信息 / Excel 导入 / 状态记录）
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

> 端到端冒烟脚本 `scripts/smoke_test.py` 已随项目整理移除（2026-11-04），功能验收由浏览器抽查 + 单测覆盖。

## 目录结构

```
sports-health-platform/
├─ main.py                 # 入口：SessionMiddleware、路由装配、端口取 .env
├─ config.py               # pydantic-settings 配置
├─ database.py             # SQLAlchemy 引擎 / SessionLocal / Base
├─ models_registry.py      # 全部模型集中注册（建表入口）
├─ app/
│  ├─ core/                # 公共认证、错误、分页、运动契约与操作
│  ├─ modules/
│  │  ├─ auth/             # 登录/注册/登出/会话（users 表含性别年龄）
│  │  ├─ body/             # 身材数据：4 表拆分 upsert + 未填继承 + 四档趋势 + BMI + 剪影 + Excel 导入/导出
│  │  ├─ training/         # 训练计划（「完成训练」一键转记录）/历史 + Excel/JSON 导入
│  │  ├─ swim/             # 游泳记录/计划 + 配速/划频计算 + 单日视图 + Excel/JSON 导入
│  │  ├─ dance/            # 舞蹈记录/计划 + 舞种汇总 + 单日视图 + Excel/JSON 导入
│  │  ├─ overview/         # 运动训练/计划总览：日/周/月聚合 + 单日详情（2026-11 新增）
│  │  ├─ cycle/            # 生理周期：七阶段推算 + 月历 + 疼痛 + 运动等级
│  │  ├─ state_record/      # 状态记录：食欲/肌肉疼痛/炎症三表按天记录 + 月历阶段归并 + 跨表批量删除
│  │  ├─ profile/          # 个人信息：基本资料（昵称/性别/年龄）+ 修改密码（复用 users 表）
│  │  └─ agent/            # AI 助手：LangGraph 图 + checkpointer 生命周期 + 会话 service/SSE（页面 /agent）
│  ├─ templates/           # Jinja2（base/侧栏/七模块页面 + auth/register + profile）
│  ├─ static/              # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py           # 建表 + 账号幂等
│  ├─ migrate_training_multi_plan.py  # 2026-11：训练一日多计划（删唯一约束、加联合索引，幂等）
│  ├─ migrate_sport_contract.py # 三运动统一表、字段、外键（幂等）
│  ├─ migrate_plan_status.py  # 2026-11：swim/dance 加 status、记录列转可空（幂等）
│  ├─ migrate_remark.py       # 2026-11：三表加 remark、swim/dance 移除 plan_text（幂等）
│  ├─ migrate_notes.py        # 2026-11：training_notes 扩四字段心得 + 新建 swim_notes/dance_notes
│  ├─ migrate_swim_avg_stroke_rate.py # 2026-11：swim_records 加 avg_stroke_rate（幂等）
│  ├─ migrate_state_record.py   # 2026-11：状态记录三表（食欲/肌肉疼痛/炎症）建表 + 注释（幂等）
│  └─ schema.sql           # 全量建表 DDL（整改后结构，含中文 COMMENT 段）
└─ tests/                  # pytest 单测（含运动契约与总览聚合）
```

## 需求口径（锁定实现）

- 配速 pace = duration_s ÷ distance_m × 100 ÷ 60，保留 1 位；划频 = total_strokes ÷ (duration_s ÷ 60)
- BMI = 体重kg ÷ 身高m²，健康区间 18.5~23.9
- 身材数据为 4 张拆分表（基础/期望/围度/目标围度），每表 (user_id, record_date) 唯一；
  页面默认显示记录日期最新一条；4 个分类添加按钮分别写入对应表；
  新增记录未填字段自动沿用该字段最近一次非空值；同日同组重复保存只覆盖当日已提交字段
- 趋势四档：week=本周周一~周日 7 点当日值；month=本月每日；half_year=近 6 个月每月 1/10/20 号、窗口 [锚点-10 天,锚点] 11 天均值；year=近 12 个月每月 1/15 号、窗口 [锚点-15 天,锚点] 16 天均值；无记录断线不插值；基础+围度 11 维可趋势，目标值不参与
- 训练负荷宽松化：动作名称必填，部位/重量/组数/每组个数可空；每组个数为字符串（如 "10+8+6"），容量 = Σ 重量×组数×个数首段数字；期望突破重量计划/记录均可填；重量与目标重量（含身材体重/目标体重）取任意数值、保留两位小数，不做范围限值（仅组数 1~99）
- 新运动模块的统一必填项：计划态和记录态均需日期；其他必填业务字段及默认展示以 [`SPORT_MODULE_GUIDELINES.md`](docs/SPORT_MODULE_GUIDELINES.md) 的需求确认清单为准，现有三模块规则不直接套用于新模块。
- 三运动页共用可收缩双栏；表格宽于卡片时只在表格区域横向滚动，健身动作表和编辑弹窗的动作字段同样如此。
- 弹窗填写框（2026-11-10 统一）：所有弹窗内的多行文本框随内容行数自动增高，初始高度由 `rows` 决定，长到 `min(300px, 42vh)` 后在框内滚动；删空内容会缩回初始高度。实现见 `app/static/js/common.js` 的 `autoGrowTextareas` 与 `app/static/css/base.css` 的 `.modal textarea`。
- 七阶段（2026-11-12 分段推算）：月经记录只存起止日期——经期长度 = 结束日 − 开始日 + 1（未填结束日为 null），周期长度 = 下一条记录开始日 − 本条开始日（无下一条为 null），两个值均实时派生、不落库；阶段以「段」为唯一计算单元，段内排卵日 = 段长 − 14（黄体固定 14 天），卵泡期随段长伸缩；排卵后 1~2 天排卵后期、3~6 天黄体前期、7~10 天黄体中期、11~14 天黄体后期
- 运动四档：排卵期前期/排卵日/排卵后期为精力旺盛；黄体前期及黄体中期前 2 天为状态良好；黄体中期余下日期及黄体后期前 2 天为状态一般；黄体后期余下日期及经期前 3 天为适合休息；经期第 4 天状态一般、第 5 天起状态良好。疼痛 ≥2 优先覆盖为适合休息
- 段长规则：相邻首日间隔 < max(22, 参考周期 + 15) 拒绝保存并提示疑似同一次月经；22~45 天为真实段；46~90 天判为漏记，按参考周期等分成 k 段补推（k 取使每段最接近参考周期且落在技术下限~45，余数摊到前面几段）；>90 天不补推，两段之间留白并提示漏记超过 3 个月
- 预测边界：只推最新记录后的当前段与一个预测段，再往后留白；最新段逾期 7 天内仍标「预测经期」，超过 7 天转「未推算 + 建议补录」；0 条记录完全不推，1 条记录按参考值铺当前段 + 预测段
- 周期参考值：`cycle_settings` 单行，只用于当前段、预测段、补推段和未填结束日的记录；参考周期 22~45（默认 28）、参考经期 2~8（默认 5），且需满足 经期 + 15 ≤ 参考周期；页面「周期参数」按钮单独修改，记录变动不再改写它
- 经期三态：recorded 经期（真实记录窗口）、inferred 推算经期（漏记补推段）、predicted 预测经期（未来段），月历以边框样式区分，详情注明「本段无记录，阶段按参考周期推算」
- 周期页面：月历标识真实记录首日，可新增、编辑、删除月经记录（表单只收起止日期）；四档疼痛独立记录，保存后同步刷新运动等级；侧栏「今日」小卡保留，今天无段显示「未推算」；三运动页周期联动已移除
- 字体与渲染（2026-11-11）：全局字体逐字照搬 GitHub 原栈（`-apple-system → Segoe UI → Noto Sans → Helvetica/Arial → sans-serif → emoji`），中文走系统默认兜底（本机实测即微软雅黑，与显式雅黑差约 1.5%）；全局 `letter-spacing: .03em` 放宽字距（中文在雅黑下偏挤显扁）；同时不使用 `-webkit-font-smoothing: antialiased`，避免 Windows 关闭 ClearType 导致小字发虚
- 周期配色：日历格底色只按四档状态显示浅蓝绿、浅绿、浅黄、浅粉；阶段保留文字标签，图例与详情使用同一状态配色；窄屏月历保留两字状态名（旺盛/良好/一般/休息）；四档底色（2026-11-11）统一向白混合 50% 再浅一档，圆点与文字深阶保持不变
- 心得（三表均 1:1 挂记录、仅记录态可填）：共有 `rating/notes`，健身另有 `best_movement/next_steps`，游泳另有 `stroke_insight`，舞蹈另有 `video_effect`；页面字段称呼维持现状
- 状态记录（2026-11-11，非运动模块）：食欲 / 肌肉疼痛 / 炎症三类各一张表，同类同一天一行（重复新建 409）；字段仅日期、星级（0~5 可空；0=明确最低分，null=未评显示 —）、描述（≤255 可空），无计划态/起止时间/时长/心率/热量，不套运动契约。跨三表列表在 service 内存合并分页（日期倒序、id 倒序），支持类型筛选；月历复用周期七阶段推算并归并经期/卵泡·排卵/黄体三档圆点，男性或无周期记录时阶段置空；跨表批量删除每条自带类型定位表。性别开放（男女均可记录），无 Excel/JSON/AI 导入入口。页面自上而下三张卡片（月历 / 当日状态 / 全部记录）纵向堆叠、内容随卡片宽度自适应铺满；当日三类就地填写（内联星级 + 描述 + 保存，有记录可块内删除），全部记录列表行内编辑才弹出表单弹窗。页面 `/state-record`，API `/api/state-record`

## 2026-11 改版口径（运动训练/计划）

- **统一两态**：所有运动均为「计划 planned / 记录 recorded」。健身用 `training_records`、
  `training_records_items`、`training_notes` 三表；计划练完点「完成训练」二次确认后转 recorded；
  游泳/舞蹈的计划态为结构化字段：游泳需目标距离，舞蹈需舞种和星级；其余字段可按需填写。
- **数据层**：旧迁移脚本保留供历史升级；最终统一契约由 `scripts/migrate_sport_contract.py`
  幂等迁移。主表统一日期、起止时间、心率、热量等列，心得文本统一 `notes`，
  三运动主表 `user_id` 升级为数据库外键。现有 API 的业务必填：健身两态均需至少一条具备名称的动作；
  游泳计划需距离、记录需距离和时长；舞蹈两态均需舞种和星级。填写泳姿时须为合法值。
  统计口径：stats 只统计 recorded 行；总览聚合中 planned 计 plans、recorded 计 records/时长/热量。
- **总览**：`GET /api/overview?granularity=day|week|month&date=` 返回逐日 per-sport 计数、汇总卡与图表序列
  （week=周一~周日逐日分钟堆叠；month=当月逐日分钟堆叠，labels=1..月末日号；day=chart 为空）；
  `GET /api/overview/day?date=` 返回当日三运动全部条目。页面 `/overview` 默认周视图，
  点击「某天 × 某运动」标签弹单日详情，可一键跳转 `/{sport}?date=某日`。
- **总览三视图整改（2026-11-04）**：聚合响应 `sports.*` 增逐条 `items[]`（每条含 id/status/tag(计|记)/main/minutes/remark），
  周/月每日卡每条计划/记录渲染**独立标签**（不再合并计数），remark 显示在标签内部第二行；
  标签文字前圆点按类型着色——计划=蓝绿 `#17b3a6`、记录=深灰 `#6b7280`；日视图三运动卡改为
  各占一行全宽堆叠、卡头用 4px 小色条标识（禁大面积背景色），并**完整展示**每条计划/记录内容
  （健身逐动作明细、游泳/舞蹈完整标题与指标）；当日详情弹窗每条目内置 remark 编辑框，
  直接保存（回传完整 body，含只读字段），保存后 toast + 重开弹窗 + 刷新视图。
- **总览周期切换（2026-11-08）**：同一套 `/api/overview` 只换锚点——右上 `‹ ›` 按当前视图步进
  `state.anchor`（日 ±1 天、周 ±7 天、月 ±1 月，跨月夹到目标月最后一天），`?mode=&date=` 同步；
  标签按 `res.start/res.end` 渲染区间，区间不含今天才显示「回到今天」；周视图每日卡在周几右侧
  加灰色「月/日」。切日/周/月视图不改锚点，因此从周视图切到日视图仍落在原来的那一天。
- **单日页**：健身/游泳/舞蹈页支持 `?date=` 参数 + 前后翻页导航，默认当天；
  总览跳转某日即某日；非当日健身计划不开放「完成训练」（后端同口径校验）。
- **清理**：删除旧的健身周计划接口，跨运动总览统一从 `/api/overview` 读取；
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




