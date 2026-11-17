# AI 架构与开发说明

本文档描述项目当前已实现的 AI 架构、功能、工具和开发契约。AI 版本规划、进度和未实现设想见 [AIplan.md](AIplan.md)；项目宏观架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 一、AI 子模块

AI 能力分为六个逻辑子模块：

1. **模型与运行时**：模型注册、能力声明、提示词加载、LangChain 调用和结构化输出校验，位于 `app/ai/`。
2. **AI 导入**：接收文字和图片，识别健身、游泳、舞蹈记录并复用现有校验和落库逻辑，位于 `app/modules/electronic_trainer/` 及各运动模块的 `ai_profile.py`。
3. **AI Agent**：会话、多轮问答、SSE 流式输出和 checkpointer 持久化，位于 `app/modules/agent/`。
4. **数据问答工具**：面向 Agent 的只读业务查询工具与受控写工具，位于 `app/modules/agent/tools/`。
5. **技能系统**：平台只读技能（代码实现或声明式 DSL）与用户私有提示词技能，负责参数解析、校验、追问续接和执行审计，位于 `app/modules/agent/skills/`。
6. **AI 运动报告**：离线单次结构化调用，事实快照由代码计算、模型只做解释，位于 `app/modules/report/`；由系统计划任务按周/月触发，不进入会话与 checkpointer。

AI 能力复用现有业务 service 和统计口径，不重复实现业务计算；Agent 消息由 `langgraph` schema 的 checkpointer 表持久化，技能定义与运行审计使用独立业务表。

## 二、技术栈与运行配置

- 模型调用使用 OpenAI 兼容接口和 LangChain；Agent 使用 LangGraph。
- ORM 使用 psycopg2；Agent checkpointer 使用 psycopg3 异步连接。
- 模型共用 `AI_API_KEY`、`AI_BASE_URL`；默认地址为 `https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1`。
- 模型能力由注册表显式声明；视觉能力目前仅对 `qwen3-vl-plus` 声明，工具调用能力按实际注册配置声明。
- 提示词位于 `app/ai/prompts/`，由加载器统一读取；敏感配置位于 `.env`。
- Windows 启动 Agent 前使用 `WindowsSelectorEventLoopPolicy`；应用 lifespan 负责连接池、checkpointer 和图的装配与关闭。

## 三、结构化 AI 导入

### 3.1 处理链路

`POST /api/{sport}/ai-import` 接收 multipart 的 `prompt` 和可选多张 `images`，经登录门禁后执行：

1. 校验图片数量和大小，选择模型并加载提示词。
2. 调用 `invoke_ai_import`，使用 `with_structured_output(..., method="json_schema", strict=True)` 强制结构化解码。
3. 由运动模块 `ai_profile.py` 执行 `normalize`、`validate`。
4. 复用 `json_import` 和 `service` 的校验、落库逻辑。
5. 返回导入结果、警告和新建记录 ID。

导入数据统一写入 `recorded` 状态；不反向调用 `/import-json`，不新增数据库表。提示词只使用 `{today}` 和 `{weekday}` 两个变量，JSON 结构由服务端 schema 定义。

### 3.2 输入与结果约束

- 最多上传 3 张图片，单张不超过 2MB。
- 单条记录缺少日期时使用当天日期。
- 只提供开始时间或结束时间时，整对时间丢弃。
- 缺少关键字段的记录跳过，并在 `ai.warnings` 中说明。
- 前端就地展示结果，可批量撤销本次新建记录；校验失败时可回填 JSON 面板手动修正。

## 四、AI Agent

### 4.1 会话与图

- 页面路径为 `/agent`，API 前缀为 `/api/agent`，模块为 `app/modules/agent/`；技能管理页为 `/agent/skills`。
- 当前数据问答图为 `START → agent ⇄ tools → END`；模型通过 `bind_tools` 选择是否进入 `ToolNode`，工具结果以 `ToolMessage` 返回 Agent。
- 图按用户技能集装配：启动时用系统技能构建常驻 `system_graph`；存在用户私有技能时，按 `(user_id, 技能版本指纹)` 编译独立图并缓存（上限 32）。系统技能版本变化需重启服务或清缓存。
- `agent_chat.v4` 提示词的变量为 `today/weekday/capabilities`；`capabilities` 由基础只读工具、受控写工具（单独分组）与当前用户可用技能共同生成，不再在提示词里硬编码工具数量。
- `recursion_limit=10` 限制循环轮数，`MessagesState` 不扩展。
- 会话元数据存放在 `agent_conversations`；消息由独立 `langgraph` schema 的 4 张 checkpointer 表按 `thread_id` 持久化。
- 前端使用 `fetch` + `ReadableStream` 手动解析 SSE，不使用 EventSource。

