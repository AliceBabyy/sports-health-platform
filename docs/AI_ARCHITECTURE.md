# AI 架构与开发说明

本文档描述项目当前已实现的 AI 架构、功能、工具和开发契约。AI 版本规划、进度和未实现设想见 [AIplan.md](AIplan.md)；项目宏观架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 一、AI 子模块

AI 能力分为六个逻辑子模块：

1. **模型与运行时**：模型注册、能力声明、提示词加载、LangChain 调用和结构化输出校验，位于 `app/ai/`。
2. **AI 导入**：接收文字和图片，识别健身、游泳、舞蹈记录并复用现有校验和落库逻辑，位于 `app/modules/electronic_trainer/` 及各运动模块的 `ai_profile.py`。
3. **AI Agent**：会话、多轮问答、SSE 流式输出、checkpointer 持久化与多角色会话人设，位于 `app/modules/agent/`。
4. **数据问答工具**：面向 Agent 的只读业务查询工具、受控写工具，以及按轮开启的联网搜索工具，位于 `app/modules/agent/tools/`。
5. **技能系统**：平台技能（代码实现或声明式 DSL；普通用户只读，管理员可在系统设置维护）与用户私有提示词技能，负责参数解析、校验、追问续接和执行审计，位于 `app/modules/agent/skills/`。
6. **AI 运动报告**：离线单次结构化调用，事实快照由代码计算、模型只做解释，位于 `app/modules/report/`；由 `app/modules/system/scheduler/` 的 cron 任务按周/月触发，不进入会话与 checkpointer。
7. **每日训练建议**：侧栏「今天」卡内的要点判断，同样离线单次调用、事实由代码计算，位于 `app/modules/daily_advice/`；每天 00:01 由调度器生成一份，不进入会话与 checkpointer。

AI 能力复用现有业务 service 和统计口径，不重复实现业务计算；Agent 消息由 `langgraph` schema 的 checkpointer 表持久化，技能定义与运行审计使用独立业务表。

## 二、技术栈与运行配置

- 模型调用使用 OpenAI 兼容接口和 LangChain；Agent 使用 LangGraph。
- ORM 使用 psycopg2；Agent checkpointer 使用 psycopg3 异步连接。
- 模型共用 `AI_API_KEY`、`AI_BASE_URL`；默认地址为 `https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1`。
- 模型能力由注册表显式声明；视觉能力目前仅对 `qwen3-vl-plus` 声明，工具调用能力按实际注册配置声明。
- 模型入口与配置键（均写在 `.env`，改后需重启进程；模型名必须已在 `MODELS` 注册）：

| 入口 | 模型来源 | 配置键 |
| --- | --- | --- |
| AI 对话 | 会话 `model_name`，为空回落默认 | `AI_DEFAULT_MODEL`；下拉列表取自 `MODELS` 注册表，非配置项 |
| AI 导入·纯文字 | `settings.ai_import_model` | `AI_IMPORT_MODEL`（默认 `qwen3.8-flash`） |
| AI 导入·带图 | `settings.ai_import_vision_model` | `AI_IMPORT_VISION_MODEL`（默认 `qwen3-vl-plus`） |
| AI 运动报告 | `report_model` 留空回落默认 | `REPORT_MODEL`（默认空） |
| 每日训练建议 | 固定默认模型 | 无独立键，跟随 `AI_DEFAULT_MODEL` |
| 技能参数解析 | 固定默认模型 | 无独立键，跟随 `AI_DEFAULT_MODEL` |

- 提示词位于 `app/ai/prompts/`，由加载器统一读取；敏感配置位于 `.env`。
- 联网搜索使用 Tavily（`TAVILY_SEARCH_URL` 默认 `https://api.tavily.com/search`），密钥 `TAVILY_API_KEY`、总开关 `WEB_SEARCH_ENABLED`；结果条数/超时/摘要长度由 `WEB_SEARCH_MAX_RESULTS`、`WEB_SEARCH_TIMEOUT_SECONDS`、`WEB_SEARCH_SNIPPET_CHARS` 控制，均由服务端固定，模型不可指定。
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

- 页面路径为 `/agent`，API 前缀为 `/api/agent`，模块为 `app/modules/agent/`；技能管理页为 `/agent/skills`，角色管理页为 `/agent/personas`；管理员内置技能页为 `/system/skills`，API 为 `/api/system/system-skills`。
- 当前数据问答图为 `START → agent ⇄ tools → END`；模型通过 `bind_tools` 选择是否进入 `ToolNode`，工具结果以 `ToolMessage` 返回 Agent。健康档案测试的保存工具 `save_health_profile_aspect` 成功后由条件边直接进入 `finalize_profile_save` 固定收口，不再回到 `agent`，避免同一会话自动开始下一个专项。
- 图按用户技能集与角色授权装配：启动时用系统技能构建常驻 `system_graph`；存在用户私有技能、角色显式工具/技能白名单或角色专用工具时，按 `(user_id, 技能版本指纹, 角色指纹)` 编译独立图并缓存（上限 32）。角色提示词本身只影响 system prompt；`tool_grants` / `skill_grants` 非空时参与图装配，为空（NULL）时沿用 `TOOL_PERSONA_SCOPES` 等代码基线。系统技能版本变化需重启服务或清缓存。
- `agent_chat.v8` 提示词的变量为 `today/weekday/now_time/capabilities/persona_block/run_mode`；日期、星期与当前时刻由 `graph.py` 在每次模型调用时用本机时间注入（`%H:%M`，24 小时制），随会话实时变化；`capabilities` 由交互工具（`ask_user` 单独成组）、基础只读工具、受控写工具（单独分组）与当前用户可用技能共同生成，不再在提示词里硬编码工具数量；本轮开启联网时，`graph.py` 还会在 `capabilities` 末尾追加「联网搜索（本轮已开启）」段并把 `web_search` bind 给模型；`persona_block` 由会话绑定的角色版本渲染，普通会话为固定默认句；`run_mode` 取「常规」或「续写」，只由续写接口置为「续写」。
- `recursion_limit=10` 限制循环轮数，`MessagesState` 不扩展。
- 会话元数据存放在 `agent_conversations`（含角色会话的 `persona_id` 与创建时版本号）；消息由独立 `langgraph` schema 的 4 张 checkpointer 表按 `thread_id` 持久化；角色定义存放在 `agent_personas` / `agent_persona_versions`。
- 前端使用 `fetch` + `ReadableStream` 手动解析 SSE，不使用 EventSource。

