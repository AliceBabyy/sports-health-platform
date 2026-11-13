# AI 架构与开发说明

本文档描述项目当前已实现的 AI 架构、功能、工具和开发契约。AI 版本规划、进度和未实现设想见 [AIplan.md](AIplan.md)；项目宏观架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 一、AI 子模块

AI 能力分为四个逻辑子模块：

1. **模型与运行时**：模型注册、能力声明、提示词加载、LangChain 调用和结构化输出校验，位于 `app/ai/`。
2. **AI 导入**：接收文字和图片，识别健身、游泳、舞蹈记录并复用现有校验和落库逻辑，位于 `app/modules/electronic_trainer/` 及各运动模块的 `ai_profile.py`。
3. **AI Agent**：会话、多轮问答、SSE 流式输出和 checkpointer 持久化，位于 `app/modules/agent/`。
4. **数据问答工具**：面向 Agent 的只读业务查询工具，位于 `app/modules/agent/tools/`。

AI 能力复用现有业务 service 和统计口径，不重复实现业务计算；当前不引入 Redis、pgvector 或新的 AI 业务表。

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

- 页面路径为 `/agent`，API 前缀为 `/api/agent`，模块为 `app/modules/agent/`。
- 当前数据问答图为 `START → agent ⇄ tools → END`；模型通过 `bind_tools` 选择是否进入 `ToolNode`，工具结果以 `ToolMessage` 返回 Agent。
- `recursion_limit=10` 限制循环轮数，`MessagesState` 不扩展。
- 会话元数据存放在 `agent_conversations`；消息由独立 `langgraph` schema 的 4 张 checkpointer 表按 `thread_id` 持久化。
- 前端使用 `fetch` + `ReadableStream` 手动解析 SSE，不使用 EventSource。

### 4.2 会话与流式协议

- SSE 事件包括 `start`、`delta`、`tool_start`、`tool_result`、`done`、`error`。
- 首条消息发送时惰性创建会话；会话支持列表、新建、重命名、硬删除和模型选择。
- `user_id`、会话归属和权限由服务端校验；模型不得指定或伪造用户身份。
- 工具调用期间前端显示查询状态；明细以折叠区展示，最多渲染 50 行。
- 模型失败返回 `error`，前端保留输入内容以便重试。

## 五、只读数据工具

工具定义位于 `app/modules/agent/tools/definitions.py`，受控查询位于 `queries.py`。工具均为只读，不接受模型 SQL，不暴露表名和列名；每次调用使用独立短 session。

| 工具 | 数据范围 |
| --- | --- |
| `get_workout_summary` | 健身、游泳、舞蹈汇总：次数、时长、热量、活跃天数，区分计划和记录 |
| `get_fitness_records` | 健身明细、动作明细、容量、心率、热量和心得 |
| `get_swim_records` | 游泳明细、距离、时长、配速、划频、泳姿和心得 |
| `get_dance_records` | 舞蹈明细、舞种、老师、风格、评分、热量和心得 |
| `get_body_measurements` | 基础、期望、围度、目标四组身材数据及指定指标趋势 |
| `get_state_records` | 食欲、肌肉疼痛、炎症三类状态记录 |
| `get_cycle_records` | 周期参考值、月经记录、派生长度、每日疼痛和当前阶段 |
| `get_profile_info` | 昵称、性别、年龄、账号状态和注册时间，不含密码等敏感字段 |

工具时间范围支持 `days_back` 或 `start_date + end_date`，明细工具支持 `limit`；不传范围参数时查询全部历史。`user_id` 由 `RunnableConfig` 注入，模型不可填写；统计和派生值复用现有业务口径。

## 六、AI 开发契约

1. 新增或修改 AI 功能前，必须先阅读本文件、`docs/ARCHITECTURE.md` 和 `docs/AIplan.md`。
2. 本文件只记录已实现的 AI 架构、功能、工具、接口和开发契约；版本路线、进度和未实现设想写入 `docs/AIplan.md`。
3. 新增工具必须同步更新工具定义、受控查询、注册清单、提示词、前端事件（如有变化）和测试。
4. 工具必须只读，参数仅限业务字段和受控枚举，不接受模型提供的 `user_id`、SQL、表名或列名。
5. AI 导入必须复用运动模块现有规范化、校验和落库逻辑，不得绕过统一运动契约或新增重复落库路径。
6. 提示词、模型注册表和结构化 schema 变更后，必须确认变量、能力声明与实际代码一致，并更新本文件。
7. 涉及数据库、前端、运动模块或版本进度时，分别按 `AGENTS.md` 同步维护对应文档和代码。
8. AI 测试需覆盖权限隔离、工具只读、模型异常、结构化校验失败和 SSE 事件；清理模拟数据时不得删除原有数据。

## 七、文件索引

| 内容 | 文件 |
| --- | --- |
| 模型注册 | `app/ai/models/` |
| 提示词加载与文件 | `app/ai/prompts/` |
| AI 调用与结构化输出 | `app/ai/runtime/` |
| AI 导入编排 | `app/modules/electronic_trainer/ai_import.py` |
| 运动 AI 适配 | 各运动模块 `ai_profile.py` |
| Agent 图与生命周期 | `app/modules/agent/graph.py` |
| 工具定义 | `app/modules/agent/tools/definitions.py` |
| 受控查询 | `app/modules/agent/tools/queries.py` |
| AI 页面 | `app/templates/agent/`、`app/static/js/agent.js`、`app/static/css/pages/agent.css` |
| AI 规划 | `docs/AIplan.md` |
