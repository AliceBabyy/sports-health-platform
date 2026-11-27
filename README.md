# 体序 BODY ALMANAC · 个人健康管理平台（V1）

## V2.0 AI 基础骨架

V2 路线以 `docs/AIplan.md` 为准。已完成模型骨架、三运动的一次性 AI 导入、
**V2.2 基础问答**与 **V2.3 数据问答**。Agent 独立模块 `app/modules/agent/`，页面
`/agent`、API `/api/agent`，基于 LangGraph `StateGraph` + `AsyncPostgresSaver`
checkpointer，支持多会话、多轮对话、SSE 流式与 PostgreSQL 持久化、登录用户隔离。
V2.3 把图升级为工具循环（`agent ⇄ tools`），模型按需调用 8 个**只读工具**查询现有
业务表后基于事实回答，不新建表、不写数据。**V2.4 技能系统**已实现平台代码/声明式技能、用户私有
提示词技能、斜杠自然语言触发、参数解析与追问续接、技能管理页和运行审计；**V2.4 多角色**已实现
3 个平台内置角色（营养师、电子私教、健康档案测试）与用户自定义提示词角色，按「一整个会话归属一种角色」创建，
会话内不可切换；管理员可在「系统设置 → 内置角色」中增删改查内置角色并勾选工具/技能。后续建设 LangGraph Store 跨会话画像（V2.5）和暂停追问后恢复（V2.6）。

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
未测量日期不补值）、`get_state_records`（食欲/肌肉疼痛/炎症/情绪/恢复）、`get_cycle_records`
（参考值 + 月经记录 + 每日疼痛与 note + 今日阶段）、`get_profile_info`（昵称/性别/年龄 + 9 个专项档案的最近一套与最近 3 套历史 + `filled/set_count/skill_count`，不含密码）。
取数范围由模型按用户意图决定：`days_back`、`start_date + end_date`、`limit` 均可选，
**不传任何范围参数即取全部历史**，已移除原 366 天 / 20 条硬上限；一次拉全量或只拉最近几次
都由意图决定。`user_id` 经 `RunnableConfig` 服务端注入、模型不可填，工具内部用独立短 session；
工具全部只读、不接受模型 SQL，参数只保留日期范围、条数与枚举。SSE 新增
`tool_start/tool_result`（`stream_mode=["messages","updates"]`），气泡显示“正在查询…“，
回答为汇总 + 关键依据、明细折叠（最多渲染 50 行）。本版无数据库结构变更、不引入 Redis/pgvector。

**V2.4 技能系统（2026-11-16，提示词技能 2026-11-17 补齐）**：平台技能只读、可版本化，支持代码实现
（`lose_weight_analyse` 减重分析、`recent_swim_review` 游泳复盘）和平台内部声明式 DSL；声明式
只作为平台能力维护，不对用户开放创建或编辑。用户技能私有，只支持提示词：保存 1~4000 字指令，
作为工具结果 `summary` 交给模型遵循，不取数、不嵌套第二次模型调用。用户可输入 `/技能名 自由文本`
触发，服务端按 key/name/alias 匹配；平台声明式缺参数自动追问，下一条普通文本会合并原命令继续；
提示词技能不抽参数、不追问。对话页输入 `/` 会浮出可用技能建议，按名称/键/别名过滤并支持键盘插入。
管理页 `/agent/skills` 挂在「AI助手」分组，整页白底铺满，提供平台/我的技能列表、用户提示词编辑、
平台声明式只读展示、校验、发布、停用、删除、试运行和运行记录。数据层新增 `agent_skills` /
`agent_skill_versions` / `agent_skill_runs`，`scope-kind` 联合约束为：平台 `code/declarative`，
用户 `prompt`。迁移 `python scripts/migrate_agent_skills.py`，种子 `python scripts/seed_agent_skills.py`。
SSE 工具事件新增 `label/kind/origin/version/skill`；技能轨迹与输出表已在 `/agent` 页面接通，
提示词技能折叠区只显示指令已加载。