### 4.2 会话与流式协议

- SSE 事件包括 `start`、`delta`、`tool_start`、`tool_result`、`ask`、`done`、`error`；`start` 带 `resume` 表示本次是从等待回答的 interrupt 恢复；工具事件携带 `tool/label/kind/origin/version/skill/call_id`，`kind` 区分 `base`（查询）、`action`（写入）、`skill`（技能），`call_id` 用于把结果精确配回调用，`tool_result` 额外携带结构化 `data`。工具展示标签（`label`）与类别由服务端下发，前端只保留 `kind → 正在查询/已查询` 等文案映射，不再维护工具名表。
- 首条消息发送时惰性创建会话；会话支持列表、新建、重命名、硬删除和模型选择。
- 用户可使用 `/技能名 自由文本` 直接触发技能；服务端同时接受技能键、技能名和斜杠别名。对话页输入 `/` 时前端读取 `GET /api/agent/skills` 的 active 技能并浮出建议，按名称/键/别名过滤，支持键盘选择与插入；参数齐全时注入一次 `AIMessage(tool_calls)` 并以 `aupdate_state(..., as_node="agent")` 续跑工具循环；缺参数时先追问，下一条普通文本自动并入原命令继续解析，不要求重新输入斜杠。
- `user_id`、会话归属和权限由服务端校验；模型不得指定或伪造用户身份。
- 工具调用期间前端按类型显示查询/保存/运行状态；技能结果显示技能名、版本、期间、输出表和 caveats，普通工具明细折叠展示，最多渲染 50 行。
- 前端把一条 AI 回答建模为一个 turn（`blocks` 正文段 + `toolRuns` + `meta`）：发送、重新生成与历史恢复共用 `runStream → applyEvent → finalizeTurn` 一条链路，`delta` 只在下一个动画帧合并渲染，不再各写一套事件分支。
- 中途提问（HITL）：`ask_user` 工具内调用 LangGraph `interrupt()` 挂起，Postgres checkpointer 保存执行位置；前端收到 `ask` 事件在同一 turn 里插入问答卡片。用户作答走后端同一条 `POST .../messages`，服务端先读图状态，识别到挂起的 interrupt 就用 `Command(resume=答案)` 从同一 thread 继续，不新增 HumanMessage——问答与后续正文留在原来那一轮。用户可点「跳过」：前端带 `skip_ask=true`，服务端以 `{answer:null, skipped:true}` 恢复，工具回传 `skipped=true`，模型按已有信息继续并说明缺少的依据，历史 ask 段标记 `skipped=true`。`GET .../messages` 会把 ask 段还原并把当前问题标记为 `pending`，刷新后仍可作答；等待回答期间 `regenerate` 返回 409。工具回答后以 ToolMessage 回到模型，历史里由 ask 段的 `answer`/`skipped` 承载，不额外显示工具行。
- 模型失败返回 `error`，前端保留输入内容以便重试。
- 重新生成：`POST /api/agent/conversations/{id}/messages/regenerate` 复用同一套 SSE 事件；服务端经 `aupdate_state` + `RemoveMessage` 移除最后一条用户消息之后的工具中转与上一条 AI 回答（保留该用户消息），再以空输入续跑覆盖本次回答，不追加重复的用户消息；仅最近一轮可重新生成。
- 生成中状态：`GET .../messages` 额外返回 `generating`，取进程内运行句柄 `_runs[thread_id]` 且结束信号未置位（进程重启后自然为 false）；历史恢复时若仍在生成，前端在末尾追加“正在生成…”占位并每 2.5 秒重拉一次，生成结束后自动替换成完整回答。
- 会话恢复：选中会话同步进 URL `?conversation_id=` 与 localStorage（`sh.agent.current`）；进入页面先按 URL、再按 localStorage 恢复，且只采用当前会话列表里存在的 id，切换页面或刷新不再退回“新建对话”态。
- 历史消息读取（`GET .../messages`）：按一轮问答聚合为 `turns`，每轮含 `blocks`（按出现顺序排列的正文段，含带 `tool_calls` 的中转 AIMessage 正文）与 `tool_runs`（`tool/label/kind/call_id/args/data`），工具结果按 `call_id` 精确匹配、缺失时顺序兜底。前端把流式事件与历史结构灌进同一个 turn 对象并用同一套渲染器收口，切换会话后与当次流式视图一致；兼容早期无 ToolMessage 的历史数据（对应工具结果为空，仅显示“已查询”、不渲染明细），并合并工具调用后重插的重复用户消息。最近一轮停在中断处时该轮带 `interrupted=true`，前端据此显示“已停止生成”与「继续」；中断后被续写，两段正文在历史里拼回同一段。
- 中断：流式期间发送按钮就地变为停止按钮，前端用 `AbortController` 立即断开 SSE，并调用 `POST .../messages/stop` 交给服务端收口。已流出正文只记在进程内运行句柄（`_runs[thread_id]["partial"]`）；停止信号用“下一帧 vs 停止信号”竞速打断 `astream`，被取消的生成器不写 checkpointer、不碰数据库。`stop` 在生成器收尾后用自己的请求 session 收口：回滚“工具调用没配齐结果”的尾部消息（已完整执行完的工具轨迹保留），并把已流出正文写成一条 `additional_kwargs={"interrupted": true}` 的 AIMessage；8 秒内未收尾（如响应头发出前就断连）返回 `settled=false` 并释放占位，避免会话被永久锁住。无进行中的生成时返回 `stopped=false`。
- 续写：`POST .../messages/continue` 不新增 HumanMessage，在既有状态上以 `configurable.run_mode=续写` 再跑一次 agent；`agent_chat.v8` 的「续写模式」段要求模型接着被中断的半截回答往下写、不重复不重开场。最近一轮已完成或为空返回 400，正等待回答返回 409。前端「继续」按钮与输入框只发“继续/接着/continue”这类短语时都走这条路径；刷新后由 `GET .../messages` 的 `interrupted` 标记恢复该按钮。
- 中断边界：中断只结束本轮会话消息，不撤销已经落库的业务写入（如已保存的今日计划）；“继续”复用已完成的工具结果，不重复调用同一只读工具。

### 4.3 多角色 Persona