### 4.2 会话与流式协议

- SSE 事件包括 `start`、`delta`、`tool_start`、`tool_result`、`done`、`error`；工具事件携带 `tool/label/kind/origin/version/skill`，`kind` 区分 `base`（查询）、`action`（写入）、`skill`（技能），`tool_result` 额外携带结构化 `data`。
- 首条消息发送时惰性创建会话；会话支持列表、新建、重命名、硬删除和模型选择。
- 用户可使用 `/技能名 自由文本` 直接触发技能；服务端同时接受技能键、技能名和斜杠别名。对话页输入 `/` 时前端读取 `GET /api/agent/skills` 的 active 技能并浮出建议，按名称/键/别名过滤，支持键盘选择与插入；参数齐全时注入一次 `AIMessage(tool_calls)` 并以 `aupdate_state(..., as_node="agent")` 续跑工具循环；缺参数时先追问，下一条普通文本自动并入原命令继续解析，不要求重新输入斜杠。
- `user_id`、会话归属和权限由服务端校验；模型不得指定或伪造用户身份。
- 工具调用期间前端按类型显示查询/保存/运行状态；技能结果显示技能名、版本、期间、输出表和 caveats，普通工具明细折叠展示，最多渲染 50 行。
- 模型失败返回 `error`，前端保留输入内容以便重试。
- 重新生成：`POST /api/agent/conversations/{id}/messages/regenerate` 复用同一套 SSE 事件；服务端经 `aupdate_state` + `RemoveMessage` 移除最后一条用户消息之后的工具中转与上一条 AI 回答（保留该用户消息），再以空输入续跑覆盖本次回答，不追加重复的用户消息；仅最近一轮可重新生成。
- 历史消息读取（`GET .../messages`）：按一轮问答聚合为 `turns`，把带 `tool_calls` 的中转 AIMessage 与 ToolMessage 归并到对应轮次的 `tool_runs`（含工具名、入参、结构化结果），前端据此重建工具状态与明细折叠，切换会话后与当次流式视图一致；按 `tool_call_id` 精确匹配、顺序兜底。兼容早期无 ToolMessage 的历史数据（对应工具结果为空，仅显示“已查询”、不渲染明细），并合并工具调用后重插的重复用户消息。

## 五、技能系统

### 5.1 平台技能与用户技能

- `scope=system`：平台技能，只读、可版本化，支持代码实现（`kind=code`）与平台内部声明式 DSL（`kind=declarative`）；当前内置 `lose_weight_analyse`（减重分析）与 `recent_swim_review`（游泳复盘），由 `scripts/seed_agent_skills.py` 幂等写入。平台声明式由平台维护，用户不可创建或编辑。
- `scope=user`：用户私有技能，只支持提示词（`kind=prompt`），仅本人可见、可编辑；不能写代码、SQL、表名或任意列名。声明式 DSL 不对用户开放。
- 用户技能绑定 `owner_user_id`，斜杠别名和技能键均按用户唯一；系统技能按 `skill_key` 全局唯一。数据库用 `scope-kind` 联合约束保证平台只存 `code/declarative`、用户只存 `prompt`；API 与管理页不再提供用户类型切换。
- 技能状态为 `draft/active/disabled/archived`；用户技能保存时仅当定义内容变化才新增版本，发布固化最新版本，旧版本保留用于审计；停用/删除后旧图调用会被执行层再次校验拦截。

### 5.2 平台声明式 DSL

声明式定义只用于平台内部技能，结构为 `schema_version/params/sources/steps/outputs/summary`：