**V2.4 多角色（2026-11-18）**：对话页「新建会话」旁新增「新建角色会话」，点击弹出角色选择弹窗（显示名称、来源与定位），从启用且已发布的角色中
选择（平台内置营养师 `nutrition`、电子私教 `e_trainer`、健康档案测试 `health_profile_test`，以及用户自定义角色）。角色会话创建时把
`persona_id + persona_version_no` 一并落库，整段会话固定该角色、不提供切换；侧栏显示角色名徽标，
历史消息与 SSE `done` 均携带角色快照。角色定义只提供提示词（`agent_chat.v8` 末尾「角色设定」+
「规则优先级（最高）」）；工具/技能默认范围由服务端 `TOOL_PERSONA_SCOPES` 提供，管理员可在
`/system/personas` 给内置角色配置显式 `tool_grants` / `skill_grants` 白名单（`NULL` 表示沿用默认范围，空数组表示不使用），
装配阶段按白名单过滤。角色改版后老会话仍读创建时版本。普通用户角色管理页
`/agent/personas` 挂在「AI助手 → 角色管理」，平台角色只读，用户角色只写名称、定位与提示词，保存即
生成新版本并生效，支持启停与删除（被会话引用时先删会话）。管理员内置角色页 `/system/personas` 支持新建、编辑、
删除、排序、启停、恢复默认范围，接口统一为 `/api/system/system-personas`，自动受管理员门禁保护。数据层新增 `agent_personas` /
`agent_persona_versions` 与 `agent_personas.tool_grants / skill_grants` 两列，会话表增加两列。迁移
`python scripts/migrate_agent_personas.py`、`python scripts/migrate_agent_persona_grants.py`，种子 `python scripts/seed_agent_personas.py`。

**健康档案专项技能（2026-11-26 重构）**：平台内置 `health_profile_test` 角色，健康档案拆成 9 个专项，每个专项一个平台代码技能：
`profile_goal`（目标）、`profile_diet`（饮食）、`profile_exercise`（运动）、`profile_sleep`（睡眠）、
`profile_lifestyle`（生活方式）、`profile_cycle`（生理期，仅女性）、`profile_posture`（形体矫正）、
`profile_medical`（伤病）、`profile_extra`（档案补充）。9 段提示词合并在
`app/ai/prompts/profile_aspect_skills_v1.txt`，由 `loader.py` 按固定 section ID 加载；题目不写死注册表，
模型每次在专项提示词约束下生成 3~6 题并逐题调用 `ask_user`，全部问完后调用
`save_health_profile_aspect(skill_key, questions, answers)` 静默写入。保存成功后图进入
`finalize_profile_save` 固定结束本轮，不自动开始下一个专项。
`health_profile` 已重置为“一套专项问题多行、一行一道题”：字段为
`set_id / skill_key / aspect / local_key(q1~q6) / label / hint / placeholder / max_length / answer / sort_order / set_generated_at`，
唯一约束 `(user_id,set_id,local_key)`，同一专项最多保留最近 3 套。页面 `/profile/health-profile`
只展示已存储的专项套，逐题 textarea 直接编辑，空串清空该题，DELETE 清空全部；不再有固定问卷、
查看/编辑两态或 9 张空卡。`get_profile_info` 返回 9 个专项的最近一套与最近 3 套历史。
9 个专项 skill 与保存工具只授权给 `health_profile_test`，是运行时硬边界，其他角色只保留 `get_profile_info` 只读，不能通过角色白名单绕过。重置迁移
`python scripts/migrate_health_profile_aspects.py`（仅允许在原表 0 行时执行）；种子
`python scripts/seed_agent_skills.py` 与 `python scripts/seed_agent_personas.py`。


**V2.12 内置技能管理（2026-11-24）**：系统设置新增「内置技能」页 `/system/skills`，管理员可统一查看平台
`scope=system` 的代码/声明式技能。代码技能定义由代码注册，页面只读且仅可启停；声明式技能支持新建、编辑、
校验、版本化保存、试运行、启停与删除。定义变化生成 `agent_skill_versions` 新版本并立即生效；保存/启停/删除后
重建常驻系统图并清空按用户图缓存，无需重启。被内置角色显式 `skill_grants` 引用的技能禁止删除（409），避免
角色配置静默失效。API 统一为 `/api/system/system-skills`，自动受管理员门禁保护；种子脚本只补代码技能元数据，
不覆盖管理员设置的启停状态。测试 `tests/test_system_skills.py`。