- 角色本身只提供一段提示词，影响语气、关注重点与表达风格；不改变数据事实、安全与免责规则，用户角色定义也不承载代码、SQL、数据源或工具授权。工具与技能可见性由服务端控制：`TOOL_PERSONA_SCOPES` 提供默认角色范围，角色表 `tool_grants` / `skill_grants` 提供管理员显式白名单。
- 平台内置角色为 `nutrition`（营养师）、`e_trainer`（电子私教）与 `health_profile_test`（健康档案测试），`scope=system`，普通用户只读；平台管理员可在 `/system/personas` 增删改查、排序、启停、编辑提示词并勾选工具/技能。内置角色由 `scripts/seed_agent_personas.py` 从 `persona_nutrition.v1` / `persona_e_trainer.v1` / `persona_health_profile_test.v3` 幂等写入；种子阶段先走与用户角色相同的 `validate_definition`，提示词超过 `agent_persona_max_chars`（当前 3000 字）直接失败，避免写入运行时无法解析的版本。`health_profile_test` 另追加 `persona_health_profile_test_guard.v3` 运行约束，独立于角色版本生效；用户角色 `scope=user`，只有名称、键、定位和提示词，仅创建者可见。`health_profile_test` 是正式内置角色名（“测试”是产品命名），两个 v3 提示词均被运行时依赖，不是测试夹具或可清理的废弃提示词。
- 角色级白名单口径：`tool_grants` / `skill_grants` 为 `NULL` 时沿用默认范围（未登记工具全开、专用工具只在注册角色可用、平台技能全开）；非空数组（含空数组）表示显式白名单，空数组即不使用任何工具/技能。管理员可以给普通工具配置显式白名单，也可以在 `/system/personas` 选择「恢复默认范围」写回 `NULL`；但健康档案 9 个专项技能与 `save_health_profile_aspect` 是硬边界，只允许 `health_profile_test`，其他角色即使写入白名单也会在运行时被过滤，管理端提交时直接报错。用户角色目前不开放白名单编辑，沿用默认范围。
- 角色会话在 `POST /api/agent/conversations` 传入 `persona_id` 创建，同时写入 `persona_version_no`；创建后整段会话固定该角色，**不提供切换接口**。普通会话两列为空，行为与未上线前完全一致。
- 角色版本只增不改：用户角色保存即生成新版本并立即生效（无草稿/发布两步）；平台角色文案变化由种子脚本新增版本。历史角色会话按创建时版本读取，不随角色改版漂移。
- 角色停用只禁止新建角色会话，已绑定会话仍按快照继续；删除角色前必须删除引用它的会话，否则 409。
- 提示词分层：`agent_chat.v8` 基座规则在前，末尾插入「角色设定」并紧跟「规则优先级（最高）」重申角色不得覆盖前述规则；`persona_block` 空时传固定默认句，不留空段。`health_profile_test` 的 `persona_block` 在角色提示词后追加 `persona_health_profile_test_guard.v3`，明确健康档案拆成 9 个专项、一次只做一个专项、每个专项由 AI 在提示词约束下生成 3~6 题、逐题提问、保存后立即结束；禁止把目标、饮食、运动、睡眠、生活方式、生理期、形体、伤病、补充混成一套“大杂烩”问卷；旧版本角色会话也受该约束。
- 工具可见性：`app/modules/agent/tools/policy.py` 的 `TOOL_PERSONA_SCOPES` 是代码基线，当前登记 9 个 `skill_profile_*` 与 `save_health_profile_aspect → {health_profile_test}`；9 个专项技能与保存工具同时列入 `PROFILE_TEST_ONLY_TOOLS` 硬边界，任何角色显式白名单都不能绕开。未登记的工具默认对所有角色与普通会话可用。运行时 `tools_for_persona` 先检查硬边界，再看角色的显式 `tool_grants`，非空时完全按白名单；为 `NULL` 时再回落到 `TOOL_PERSONA_SCOPES`。技能侧同理：`available_skills` 先排除非 `health_profile_test` 的专项技能，再看显式 `skill_grants`，为 `NULL` 时沿用 `TOOL_PERSONA_SCOPES` 中的 `skill_<key>` 基线与平台技能全开；`include_restricted=True` 只给 `/system/personas` 管理页与校验层列出全平台技能，不代表可执行权限。过滤发生在服务端装配阶段，不依赖提示词；过滤后 `capabilities` 只列当前角色可用项。显式白名单或默认专用工具会进入图缓存 key。
- 页面为 `/agent/personas`（侧栏「AI助手」→「角色管理」）：左侧平台角色/我的角色，右侧提示词编辑；平台角色普通用户只读，用户角色可保存、启停、删除。管理员页面为 `/system/personas`（侧栏「系统设置」→「内置角色」），可新建/编辑/删除内置角色、调整排序与状态，并按工具/技能的稳定清单勾选白名单。对话页「新建角色会话」点击后弹出角色选择弹窗，从 `INIT_PERSONAS` 选择启用且已发布的角色；侧栏角色会话带「人形图标 + 角色名」徽标。
- 相关 API：普通用户角色列表/详情/创建/保存/启停/删除 6 个接口；管理员内置角色列表/选项/创建/详情/保存/删除 6 个接口，统一在 `/api/system/system-personas` 下并受 `/api/system` 管理员门禁保护。平台角色普通用户编辑 403、非本人用户角色 403、被会话引用删除 409。
- `tests/test_agent_personas.py` 覆盖定义字段/长度、创建与版本化、配额与平台遮蔽、权限、删除引用、会话版本快照与停用、角色段渲染、工具预留接缝、v6 变量与 v5 移除、会话两列一致性约束，以及内置角色提示词必须通过运行时同口径定义校验；`tests/test_system_personas.py` 覆盖内置角色 CRUD、版本化、键不可改、工具/技能白名单校验与运行时过滤；`tests/test_profile_aspect.py` 覆盖 9 个专项提示词加载、专项归属校验、3~6 题与 q1~q6、同专项最多 3 套、cycle 仅女性、页面逐题保存/清空、`profile_info` 新结构、保存工具边界、受限技能按角色过滤、保存成功后的 `finalize_profile_save` 收口与 v3 guard；`tests/test_ai_foundation.py` 校验提示词注册表与 `app/ai/prompts` 目录文件一一对应，防止遗留测试提示词或废弃提示词。

## 五、技能系统

### 5.1 平台技能与用户技能