- 参数类型仅 `date/int/bool/enum`；支持 `required/default/min/max/enum/label`。
- 数据源白名单：`body_metric/swim_records/fitness_records/dance_records/workout_summary/state_records/cycle_records/profile_info`。
- 算子白名单：`first/last/count/sum/avg/min/max/group_count`；参数化算子只接受白名单字段。
- 身材指标键必须使用 `weight`、`body_fat` 等模型字段，不使用 `weight_kg`、`body_fat_pct`。
- 输出表达式只允许数值、括号、`+ - * /` 和 `$step.field` 引用；由 AST 白名单解释器执行，禁止函数调用、属性访问、下标、比较和任意代码。
- 执行结果统一为 `status/range/sample_size/outputs/facts/summary/caveats`；空样本返回 `insufficient_data` 并给出 caveats，不编造数据。

### 5.3 提示词技能

- 定义结构为 `{"schema_version": 1, "prompt": "..."}`，`prompt` 去除首尾空白后为 1~4000 字；不允许出现 `params/sources/steps/outputs` 等额外字段。
- 提示词技能不取数、不嵌套第二次模型调用：`execution.py` 把提示词作为工具结果的 `summary` 返回，其余契约为 `outputs=[]`、`sample_size=0`、`range=null`、`facts={"prompt_chars": N}`、`caveats=[]`。
- `registry.skill_capabilities` 与 `describe_skill` 向模型说明：提示词技能返回的 `summary` 是必须遵循的技能指令，模型应据此回答用户，而不是复述指令；自然语言触发依赖 `description` 让模型选择 `skill_<key>`。
- 斜杠 `/技能名 内容` 由 `parser.parse_skill_args` 直接返回空参数、不追问、不抽取参数；斜杠后的文字保留在 HumanMessage 中供模型参考，不写入运行审计参数。
- 执行仍由 `execute_skill` 写入 `agent_skill_runs`，`trigger` 为 `slash/model/test`；提示词技能仅限 `scope=user`，平台技能不可创建或切换为 prompt。

### 5.4 参数解析与追问

1. 规则层先识别今天/昨天/前天、本周/上周、这个月/上个月、最近 N 天/周/月、最近 N 次、ISO 日期区间、`k=v` 和中文泳姿标签。
2. 规则不足时，用 `settings.ai_default_model` 经 `ainvoke_structured` 抽取；动态参数模型由 `build_args_model` 从技能定义生成，提示词为 `skill_arg_parse.v1`。
3. `normalize_args` 负责日期、整数、布尔和枚举清洗，`validate_args` 负责必填、范围与模型校验。
4. 缺参数时由 `build_question` 生成追问；`PendingStore` 为进程内存储，TTL 600 秒、最多追问 2 轮，按 `conversation_id + user_id` 绑定。
5. 追问期间下一条普通文本会与原斜杠命令合并重新解析；成功则注入技能调用，失败继续追问或清空。该机制不跨进程持久化，服务重启后待回答状态失效。

### 5.5 执行与审计

- 代码技能在 `platform.py` 中直接调用只读查询并计算；平台声明式技能由 `engine.py` 按数据源白名单取数并执行算子；提示词技能由 `execution.py` 直接返回提示词指令。
- `execution.py` 统一执行三类技能并写入 `agent_skill_runs`；`trigger` 为 `slash/model/test`，`parse` 记录模型、提示词版本、策略、解析耗时和 warnings。
- 工具名统一为 `skill_<key>`；工具从 `RunnableConfig` 读取 `user_id`，并读取 `skill_trigger`、`skill_parse`、`conversation_id` 用于审计。
- 技能管理 API 提供列表、详情、创建、保存、校验、发布、状态、删除、试运行和运行记录；平台技能只读，用户技能越权返回 403。

### 5.6 验收与测试

- `tests/test_agent_skills.py` 覆盖 DSL 非法字段/类型/表达式/未知引用、平台声明式取数与空样本、代码技能基线、日期规则、参数校验、创建/发布/停用/删除权限、别名冲突，以及提示词定义的键/长度校验、用户禁建声明式、prompt 技能创建发布执行和平台声明式只读装配。
- 管理页为 `/agent/skills`，左侧平台/我的技能列表、右侧编辑区；用户技能只提供提示词文本域，平台代码/声明式只读展示；字段只读状态由 `can_edit` 控制，删除权限由 `can_delete` 控制。
- 真实链路已验证：`/减重分析 这个月` 产生工具事件与完整回答；`/减重分析 最近` 先追问，用户回答“这个月”后继续执行。