**V2.13 联网搜索（2026-11-24）**：会话页输入框底行新增「联网」开关，默认关闭，开启后只对下一轮生效（发送、重新生成、
续写与中途作答都携带该开关）。后端 `app/modules/agent/tools/web_search.py` 封装 Tavily `/search`，只有服务端配置
`TAVILY_API_KEY` 且 `WEB_SEARCH_ENABLED=true` 时才装配工具；未开启那轮既不 `bind_tools`，也不写进 `capabilities`，
模型无法假装检索。`query` 2~300 字、`topic ∈ {general, news}`、`days` 仅 news 且 1~365；结果条数、超时与摘要长度
全部由服务端配置固定，模型不能传密钥、地址或任意参数。检索结果含标题、链接、摘要与可选发布时间，回答需保留来源；
超时、HTTP 异常与空结果收敛为结构化错误，不打断本轮。工具不受角色 `tool_grants` 裁剪，开关随请求生效，无需重建图。
提示词升级为 `agent_chat.v8`（新增「联网搜索：只在开启时可用」一节，删除 v7 文件与映射）。配置见
`WEB_SEARCH_ENABLED`、`TAVILY_API_KEY`、`TAVILY_SEARCH_URL`、`WEB_SEARCH_TIMEOUT_SECONDS`、`WEB_SEARCH_MAX_RESULTS`、
`WEB_SEARCH_SNIPPET_CHARS`；测试 `tests/test_agent_web_search.py`。

**V2.9 对话中途提问（2026-11-18）**：AI 可在回答中途调用 `ask_user` 停下来提问（问题 + 最多 4 个选项，
可多选，也可跳过），用户作答后从同一轮继续，不必重新解释请求。停点由 LangGraph `interrupt()` 与 Postgres
checkpointer 承载；作答仍走 `POST .../messages`，服务端识别到挂起后以 `Command(resume=答案)` 恢复，
问答与后续正文留在原轮次，刷新页面后卡片仍可继续作答。等待回答期间不可重新生成。提示词升到
`agent_chat.v7`（现为 `v8`），新增 SSE `ask` 事件。

**V2.10 中断生成与续写（2026-11-19）**：流式生成期间发送按钮就地变为停止按钮（方形图标 + 深色底），再次点击即中断
本轮；前端用 `AbortController` 立即断开 SSE，并调用 `POST /api/agent/conversations/{id}/messages/stop` 交给服务端收口。
服务端把已流出正文作为一条带 `interrupted` 标记的 AI 回答保留，回滚“工具调用没配齐结果”的尾部消息（已完成的工具
轨迹保留），8 秒内未收尾则释放占位，避免会话被永久锁住。中断后可点「继续」，或直接发“继续/接着/continue”：
`POST .../messages/continue` 不新增用户消息，以 `run_mode=续写` 在原轮次接着写（不重复、不重开场），也可改用「重新生成」
整段重写；刷新后由历史消息的 `interrupted` 标记恢复「继续」。中断只结束会话消息，不撤销已落库的业务写入。提示词
`agent_chat.v7` 新增 `{run_mode}` 变量（现为 `v8`）。

**V2.5 AI 运动报告（2026-11-17）**：新增 `/reports` 单页（周报/月报 tab 切换），侧栏挂在
「运动训练/计划」第四项，总览页顶部提供周报/月报入口。三层结构：事实层由代码确定性计算
（三运动次数/时长/热量、身材实测变化、状态记录、生理周期阶段，月报另有周节奏与环比），
叙事层由一次结构化模型调用写 headline/summary/亮点/留意/建议/周期视角，依据层直接展示
事实快照，叙事的 `evidence` 只能引用真实指标 key。统一 `reports` 表（`period_type` 区分周/月），
`(user_id, period_type, period_start)` 唯一，`data_hash` 做过期检测，删除为软删除。周报=周一~周日，
月报=自然月；未结束周期标「进行中（截至 X）」。空数据不调模型、走规则文案。迁移
`python scripts/migrate_reports.py`。

**V2.7 应用内定时任务（2026-11-17）**：新增 `app/modules/scheduler/`（2026-11-19 并入 `app/modules/system/scheduler/`）与 `/system/scheduler` 管理页
（侧栏「系统设置 → 定时任务」），用
APScheduler 后台线程替代原「Windows 任务计划程序每 30 分钟跑 CLI」方案。任务定义存 `scheduled_jobs`
（唯一事实源，启动按表 reconcile 重建内存作业），支持 cron / date / interval 三种触发（cron 为标准
五段式，星期只写 mon~sun）；执行记录写 `job_runs`（定时 / 手动 / 命令行三种来源）。默认任务
`report.weekly`（周一 08:00 生成上周周报）与 `report.monthly`（每月 1 日 08:00 生成上月月报），
`report.scan` 不排期、供手动兜底。错过执行窗口不补跑（宽限 300 秒记 skipped），在页面「立即执行」
手动补齐。迁移 `python scripts/migrate_scheduler.py`。