- `scope=system`：平台技能，对普通用户只读、可版本化，支持代码实现（`kind=code`）与平台内部声明式 DSL（`kind=declarative`）；当前内置 `lose_weight_analyse`（减重分析）、`recent_swim_review`（游泳复盘），以及 9 个健康档案专项技能 `profile_goal` / `profile_diet` / `profile_exercise` / `profile_sleep` / `profile_lifestyle` / `profile_cycle` / `profile_posture` / `profile_medical` / `profile_extra`，由 `scripts/seed_agent_skills.py` 幂等写入。9 个专项技能带固定斜杠别名（`/目标档案`、`/饮食档案`、`/运动档案`、`/睡眠档案`、`/生活方式`、`/生理期档案`、`/形体矫正`、`/伤病档案`、`/档案补充`），输入参数只有 `mode ∈ {补齐, 更新}`，执行时返回该专项提示词和已有答案上下文；仅 `health_profile_test` 角色可见可调用。普通用户在 `/agent/skills` 只读；管理员可在 `/system/skills` 维护：代码技能定义由代码注册、仅可启停，声明式技能可新建、编辑、版本化与删除。平台声明式 DSL 仍只作为平台内部能力维护，不对用户开放创建或编辑。
- 管理员保存/启停/删除平台技能后，`runtime.refresh_system_graph()` 重建常驻系统图并清空按用户图缓存，默认用户与角色会话的下一次提问即使用最新技能集，无需重启；图重建失败只记日志，重启后仍按数据库最新状态加载。被内置角色显式 `skill_grants` 引用的技能删除返回 409，避免角色白名单静默失效。
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
- 技能管理 API 提供列表、详情、创建、保存、校验、发布、状态、删除、试运行和运行记录；`/api/agent/skills` 对平台技能只读，用户技能越权返回 403。管理员另走 `/api/system/system-skills`，可新建/编辑/版本化/启停/删除平台声明式技能，代码技能仅启停；接口自动受 `/api/system` 管理员门禁保护。

### 5.6 验收与测试

- `tests/test_agent_skills.py` 覆盖 DSL 非法字段/类型/表达式/未知引用、平台声明式取数与空样本、代码技能基线、日期规则、参数校验、创建/发布/停用/删除权限、别名冲突，以及提示词定义的键/长度校验、用户禁建声明式、prompt 技能创建发布执行和平台声明式只读装配。
- `tests/test_system_skills.py` 覆盖内置技能的创建/列表、拒绝代码类型、非法 DSL、键/名/别名全局冲突、定义变化才升版本、代码技能只读与启停、角色白名单引用删除保护、定义校验、试运行成功/非法参数、跨用户运行记录，以及系统图重建与用户缓存清理。
- 管理页为 `/agent/skills`，左侧平台/我的技能列表、右侧编辑区；用户技能只提供提示词文本域，平台代码/声明式只读展示；字段只读状态由 `can_edit` 控制，删除权限由 `can_delete` 控制。管理员内置技能页为 `/system/skills`，沿用同一工作台布局：代码技能只读定义+仅启停，声明式技能可编辑定义并版本化、校验、试运行、查看运行记录；`active=system_skills`，仅管理员可见。
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
| `get_state_records` | 食欲、肌肉疼痛、炎症、情绪、恢复五类状态记录 |
| `get_cycle_records` | 周期参考值、月经记录、派生长度、每日疼痛与 note、当前阶段 |
| `get_profile_info` | 昵称、性别、年龄、账号状态、注册时间，9 个专项档案（每项含最近一套与最近 3 套历史，题目带 `local_key/aspect/label/hint/placeholder/max_length/answer`），以及 `health_profile_meta`（`filled/set_count/skill_count/created_at/updated_at`），不含密码等敏感字段 |

工具时间范围支持 `days_back` 或 `start_date + end_date`，明细工具支持 `limit`；不传范围参数时查询全部历史。`user_id` 由 `RunnableConfig` 注入，模型不可填写；统计和派生值复用现有业务口径。

## 六补、受控写工具

受控写工具与只读工具物理分离。当前包含健身计划 `save_today_workout_plan` 与健康档案 `save_health_profile_aspect`；后者见下一节。健身计划工具边界由代码强制，不依赖提示词：

- `user_id` 从 `RunnableConfig` 注入，入参 schema 不含 `user_id`、`date`、`status`，模型无法指定或伪造；
- 日期内部固定 `today_local()`、状态固定 `planned`，仅写今日计划，不支持改/删、不支持任意日期，也不接受心率、热量、起止时间等记录态字段；
- 动作明细经 Pydantic 严格校验（`extra=forbid`），约束对齐训练模块 `PlanItemIn`：动作名必填（1–128）、部位可空（≤32）、重量 0–1000 且禁 NaN/inf、组数 1–99、次数为字符串可空（≤32）；
- 落库复用 `training.service.create_plan`，不新造写入通道；今日已有完全相同的 planned 计划时返回 `already_exists`，不重复落库。

“先询问再写入”是 human-in-the-loop：提示词要求给出动作方案后先询问、用户明确肯定后才调用；工具核心逻辑 `save_today_plan(db, user_id, payload)` 可注入 db 单测。SSE 事件中该工具 `kind=action`，前端显示“正在保存/已保存”。

## 六补二、健康档案专项技能与写工具（save_health_profile_aspect）

健康档案不再是一套混合问卷，而是 9 个专项：目标、饮食、运动、睡眠、生活方式、生理期、形体矫正、伤病、档案补充。每个专项对应一个平台代码技能，固定注册在 `app/modules/profile/aspect_skills.py`，技能定义在 `app/modules/agent/skills/platform.py`：

- 9 个专项 skill 的 key、名称、斜杠别名、允许 aspect、提示词 ID、页面 section 由 `aspect_skills.py` 单一维护；不允许模型或用户新增专项。
- 9 段专项提示词合并在 `app/ai/prompts/profile_aspect_skills_v1.txt`，用 `===== goal =====` 等 section 分隔；`loader.PROMPTS` 用 `(文件名, section)` 映射为 9 个固定 ID，不允许多个文件各存一段。
- 每个 skill 的输入只有 `mode ∈ {补齐, 更新}`；执行时 `skill_runtime.run_profile_aspect` 加载对应 section，并拼接该用户该专项已有问答与当前 mode，作为工具结果 `summary` 返回给模型。题目本身不预置、不写死注册表，由模型每次按提示词生成 3~6 题。
- cycle 专项 `female_only=True`，保存时服务层再校验用户性别，男性账号直接 400。
- 9 个专项 skill 与 `save_health_profile_aspect` 只允许 `health_profile_test`，运行时硬边界；其他角色保留 `get_profile_info` 只读，管理员也无法通过角色白名单授权。受限技能在普通用户的斜杠建议中不返回（`/api/agent/skills/available` 按角色过滤），平台技能管理页仍以只读条目展示；`/system/personas` 用 `include_restricted=True` 列出以便查看，非 `health_profile_test` 角色提交这些授权会校验失败。