## 六、只读数据工具

工具定义位于 `app/modules/agent/tools/definitions.py`，受控查询位于 `queries.py`。工具均为只读，不接受模型 SQL，不暴露表名和列名；每次调用使用独立短 session。

| 工具 | 数据范围 |
| --- | --- |
| `get_workout_summary` | 健身、游泳、舞蹈汇总：次数、时长、热量、活跃天数，区分计划和记录 |
| `get_fitness_records` | 健身明细、动作明细、容量、心率、热量和心得 |
| `get_swim_records` | 游泳明细、距离、时长、配速、划频、泳姿和心得 |
| `get_dance_records` | 舞蹈明细、舞种、老师、风格、评分、热量和心得 |
| `get_body_measurements` | 基础、期望、围度、目标四组身材数据及指定指标趋势 |
| `get_state_records` | 食欲、肌肉疼痛、炎症、情绪四类状态记录 |
| `get_cycle_records` | 周期参考值、月经记录、派生长度、每日疼痛和当前阶段 |
| `get_profile_info` | 昵称、性别、年龄、账号状态和注册时间，不含密码等敏感字段 |

工具时间范围支持 `days_back` 或 `start_date + end_date`，明细工具支持 `limit`；不传范围参数时查询全部历史。`user_id` 由 `RunnableConfig` 注入，模型不可填写；统计和派生值复用现有业务口径。

## 六补、受控写工具（save_today_workout_plan）

平台首个写操作工具，定义于 `app/modules/agent/tools/action_definitions.py`，与只读工具物理分离。安全边界由代码强制，不依赖提示词：

- `user_id` 从 `RunnableConfig` 注入，入参 schema 不含 `user_id`、`date`、`status`，模型无法指定或伪造；
- 日期内部固定 `today_local()`、状态固定 `planned`，仅写今日计划，不支持改/删、不支持任意日期，也不接受心率、热量、起止时间等记录态字段；
- 动作明细经 Pydantic 严格校验（`extra=forbid`），约束对齐训练模块 `PlanItemIn`：动作名必填（1–128）、部位可空（≤32）、重量 0–1000 且禁 NaN/inf、组数 1–99、次数为字符串可空（≤32）；
- 落库复用 `training.service.create_plan`，不新造写入通道；今日已有完全相同的 planned 计划时返回 `already_exists`，不重复落库。

“先询问再写入”是 human-in-the-loop：提示词要求给出动作方案后先询问、用户明确肯定后才调用；工具核心逻辑 `save_today_plan(db, user_id, payload)` 可注入 db 单测。SSE 事件中该工具 `kind=action`，前端显示“正在保存/已保存”。

## 七、AI 运动报告（周报/月报）

报告是独立于 AI 导入与 AI Agent 的第三条 AI 链路：**离线、单次、无工具、无会话**。它不读写 `agent_conversations`，不经过 LangGraph checkpointer，也不暴露给模型任何查询能力；模型只拿到一份已经算好的事实快照。

### 7.1 三层结构

1. **事实层**（`app/modules/report/facts.py`）：确定性计算，复用 overview / 三运动 / 身材 / 状态记录 / 周期 service 的既有口径，输出 `period_*`、扁平 `metrics`（key → `{key,label,value,unit,display}`）、4 张 `cards`、`totals/prev_totals`、`sports`、`body`、`state`、`cycle`、`weekly_breakdown`（月报）、`notes`、`completeness`、`kcal_scope/kcal_note`。
2. **叙事层**（`app/modules/report/ai.py`）：一次 `invoke_structured` 调用，schema 为 `ReportNarrative`（headline/summary/highlights/watchouts/next_actions/caveats/cycle_note），列表项为 `EvidenceItem(title/detail/evidence)`。
3. **依据层**：页面把 `facts` 原样展示（运动/身体/状态/周期/完整度），叙事中的 `evidence` 只映射到 `metrics` 的 key，不额外存放第二份数字。

### 7.2 生成流程