**V2.8 侧栏每日训练建议（2026-11-17，2026-11-26 调整权重）**：左侧菜单栏「今天」卡内、周期四档标签上方常驻三句由默认模型
生成的自然表达（运动强度与总体判断 / 按近 30 天运动类型偏好推荐类型与部位 / 依据，约 15~30、20~35、30~45 字，每行以 `- ` 开头、句末不带句号）——今天
是否适合运动、有氧还是无氧、建议强度、健身练什么部位。事实层全部由代码算（基础信息、身材、
昨日三运动、近 3/7 天负荷与近 30 天类型次数、状态记录含恢复、当天计划、女性当天周期），模型只负责解释；经期疼痛、周期
休息/状态一般、炎症、恢复、昨日负荷、今日已练力量、情绪等硬约束由代码判定并在模型输出后强制降档（`sanitize`）；单纯肌肉酸痛不触发降档，只做部位避让。
每天 00:01 由应用内调度器 `advice.daily`（cron `1 0 * * *`）生成当天一份，启动后按
`ADVICE_STARTUP_CATCHUP_SECONDS` 补跑缺失行；「今天」标题行右侧刷新按钮可手动重算（60 秒防连点）。一天一条，
`(user_id, advice_date)` 唯一，无软删除；空账号走 `mode=rule` 固定要点不调模型。接口
`GET /api/daily-advice`、`POST /api/daily-advice/regenerate`；迁移 `python scripts/migrate_daily_advice.py`。

安装依赖：`uv sync --extra dev`。

SSR 单体应用：**FastAPI + Jinja2 + SQLAlchemy + PostgreSQL**，端口 **8010**（避开 8000）。

V1 范围：注册/登录认证 + 模块（身材数据 BD / 状态记录 SR / 健身训练 TR / 游泳 SW / 舞蹈 DA / 生理周期 MC / 个人信息 PR）。

健康档案（2026-11-26 专项化重构）：侧栏「个人信息」分组新增子页 `/profile/health-profile`，只展示已存储的专项套，每个专项最近一套、题目标题 + 自适应高度 textarea 直接编辑，页头「清空档案」、底部「保存」。题目由「健康档案测试」角色按 9 个专项（目标/饮食/运动/睡眠/生活方式/生理期/形体矫正/伤病/补充）在对话中生成，每套 3~6 题；`health_profile` 按 `set_id` 分套、一行一道题，字段 `set_id / skill_key / aspect / local_key / label / hint / placeholder / max_length / answer / sort_order / set_generated_at`，唯一约束 `(user_id,set_id,local_key)`，同一专项最多保留最近 3 套。文本不做结构化解析，只作 AI 每日建议与 Agent 只读工具的参考，不参与代码硬约束。现有库运行 `python scripts/migrate_health_profile_aspects.py`（仅原表 0 行时执行）。

账号注销：个人信息页可退出登录，或在输入当前密码后选择“注销但保留数据”（users.status=停用，禁止登录）和“注销并清除所有数据”（删除用户及所有关联记录）。停用账号可在注册页勾选恢复并凭同名账号、原密码恢复原 user_id 和数据。管理员角色已用于 `/system` 管理区（定时任务、内置角色、内置技能）；停用账号的恢复与清除仍通过受控数据库操作。现有库运行 `python scripts/migrate_user_status.py` 增加状态列。
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
ADMIN_USERNAMES=<可选，逗号分隔的管理员登录名；留空则由库里 id 最小的启用账号担任>
SECRET_KEY=<随机生成，勿提交仓库>
```

### 3. 建表 + 初始化账号

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
# 可选参数：--username <名> --password <密码> --display-name <昵称>，默认 admin / admin123
# 已有库补结构：python scripts\migrate_reports.py（AI 运动报告表）
#              python scripts\migrate_scheduler.py（定时任务两表 + 默认周报/月报任务）
#              python scripts\migrate_role.py（users 角色列 + 首个管理员回填）
#              python scripts\migrate_daily_advice.py（每日训练建议表）
#              python scripts\migrate_agent_persona_grants.py（内置角色工具/技能白名单两列）
```