`save_health_profile_aspect` 定义于 `app/modules/agent/tools/health_profile_actions.py`，边界由代码强制：

- 入参经 Pydantic 严格校验（`extra=forbid`）：`skill_key` 必须是 9 个专项之一；`questions` 3~6 题，`local_key` 只允许 `q1~q6`，标题 ≤48、提示/占位 ≤120、`max_length` 50~255、`aspect` 必须是该专项允许的固定方面；`answers` 的 key 必须对应题目，至少 1 题有答案，只记录用户实际回答。
- `user_id` 从 `RunnableConfig` 注入，模型不能传；不接受日期、表名、SQL 或任意题目结构。保存工具只写当前专项最近一套，不会覆盖其他专项。
- 落库复用 `profile.service.save_health_profile_aspect`。一套问题对应一个 `set_id`，问题定义与答案都写 `health_profile` 行：`skill_key` / `set_id` / `local_key` / `aspect` / `label` / `hint` / `placeholder` / `max_length` / `sort_order` / `set_generated_at` 同存一行，未答项 `answer=NULL`。与同专项最近一套的题号、标题、提示、aspect 签名相同则更新该套答案；签名变化则新增一套，同一专项最多保留最近 3 套。
- 返回 `created`（新增一套）、`updated`（同套补答案）、`already_exists`（同套同答案不重复写），并带 `skill_key/skill_name/set_id/question_count/answered_count/filled`；成功后图由 `finalize_profile_save` 固定收口并结束本轮，不再回到模型续问，也不自动开始下一个专项。
- 页面 `/profile/health-profile` 只展示已存储的专项套：每套逐题 textarea 直接可编辑，PUT 只接受已存在的 `(set_id, local_key)`；空串清空该题但保留题目；DELETE 清空该用户全部专项档案。页面不再有“未填写问卷 / 只读 / 编辑”三态，也不再展示 9 张空卡。
- `profile_info` 返回 `aspect_questionnaires`（9 个专项，每个含 `latest` 与 `history`）与 `health_profile_meta`；每日建议事实层按每个专项最近一套注入已答问答，不再使用旧的固定题或 `custom_health_profile_*` 字段。

## 六补三、联网搜索工具（web_search，V2.13）

会话页输入框左侧的「联网」按钮按轮开启联网，默认关闭；开启后该轮请求在 `web_search` 字段带 `true`，服务端写入 `config.configurable.web_search`。

- 装配：`app/modules/agent/tools/web_search.py` 的工具只在 `WEB_SEARCH_ENABLED=true` 且配置了 `TAVILY_API_KEY` 时进入图（`runtime.build_user_graph` 在角色白名单过滤之后追加，不受 `tool_grants` 裁剪）；`graph.make_agent_node` 再按本轮开关决定是否 `bind_tools`，未开启时既不 bind，也不写进 `capabilities`。开关随请求生效，不需要重建或重新缓存图。
- 边界：工具从 `RunnableConfig` 读取本轮开关并再次校验总开关与密钥；`query` 2~300 字，`topic ∈ {general, news}`，`days` 仅 `news` 可用且 1~365；结果条数、超时、摘要长度由服务端配置固定，模型不能传 key、URL 或任意参数。
- 结果形态：`{ok, query, result_count, results:[{title, url, content, published_date?}]}`，正文按 `WEB_SEARCH_SNIPPET_CHARS` 截断（下限 200 字）；空结果返回 `result_count=0` 与提示；超时、HTTP 异常与网络异常收敛为 `{ok:false, error}` 固定文案，不抛异常打断本轮。
- 用途边界（提示词 + 代码）：只查平台外部的实时信息（新闻、赛事、天气、价格、政策、机构、产品、公开指南等）；用户个人运动、身材、状态、周期与档案数据仍走平台只读工具。未开启时模型不得假装检索或编造“最新”结论。
- SSE：`tool_start` / `tool_result` 的 `label` 为「联网搜索」、`kind=base`，前端沿用普通只读工具的折叠展示。
- 页面：`GET /agent` 注入 `web_search_available`（开关与密钥齐备），前端据此启用或置灰按钮；开关状态只存在内存，刷新页面回到关闭。

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
- 思考模式：报告走非流式 `json_schema` 结构化输出，服务端在整段 JSON 完成前不返回任何字节，长思考模型会直接顶满读超时（`qwen4-max` 开启思考实测 90~120s，失败耗时约等于 `60s × 2` 次重试，最终在库里只留下 `模型服务暂不可用`）。因此报告链路默认关闭思考（`REPORT_ENABLE_THINKING=False`），经 `get_model(extra_body=...)` 传 `enable_thinking=False`，实测 20~30s；该参数只对 `qwen*` 模型生效，换用其他厂商模型时不传。
- evidence 校验：`evidence` 只能取 `facts.metrics` 中存在的键；无效键删除并记 warnings；一条内容的 evidence 全部无效时整条丢弃，避免编造依据留在页面。

### 7.3 周期与过期

- 周报 = 周一~周日（`monday_of`）；月报 = 自然月 1 日~月末。未结束周期 `period_end` 仍存周日/月末，`as_of=min(end,today)`、`partial=True`，页面标「进行中（截至 X）」；未来周期禁止生成。
- `data_hash` = `facts`（剔除 `as_of`/`partial`）的 SHA-256；周期结束后数据补齐、或用户补录记录导致 hash 变化时，页面标「数据已更新」并可重新生成；旧叙事仍保留为快照。
- 进行中周期的环比只取上期「同期」天数（如 11 月 1–17 日对比 10 月 1–17 日、本周前三天对比上周前三天），卡片文案标「较上期同期」，避免 17 天与整月直接比较造成假涨跌。
- 统计只计 `recorded`，计划单独计数；不做「计划完成率」（planned→recorded 原地改状态，无溯源字段）。热量沿用总览口径只汇总游泳+舞蹈，健身热量单列，`caveats` 与页面口径说明同步写明。
- 周期分析：仅 `gender != 男` 且 `calendar_month(...).overview.has_records` 为真时输出；周跨月按月调 `calendar_month` 合并逐日；真实/推算/预测分开统计，`cycle_note` 必须区分，预测段不得当事实。