`service.generate`：算 facts + hash → 已 ready 且 hash 相同且非 force 直接返回 → 写 `generating`（唯一约束 `(user_id, period_type, period_start)` 兜底并发，同周期并发 409）→ 调模型 → evidence 校验/清洗 → 写 `ready`。失败写 `failed` 并保留 facts；页面可重试。空数据（周期内无任何 recorded 记录）走 `mode=rule` 规则文案，不调用模型。

- 提示词：`weekly_report.v1`、`monthly_report.v1`，变量严格为 `{today}`、`{period_range}`、`{period_label}`、`{status_note}`，在 `loader.py` 的 `PROMPTS` 注册。
- 输入：`facts` 的 JSON 字符串；`{today}` 取事实截止日（进行中周期为 `as_of`）。
- 超时：`REPORT_TIMEOUT_SECONDS`（默认 60s）经 `invoke_structured(timeout=...)` 传给 `get_model`；模型默认 `AI_DEFAULT_MODEL`，可用 `REPORT_MODEL` 覆盖。
- evidence 校验：`evidence` 只能取 `facts.metrics` 中存在的键；无效键删除并记 warnings；一条内容的 evidence 全部无效时整条丢弃，避免编造依据留在页面。

### 7.3 周期与过期

- 周报 = 周一~周日（`monday_of`）；月报 = 自然月 1 日~月末。未结束周期 `period_end` 仍存周日/月末，`as_of=min(end,today)`、`partial=True`，页面标「进行中（截至 X）」；未来周期禁止生成。
- `data_hash` = `facts`（剔除 `as_of`/`partial`）的 SHA-256；周期结束后数据补齐、或用户补录记录导致 hash 变化时，页面标「数据已更新」并可重新生成；旧叙事仍保留为快照。
- 进行中周期的环比只取上期「同期」天数（如 11 月 1–17 日对比 10 月 1–17 日、本周前三天对比上周前三天），卡片文案标「较上期同期」，避免 17 天与整月直接比较造成假涨跌。
- 统计只计 `recorded`，计划单独计数；不做「计划完成率」（planned→recorded 原地改状态，无溯源字段）。热量沿用总览口径只汇总游泳+舞蹈，健身热量单列，`caveats` 与页面口径说明同步写明。
- 周期分析：仅 `gender != 男` 且 `calendar_month(...).overview.has_records` 为真时输出；周跨月按月调 `calendar_month` 合并逐日；真实/推算/预测分开统计，`cycle_note` 必须区分，预测段不得当事实。

### 7.4 自动生成

应用进程内**没有**常驻 asyncio 循环。由 Windows 任务计划程序每 30 分钟执行 `scripts/generate_reports.py --scan`：

- 周一凌晨命中「上周周报」（`today - 7` 所在周），每月 1 日命中「上月月报」（`today.replace(day=1) - 1` 所在月）；
- PostgreSQL `pg_try_advisory_lock` 防重入；单实例串行生成；日志 `logs/report_task.log`；
- `ready`/`deleted` 跳过；`failed` 且 `attempts >= REPORT_MAX_ATTEMPTS` 不再自动重试；`generating` 超过 5 分钟视为卡死转 `failed`；
- **半程报告重写**：若该周期已有 `ready` 报告，但快照里 `facts.partial=true` 而当前周期已结束，扫描仍会命中并带 `force=True` 重写，避免月报停留在月中数据；
- `--dry-run` 只打印到期周期（含 `refresh` 标记）；`--type/--anchor/--user/--force` 可手动生成单个周期。

### 7.5 接口与页面

- 页面 `GET /reports?type=weekly|monthly&anchor=YYYY-MM-DD`；API `GET /api/reports`、`POST /api/reports/generate`、`GET /api/reports/history`、`DELETE /api/reports/{id}`（软删除）。
- 页面结构：4 张事实卡 → 叙事（亮点/留意/下阶段建议/周期视角/数据说明）→ 判断依据 → 历史报告。前端只渲染 facts 与 narrative，不自行算数。

### 7.6 测试

`tests/test_report.py` 覆盖周期归一（周/月/进行中）、空数据、热量口径、进行中同期对比、周期仅女性有记录、规则模式不调模型、ready 复用与 force、失败保留 facts、软删除与扫描跳过、半程报告周期结束后重写、evidence 清洗。