### 3.1 AI 运动报告自动生成（可选）

周报/月报由应用内调度器自动触发（服务启动即注册，无需操作系统计划任务）；`/system/scheduler` 管理页（仅管理员可见，`/system` 与 `/api/system` 前缀统一由管理员门禁拦截）可改表达式、启停与立即执行。手动补跑：

```powershell
# 试运行（只列出到期周期，不调模型）
.\.venv\Scripts\python.exe scripts\generate_reports.py --scan --dry-run
# 补跑上周周报与上月月报（与页面「立即执行」同一路径，写 job_runs 留痕）
.\.venv\Scripts\python.exe scripts\generate_reports.py --scan
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
# 单元测试（趋势聚合 / 配速划频 / 周期阶段 / 训练状态机 / 总览聚合 / 个人信息 / 健康运动档案 / Excel 导入 / 状态记录 / AI 运动报告 / 每日训练建议）
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
│  │  ├─ body/             # 身材数据：4 表拆分 upsert + 未填继承 + 五档趋势 + BMI + 剪影 + Excel 导入/导出
│  │  ├─ training/         # 训练计划（「完成训练」一键转记录）/历史 + Excel/JSON 导入
│  │  ├─ swim/             # 游泳记录/计划 + 配速/划频计算 + 单日视图 + Excel/JSON 导入
│  │  ├─ dance/            # 舞蹈记录/计划 + 舞种汇总 + 单日视图 + Excel/JSON 导入
│  │  ├─ overview/         # 运动训练/计划总览：日/周/月聚合 + 单日详情（2026-11 新增）
│  │  ├─ cycle/            # 生理周期：七阶段推算 + 月历 + 疼痛 / note + 全部记录
│  │  ├─ state_record/      # 状态记录：食欲/肌肉疼痛/炎症/情绪/恢复五表按天记录 + 月历阶段归并 + 跨表批量删除
│  │  ├─ report/           # AI 运动报告：周/月事实快照 + 叙事 + 软删除 + 自动生成（页面 /reports）
│  │  ├─ daily_advice/     # 每日训练建议：今天卡内要点判断 + 硬约束降档 + 00:01 定时生成（/api/daily-advice）
│  │  ├─ system/           # 系统管理区：聚合 /system 页面与 /api/system API；scheduler/ 定时任务、personas/ 内置角色 CRUD + 工具/技能白名单
│  │  ├─ profile/          # 个人信息：基本资料 + 修改密码（复用 users）+ 健康档案（health_profile 专项套）
│  │  └─ agent/            # AI 助手：LangGraph 图 + checkpointer 生命周期 + 会话 service/SSE（页面 /agent）
│  ├─ templates/           # Jinja2（base/侧栏/各模块页面 + auth/register + profile）
│  ├─ static/              # css / js / vendor(echarts) / img
├─ scripts/
│  ├─ init_db.py           # 建表 + 账号幂等
│  ├─ migrate_training_multi_plan.py  # 2026-11：训练一日多计划（删唯一约束、加联合索引，幂等）
│  ├─ migrate_sport_contract.py # 三运动统一表、字段、外键（幂等）
│  ├─ migrate_plan_status.py  # 2026-11：swim/dance 加 status、记录列转可空（幂等）
│  ├─ migrate_remark.py       # 2026-11：三表加 remark、swim/dance 移除 plan_text（幂等）
│  ├─ migrate_notes.py        # 2026-11：training_notes 扩四字段心得 + 新建 swim_notes/dance_notes
│  ├─ migrate_swim_avg_stroke_rate.py # 2026-11：swim_records 加 avg_stroke_rate（幂等）
│  ├─ migrate_state_record.py   # 2026-11：状态记录五表（state_ 前缀，食欲/肌肉疼痛/炎症/情绪/恢复）建表 + 注释（幂等）
│  ├─ migrate_state_table_prefix.py # 2026-11-17：状态记录四表旧名加 state_ 前缀，同步约束/索引/序列改名（幂等）
│  ├─ migrate_reports.py        # 2026-11：AI 运动报告 reports 表 + 注释（幂等）
│  ├─ migrate_scheduler.py      # 2026-11：定时任务 scheduled_jobs/job_runs 两表 + 注释 + 默认任务（幂等）
│  ├─ migrate_daily_advice.py   # 2026-11：每日训练建议 daily_advice 表 + 注释（幂等）
│  ├─ generate_reports.py       # 报告生成 CLI：--scan 手动补跑上周周报/上月月报（与页面「立即执行」同路径）
│  └─ schema.sql           # 全量建表 DDL（整改后结构，含中文 COMMENT 段）
└─ tests/                  # pytest 单测（含运动契约、总览聚合与 AI 运动报告）
```