### 7.4 自动生成

应用进程内不起 asyncio 循环，改由 `app/modules/system/scheduler/` 的 APScheduler 后台线程触发；任务定义存 `scheduled_jobs` 表，启动时按表重建内存作业：

- `report.weekly`（cron `0 8 * * mon`）生成上周周报（`today - 7` 所在周），`report.monthly`（cron `0 8 1 * *`）生成上月月报（`today.replace(day=1) - 1` 所在月），时区 `Asia/Shanghai`；
- 两条任务都调 `report.service.generate_due`，复用 `scan_due` 的幂等判断（`ready`/`deleted` 跳过；`failed` 且 `attempts >= REPORT_MAX_ATTEMPTS` 不再重试；`generating` 超过 5 分钟视为卡死转 `failed`）；
- **错过不补**：`misfire_grace_time` 默认 300 秒，超时记 `job_runs.status=skipped`；补跑由用户在 `/system/scheduler` 点「立即执行」，或跑不排期的 `report.scan`（忽略 `report_auto_enabled`）；
- **同域互斥**：三条报告任务共用 `lock_scope="report"`，`runner.run_task` 用 `pg_try_advisory_lock(hashtext('report'))` 串行化，周报、月报、兜底扫描不会同时生成；
- 每次执行写 `job_runs`（来源 schedule/manual/cli、结果、耗时、明细），并回写任务的上次结果与累计次数；命令行执行日志 `logs/scheduler.log`；
- **半程报告重写**：若该周期已有 `ready` 报告，但快照里 `facts.partial=true` 而当前周期已结束，扫描仍会命中并带 `force=True` 重写，避免月报停留在月中数据；
- `--dry-run` 只打印到期周期（含 `refresh` 标记）；`--type/--anchor/--user/--force` 可手动生成单个周期。

### 7.5 接口与页面

- 页面 `GET /reports?type=weekly|monthly&anchor=YYYY-MM-DD`；API `GET /api/reports`、`POST /api/reports/generate`、`GET /api/reports/history`、`DELETE /api/reports/{id}`（软删除）。
- 页面结构：4 张事实卡 → 叙事（亮点/留意/下阶段建议/周期视角/数据说明）→ 判断依据 → 历史报告。前端只渲染 facts 与 narrative，不自行算数。hero 右侧只显示生成时间与操作，不展示 `model_name`（该字段仅存库备查，避免历史报告残留旧模型名）。

### 7.6 测试

`tests/test_report.py` 覆盖周期归一（周/月/进行中）、空数据、热量口径、进行中同期对比、周期仅女性有记录、规则模式不调模型、ready 复用与 force、失败保留 facts、软删除与扫描跳过、半程报告周期结束后重写、evidence 清洗、`period_types` 限定与 `generate_due` 摘要；调度器侧（表达式校验、任务 CRUD、执行记录、失败收敛）见 `tests/test_scheduler.py`。

## 八、每日训练建议（V2.8）

并进侧栏「今天」卡（`.today-card`）内的要点判断，位于周期四档标签上方：今天是否适合运动、有氧还是无氧、建议强度、健身练什么部位。与报告同属**离线、单次、无工具、无会话**的结构化调用，区别是周期为一天、产物只有三句自然表达、每天自动生成一次并可手动刷新。

### 8.1 三层结构

1. **事实层**（`app/modules/daily_advice/facts.py`）：确定性计算，复用 body / overview / 三运动 / state_record / cycle 既有口径，输出 `date`、`profile`（性别、年龄、9 个健康档案专项最近一套的已答问答）、`body`（体重/体脂/BMI/腰臀/近 30 天体重差）、`yesterday`、`today_records`、`plans_today`、`recent_load`（近 3/7 天负荷、近 7 天部位分布、近 30 天运动类型次数 `window_30d`、距上次健身）、`state`（今天/昨天/近 3 天各记录项）、`cycle`（女性且有月经记录）、`hard_limits`、`completeness`。其中 `health_profile` 是用户自填的开放式文本，只作模型参考，**不做结构化解析、不参与 `hard_limits` 判定**。
2. **约束层**（`facts._hard_limits`）：代码判定的上限，不依赖提示词；`sanitize` 在模型返回后二次降档，见 8.3。
3. **表达层**（`app/modules/daily_advice/ai.py`）：一次 `invoke_structured`，schema `DailyAdvice`（`verdict` / `focus` / `intensity` / `body_parts` / `text`，`extra=forbid`），模型只解释事实。

### 8.2 口径

- 只计 `recorded` 为已发生；`planned` 只作为当天计划提供给模型，不做完成率、不说「已经练过」。
- 健身时长复用 `overview.service.fitness_minutes(plan)`（`_fitness_minutes` 的公开别名，只转发不改逻辑）；游泳/舞蹈按 `duration_s`。
- `recent_load.recent_parts_2d` 汇总昨天与今天已 `recorded` 的健身部位，作为「最近 2 天练过就今天不再安排」的事实依据；只作提示模型与约束依据，不改写用户当天计划。
- 周期仅 `gender != 男` 且存在月经记录时计算；`build_segments(..., today=day)` 锚定传入日，段来源（真实/当前/补推/预测）写入 facts，预测段不得当事实。
- 身材 30 天体重窗口锚定传入的 `day`，保证 `generate(day != 真实今天)` 与测试可复现。
- 事实层不做任何模型调用；模型固定 `ai_default_model`，不接受页面覆盖。

### 8.3 硬约束与输出清洗