## 八、AI 开发契约

1. 新增或修改 AI 功能前，必须先阅读本文件、`docs/ARCHITECTURE.md` 和 `docs/AIplan.md`。
2. 本文件只记录已实现的 AI 架构、功能、工具、接口和开发契约；版本路线、进度和未实现设想写入 `docs/AIplan.md`。
3. 新增工具必须同步更新工具定义、受控查询、注册清单、提示词、前端事件（如有变化）和测试。
4. 数据查询工具必须只读，参数仅限业务字段和受控枚举，不接受模型提供的 `user_id`、SQL、表名或列名。受控写工具与只读工具分离，只能写今日 planned 健身计划，`user_id` 从 config 注入、日期与状态由代码固定，复用训练模块统一落库逻辑并做防重复。
5. AI 导入必须复用运动模块现有规范化、校验和落库逻辑，不得绕过统一运动契约或新增重复落库路径。
6. 提示词维护按 `AGENTS.md`「提示词维护契约」执行：固定 ID 经 loader 加载、变量与能力声明和代码一致、版本替换后删除无引用的旧文件与映射，并同步本文件；模型注册表与结构化 schema 变更同样确认变量、能力声明与代码一致。
7. 涉及数据库、前端、运动模块或版本进度时，分别按 `AGENTS.md` 同步维护对应文档和代码。
8. AI 测试需覆盖权限隔离、查询工具只读、写工具的校验/落库/防重复、模型异常、结构化校验失败和 SSE 事件；清理模拟数据时不得删除原有数据。
9. 平台技能用代码实现或平台内部声明式 DSL，复用只读工具层并补测试；用户技能只允许提示词，提示词不得成为代码/SQL 入口；任何新增平台声明式数据源、字段或算子都要先更新白名单、校验、执行器、平台只读展示和测试，禁止开放 SQL/代码入口。
10. 技能定义变更或平台技能升级后，`scripts/seed_agent_skills.py` 与 `scripts/schema.sql` 必须保持幂等；运行审计不得写入密码、完整聊天正文或超出技能参数范围的数据。
11. 报告功能（`app/modules/report/`）必须保持「事实层确定性计算、叙事层只解释」的分层：新增指标先加到 `facts.metrics` 并写入提示词可用 key 白名单，再让模型引用；不得让模型直接查库或自行计算。报告生成失败必须保留 `facts`，删除必须走软删除，自动生成必须由计划任务调 CLI，不得在应用进程内起常驻循环。

## 九、文件索引

| 内容 | 文件 |
| --- | --- |
| 模型注册 | `app/ai/models/` |
| 提示词加载与文件 | `app/ai/prompts/` |
| AI 调用与结构化输出 | `app/ai/runtime/` |
| AI 导入编排 | `app/modules/electronic_trainer/ai_import.py` |
| 运动 AI 适配 | 各运动模块 `ai_profile.py` |
| Agent 图与生命周期 | `app/modules/agent/graph.py` |
| 技能引擎与平台技能 | `app/modules/agent/skills/` |
| 工具定义（只读） | `app/modules/agent/tools/definitions.py` |
| 受控写工具 | `app/modules/agent/tools/action_definitions.py` |
| 受控查询 | `app/modules/agent/tools/queries.py` |
| AI 页面 | `app/templates/agent/`、`app/static/js/agent.js`、`app/static/js/agent_skills.js`、`app/static/css/pages/agent.css`、`agent_skills.css` |
| 技能种子与迁移 | `scripts/seed_agent_skills.py`、`scripts/migrate_agent_skills.py` |
| 报告事实快照 / 叙事 / 服务 / 模型 | `app/modules/report/facts.py`、`ai.py`、`service.py`、`models.py` |
| 报告提示词 | `app/ai/prompts/weekly_report_v1.txt`、`monthly_report_v1.txt` |
| 报告页面 | `app/templates/report/`、`app/static/js/report.js`、`app/static/css/pages/report.css` |
| 报告迁移与定时任务 | `scripts/migrate_reports.py`、`scripts/generate_reports.py`、`scripts/register_report_task.ps1` |
| AI 规划 | `docs/AIplan.md` |