## 需求口径（锁定实现）

- 配速 pace = duration_s ÷ distance_m × 100 ÷ 60，保留 1 位；划频 = total_strokes ÷ (duration_s ÷ 60)
- BMI = 体重kg ÷ 身高m²，健康区间 18.5~23.9
- 身材数据为 4 张拆分表（基础/期望/围度/目标围度），每表 (user_id, record_date) 唯一；
  页面默认显示记录日期最新一条；4 个分类添加按钮分别写入对应表；
  新增记录未填字段自动沿用该字段最近一次非空值；同日同组重复保存只覆盖当日已提交字段；「全部记录」按日期合并 4 组，列为日期、身高、体重、体脂率、臂围、胸围、腰围、臀围、大腿围、小腿围、操作
- 趋势五档：week=本周周一~周日 7 点当日值；month=本月每日；two_month=最近 60 天（含今天）逐日当日值；half_year=近 6 个月每月 1/10/20 号、窗口 [锚点-10 天,锚点] 11 天均值；year=近 12 个月每月 1/15 号、窗口 [锚点-15 天,锚点] 16 天均值；无记录断线不插值；基础+围度 11 维可趋势，目标值不参与
- 训练负荷宽松化：动作名称必填，部位/重量/组数/每组个数可空；每组个数为字符串（如 "10+8+6"），容量 = Σ 重量×组数×个数首段数字；期望突破重量计划/记录均可填；重量与目标重量（含身材体重/目标体重）取任意数值、保留两位小数，不做范围限值（仅组数 1~99）
- 新运动模块的统一必填项：计划态和记录态均需日期；其他必填业务字段及默认展示以 [`SPORT_MODULE_GUIDELINES.md`](docs/SPORT_MODULE_GUIDELINES.md) 的需求确认清单为准，现有三模块规则不直接套用于新模块。
- 三运动页共用可收缩双栏；表格宽于卡片时只在表格区域横向滚动，健身动作表和编辑弹窗的动作字段同样如此。
- 弹窗填写框（2026-11-10 统一）：所有弹窗内的多行文本框随内容行数自动增高，初始高度由 `rows` 决定，长到 `min(300px, 42vh)` 后在框内滚动；删空内容会缩回初始高度。实现见 `app/static/js/common.js` 的 `autoGrowTextareas` 与 `app/static/css/base.css` 的 `.modal textarea`。
- 七阶段（2026-11-12 分段推算）：月经记录只存起止日期——经期长度 = 结束日 − 开始日 + 1（未填结束日为 null），周期长度 = 下一条记录开始日 − 本条开始日（无下一条为 null），两个值均实时派生、不落库；阶段以「段」为唯一计算单元，段内排卵日 = 段长 − 14（黄体固定 14 天），卵泡期随段长伸缩；排卵后 1~2 天排卵后期、3~6 天黄体前期、7~10 天黄体中期、11~14 天黄体后期
- 运动四档：排卵期前期/排卵日/排卵后期为精力旺盛；黄体前期及黄体中期前 2 天为状态良好；黄体中期余下日期及黄体后期前 2 天为状态一般；黄体后期余下日期及经期前 3 天为适合休息；经期第 4 天状态一般、第 5 天起状态良好。疼痛 ≥2 优先覆盖为适合休息
- 段长规则：相邻首日间隔 < max(22, 参考周期 + 15) 拒绝保存并提示疑似同一次月经；22~45 天为真实段；46~90 天判为漏记，按参考周期等分成 k 段补推（k 取使每段最接近参考周期且落在技术下限~45，余数摊到前面几段）；>90 天不补推，两段之间留白并提示漏记超过 3 个月
- 预测边界：只推最新记录后的当前段与一个预测段，再往后留白；最新段逾期 7 天内仍标「预测经期」，超过 7 天转「未推算 + 建议补录」；0 条记录完全不推，1 条记录按参考值铺当前段 + 预测段
- 周期参考值：`period_setting` 单行，只用于当前段、预测段、补推段和未填结束日的记录；参考周期 22~45（默认 28）、参考经期 2~8（默认 5），且需满足 经期 + 15 ≤ 参考周期；页面「周期参数」按钮单独修改，记录变动不再改写它
- 经期三态：recorded 经期（真实记录窗口）、inferred 推算经期（漏记补推段）、predicted 预测经期（未来段），月历以边框样式区分，详情注明「本段无记录，阶段按参考周期推算」
- 周期页面：月历标识真实记录首日，可新增、编辑、删除月经记录（表单只收起止日期）；「全部记录」用分段控件在月经记录 / 周期日志间切换，日志分页展示日期、疼痛、所属经期与 note；疼痛独立记录，填写入口只在 recorded 经期出现（推算经期、预测经期不填），保存后同步刷新运动等级；侧栏「今日」小卡保留，今天无段显示「未推算」；三运动页周期联动已移除
- 周期日志（2026-11-17）：`period_logs` 一天一行；`pain_level` 可空且仅 recorded 经期可写，写入时归属 `period_id`（对应 `period_records.id`）；`note` 每天可写，非经期日写 note 时 `pain_level` / `period_id` 置 null；页面右侧详情下方新增「今日 note」小卡，读写该表 `note` 字段
- 阶段激素文案（2026-11-17）：七阶段各两份，按阶段天数 n 取前 floor(n/2) 天用前段、其余用后段（n=1 只用前段）；单份 ≤70 字、两句话各占一行（上行客观激素状态，下行对心情 / 食欲 / 运动表现的影响）；详情只展示「激素水平」，「运动建议」已移除
- 字体与渲染（2026-11-11）：全局字体逐字照搬 GitHub 原栈（`-apple-system → Segoe UI → Noto Sans → Helvetica/Arial → sans-serif → emoji`），中文走系统默认兜底（本机实测即微软雅黑，与显式雅黑差约 1.5%）；全局 `letter-spacing: .03em` 放宽字距（中文在雅黑下偏挤显扁）；同时不使用 `-webkit-font-smoothing: antialiased`，避免 Windows 关闭 ClearType 导致小字发虚
- 周期配色：日历格底色只按四档状态显示浅蓝绿、浅绿、浅黄、浅粉；阶段保留文字标签，图例与详情使用同一状态配色；窄屏月历保留两字状态名（旺盛/良好/一般/休息）；四档底色（2026-11-11）统一向白混合 50% 再浅一档，圆点与文字深阶保持不变
- 心得（三表均 1:1 挂记录、仅记录态可填）：共有 `rating/notes`，健身另有 `best_movement/next_steps`，游泳另有 `stroke_insight`，舞蹈另有 `video_effect`；页面字段称呼维持现状
- 状态记录（2026-11-11 建立，2026-11-26 新增恢复，非运动模块）：食欲 / 肌肉疼痛 / 炎症 / 情绪 / 恢复五项各一张表，同类同一天一行（重复新建 409）；字段仅日期、星级（0~5 可空；0=明确最低分，null=未评显示 —）、描述（≤255 可空），无计划态/起止时间/时长/心率/热量，不套运动契约。类型键、中文标签与模型映射集中注册在 `models.py`，页面筛选项与编辑弹窗从服务端类型表生成；跨五表列表在 service 内存合并分页（日期倒序、id 倒序），支持类型筛选；月历复用周期七阶段推算并归并经期/卵泡·排卵/黄体三档圆点，男性或无周期记录时阶段置空；跨表批量删除每条自带类型定位表。新增记录项的完整开发契约见 [`STATE_RECORD_GUIDELINES.md`](docs/STATE_RECORD_GUIDELINES.md)。性别开放（男女均可记录），无 Excel/JSON/AI 导入入口。页面自上而下三张卡片（月历 / 当日状态 / 全部记录）纵向堆叠、内容随卡片宽度自适应铺满；当日五项就地填写（桌面双列每行 2 项、窄屏单列；内联星级 + 描述 + 保存，有记录可块内删除），全部记录列表行内编辑才弹出表单弹窗。页面 `/state-record`，API `/api/state-record`

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