| key | 条件 | 上限 |
| --- | --- | --- |
| `cycle_pain_high` | 今日经期疼痛 ≥2 | 结论 ≤ 克制、强度 ≤ 低、不留力量部位 |
| `cycle_rest` | 周期四档 = 适合休息 | 结论 ≤ 克制、强度 ≤ 低、不留力量部位 |
| `cycle_average` | 周期四档 = 状态一般 | 强度 ≤ 中 |
| `inflammation_high` | 今日炎症 ≥4 | 强度 ≤ 低 |
| `inflammation_mid` | 今日炎症 ≥3 | 强度 ≤ 中 |
| `recovery_low` | 今日恢复 ≤1 | 强度 ≤ 低 |
| `recovery_fair` | 今日恢复 = 2 | 强度 ≤ 中 |
| `yesterday_very_heavy` | 昨日健身容量 ≥8000 或总时长 ≥120 分钟 | 结论 ≤ 克制、强度 ≤ 低 |
| `yesterday_heavy` | 昨日容量 ≥5000 或总时长 ≥90 分钟 | 强度 ≤ 中 |
| `trained_today` | 今日已有 recorded 力量训练 | 结论 ≤ 克制、强度 ≤ 低、不留力量部位 |
| `mood_low` | 今日情绪 ≤1 | 强度 ≤ 中 |

单纯肌肉酸痛**不触发**硬约束：休息只通过 `recent_parts_2d` 做部位避让，由提示词解释为正常训练反应；炎症 0~2（没有或很轻）不因炎症降档；只有炎症偏重、恢复不足、周期四档或多项信号叠加才明显降档。

`sanitize`：强度按 低<中<高、结论按 休息<克制<适合 取更保守值；结论为「休息」时 `focus=恢复` 并清空部位；`focus=恢复` 时清空部位；力量被禁（`block_parts`）时，纯无氧或混合降为有氧并清空部位，纯有氧保留。正文去 HTML，按换行拆行（整段时按句末标点拆），每行去前缀标点后统一加 `- `、去句末句号，并按三句大致上限收口（32 / 36 / 48 字，提示词约为 15~30、20~35、30~45 字，最多 3 行），空正文按失败处理；部位去重、单项 ≤8 字、最多 2 个。

### 8.4 生成流程与幂等

`service.generate(db, user, day=None, force=False)`：算 facts 与 `data_hash` → 已有 `ready` 且 hash 相同且非 force 直接返回 → 写 `generating`（`attempts+1`；`UNIQUE (user_id, advice_date)` 冲突回滚并 409）→ 无任何可用记录走 `mode=rule` 固定文案不调模型 → 否则调模型并 `sanitize` → 写 `ready`（模型名、提示词版本、耗时、完成时间）。模型失败写 `failed` 并保留 facts，接口 502；`generating` 超过 5 分钟视为卡死可重入。

`generate_due(db, day=None, limit=None, check_switch=True)`：只扫 `status=启用` 用户，跳过已 `ready`、`failed` 且达到 `advice_max_attempts`、生成中未超时的行；单用户异常只回滚自己；返回 `{day, scanned, generated, skipped, failed, items}`。

手动刷新：侧栏按钮发 `force=true`，同一行 60 秒内重复请求直接返回已有结果（防连点），之后才真正重算。当天新建计划不触发重算。

### 8.5 定时任务与启动补跑

- `advice.daily`（cron `1 0 * * *`，`lock_scope="advice"`，`EmptyParams`）调 `generate_due`；`advice.scan` 不排期，手动补跑（忽略 `advice_auto_enabled`）。
- 启动补跑：`engine.start_scheduler()` 在 `bootstrap()` 后注册内存一次性 `date` 作业 `advice-catchup`（`now + advice_startup_catchup_seconds`），直接调 `generate_due`，不写 `job_runs`；作业 id 不在注册表，事件回调自动忽略。
- 配置：`advice_auto_enabled`、`advice_timeout_seconds`（默认 30s）、`advice_max_attempts`、`advice_startup_catchup_seconds`（0 表示不补跑）。

### 8.6 接口与前端

- `GET /api/daily-advice?date=`（缺省今天）、`POST /api/daily-advice/regenerate`（body `{date?, force?}`，只允许今天；跨天 400、生成中 409、模型失败 502）。
- 返回 `{date, mode, status, verdict, focus, intensity, body_parts, text, tag, generated_at, error}`，不下发 `facts` / `data_hash`。
- `render_page` 注入轻量对象 `daily_advice`（一次索引查询，异常降级 `None`）；正文并进 `.today-card`，位于 `.d3` 与周期四档标签之间（`.advice-lines`，`white-space: pre-line`），刷新图标在「今天」标题行右侧；`sidebar_advice.js` 只处理刷新与生成中态，不轮询。
- 正文三句按「运动强度 / 运动类型与部位 / 依据」顺序渲染，不写段名小标题；字段 `verdict` / `focus` / `intensity` / `body_parts` 仍随接口下发，供刷新与后续功能使用，但侧栏不再单独展示标签。

### 8.7 测试与降级

`tests/test_daily_advice.py` 覆盖事实组装（男性无 cycle、女性有、仅 recorded 计入、计划与记录分离、近 30 天类型）、各类硬约束、sanitize 降档（含力量被禁→有氧）与要点格式（整段拆行、`- ` 前缀、去句末句号、三句各自字数收口）、rule 模式不调模型、ready 复用与 force、失败保留 facts、generating 409、`generate_due` 开关/limit/失败上限、任务表达式与跨天 400。降级路径：模型失败 → 卡片「未生成」可刷新；无数据 → rule 要点；任务错过 → 启动补跑或手动刷新；男性/无周期 → 正常生成且禁提周期。

## 九、AI 开发契约

1. 新增或修改 AI 功能前，必须先阅读本文件、`docs/ARCHITECTURE.md` 和 `docs/AIplan.md`。
2. 本文件只记录已实现的 AI 架构、功能、工具、接口和开发契约；版本路线、进度和未实现设想写入 `docs/AIplan.md`。
3. 新增工具必须同步更新工具定义、受控查询、注册清单、提示词、前端事件（如有变化）和测试。
4. 数据查询工具必须只读，参数仅限业务字段和受控枚举，不接受模型提供的 `user_id`、SQL、表名或列名。受控写工具与只读工具分离：健身计划工具只能写今日 planned 计划，`user_id` 从 config 注入、日期与状态由代码固定，复用训练模块统一落库逻辑并做防重复；健康档案工具只能写当前专项的一套题，`user_id` 从 config 注入，题数/题号/aspect 属于该专项、至少 1 题有答案、同专项最多 3 套均由代码强制，并复用档案 service。
5. AI 导入必须复用运动模块现有规范化、校验和落库逻辑，不得绕过统一运动契约或新增重复落库路径。
6. 提示词维护按 `AGENTS.md`「提示词维护契约」执行：固定 ID 经 loader 加载、变量与能力声明和代码一致、版本替换后删除无引用的旧文件与映射，并同步本文件；模型注册表与结构化 schema 变更同样确认变量、能力声明与代码一致。
7. 涉及数据库、前端、运动模块或版本进度时，分别按 `AGENTS.md` 同步维护对应文档和代码。
8. AI 测试需覆盖权限隔离、查询工具只读、写工具的校验/落库/防重复、模型异常、结构化校验失败和 SSE 事件；清理模拟数据时不得删除原有数据。
9. 平台技能用代码实现或平台内部声明式 DSL，复用只读工具层并补测试；用户技能只允许提示词，提示词不得成为代码/SQL 入口；任何新增平台声明式数据源、字段或算子都要先更新白名单、校验、执行器、平台只读展示和测试，禁止开放 SQL/代码入口。
10. 技能定义变更或平台技能升级后，`scripts/seed_agent_skills.py` 与 `scripts/schema.sql` 必须保持幂等；运行审计不得写入密码、完整聊天正文或超出技能参数范围的数据。
11. 报告功能（`app/modules/report/`）必须保持「事实层确定性计算、叙事层只解释」的分层：新增指标先加到 `facts.metrics` 并写入提示词可用 key 白名单，再让模型引用；不得让模型直接查库或自行计算。报告生成失败必须保留 `facts`，删除必须走软删除；自动生成只能由 `app/modules/scheduler` 的 cron 任务触发（统一走 `report.service.generate_due`），不得在业务模块里自起循环或另建第二套调度。
12. 每日训练建议（`app/modules/daily_advice/`）同样只允许「事实由代码算、模型只解释」：新增建议维度先进 `facts` 与提示词规则，不得让模型查库；地板约束以 `hard_limits` 表达并在 `sanitize` 强制执行，不得只写在提示词里；生成入口统一 `service.generate` / `generate_due`，定时只能由调度器 `advice.daily` 触发；模型固定 `ai_default_model`；失败保留 `facts`，前端任何异常都不得阻塞页面渲染。
13. 多角色本身只允许影响 system prompt：角色定义固定为 `{schema_version:1, prompt}`，不得加入工具、代码、SQL、数据源或用户可写的授权字段；角色会话创建时固定 `persona_id + version_no`，不提供切换；角色模板与平台角色用 `scripts/seed_agent_personas.py` 幂等维护。角色级工具/技能授权只能由平台管理员在 `/system/personas` 维护，落到 `agent_personas.tool_grants` / `skill_grants`；默认范围仍由服务端 `tools/policy.py` 的 `TOOL_PERSONA_SCOPES` 提供。装配阶段过滤后，被排除的工具不会 `bind` 给模型。
14. 联网搜索（`web_search`）默认关闭，只能由会话页「联网」开关按轮开启：开关状态经 `web_search` 请求字段进入 `config.configurable`，未开启时不得 bind 工具或写入 `capabilities`；密钥、接口地址、结果条数、超时与摘要长度只能来自服务端配置，不接受模型或前端传入；联网结果不得替代平台只读工具查询用户个人数据，未检索到时必须如实说明，不得编造。

## 十、文件索引

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
| 联网搜索工具 | `app/modules/agent/tools/web_search.py` |
| 受控写工具 | `app/modules/agent/tools/action_definitions.py`、`health_profile_actions.py` |
| 受控查询 | `app/modules/agent/tools/queries.py` |
| 健康档案专项 | `app/modules/profile/aspects.py`、`aspect_skills.py`、`questionnaire.py`、`skill_runtime.py`、`service.py`、`app/ai/prompts/profile_aspect_skills_v1.txt` |
| AI 页面 | `app/templates/agent/`、`app/static/js/agent.js`、`agent_skills.js`、`agent_personas.js`、`app/static/css/pages/agent.css`、`agent_skills.css`、`agent_personas.css` |
| 内置角色管理页 | `app/templates/system/personas.html`、`app/static/js/system_personas.js`、`app/static/css/pages/system_personas.css` |
| 技能种子与迁移 | `scripts/seed_agent_skills.py`、`scripts/migrate_agent_skills.py` |
| 角色定义/管理/运行时 | `app/modules/agent/personas/definition.py`、`management.py`、`runtime.py` |
| 角色工具可见性 | `app/modules/agent/tools/policy.py`、`catalog.py` |
| 内置角色管理服务/API/页面 | `app/modules/system/personas/` |
| 内置技能管理服务/API/页面 | `app/modules/system/skills/` |
| 内置技能管理页 | `app/templates/system/skills.html`、`app/static/js/system_skills.js`、`app/static/css/pages/system_skills.css` |
| 内置技能测试 | `tests/test_system_skills.py` |
| 角色种子与迁移 | `scripts/seed_agent_personas.py`、`scripts/migrate_agent_personas.py`、`scripts/migrate_agent_persona_grants.py`、`scripts/migrate_health_profile_aspects.py` |
| 角色模板 | `app/ai/prompts/persona_nutrition_v1.txt`、`persona_e_trainer_v1.txt`、`persona_health_profile_test_v3.txt`、`persona_health_profile_test_guard_v3.txt` |
| 报告事实快照 / 叙事 / 服务 / 模型 | `app/modules/report/facts.py`、`ai.py`、`service.py`、`models.py` |
| 报告提示词 | `app/ai/prompts/weekly_report_v1.txt`、`monthly_report_v1.txt` |
| 报告页面 | `app/templates/report/`、`app/static/js/report.js`、`app/static/css/pages/report.css` |
| 报告迁移与定时任务 | `scripts/migrate_reports.py`、`scripts/generate_reports.py`、`scripts/migrate_scheduler.py`、`app/modules/system/scheduler/`（定时任务定义/执行/管理页） |
| 每日建议事实 / 清洗 / 服务 / 模型 | `app/modules/daily_advice/facts.py`、`ai.py`、`service.py`、`models.py`、`schemas.py` |
| 每日建议提示词 | `app/ai/prompts/daily_advice_v3.txt` |
| 每日建议侧栏 | `app/templates/layout/sidebar.html`、`app/static/js/sidebar_advice.js`、`app/static/css/layout.css` |
| 每日建议迁移 | `scripts/migrate_daily_advice.py` |
| AI 规划 | `docs/AIplan.md` |
