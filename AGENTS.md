# sports-health-platform 唯一约定

## 一、文档入口与使用规则

`AGENTS.md` 是项目开发规则的唯一入口：先按任务类型查阅对应文档，再实施修改；详细实现内容写入对应文档，不在本文件重复展开。

| 任务 | 开始前阅读 | 修改后维护 |
| --- | --- | --- |
| 任意功能或模块 | `docs/ARCHITECTURE.md` | `README.md`、`docs/ARCHITECTURE.md`、`scripts/schema.sql`、`docs/数据库建表设计.md` |
| AI 功能 | `docs/ARCHITECTURE.md`、`docs/AI_ARCHITECTURE.md`、`docs/AIplan.md` | `docs/AI_ARCHITECTURE.md`；版本进度维护 `docs/AIplan.md`；并同步上述通用文档 |
| 前端页面、样式或交互 | `docs/ARCHITECTURE.md`、`docs/FRONTEND_GUIDELINES.md` | `docs/FRONTEND_GUIDELINES.md`，并同步上述通用文档 |
| 运动模块 | `docs/ARCHITECTURE.md`、`docs/SPORT_MODULE_GUIDELINES.md`、`docs/数据库建表设计.md` | `docs/SPORT_MODULE_GUIDELINES.md`、`docs/ARCHITECTURE.md`、`docs/数据库建表设计.md`、`scripts/schema.sql`，并同步 `README.md` |
| 状态记录（新增或修改记录项） | `docs/ARCHITECTURE.md`、`docs/STATE_RECORD_GUIDELINES.md`、`docs/数据库建表设计.md` | `docs/STATE_RECORD_GUIDELINES.md`、`docs/ARCHITECTURE.md`、`docs/数据库建表设计.md`、`scripts/schema.sql`、`scripts/migrate_state_record.py`、`docs/API_REFERENCE.md`，并同步 `README.md` |
| 数据库表或字段 | `docs/数据库建表设计.md`、`docs/ARCHITECTURE.md` | `docs/数据库建表设计.md`、`scripts/schema.sql`，并维护数据库 `COMMENT` 注释 |
| 任意 HTTP 接口（新增、删除、改字段或改权限） | `docs/API_REFERENCE.md`、`docs/ARCHITECTURE.md` | `docs/API_REFERENCE.md`（同步模块表与计数）；涉及模块职责时同步 `docs/ARCHITECTURE.md` |

1. `docs/ARCHITECTURE.md` 只记录已实现的系统结构、功能和约束，不记录未实现内容或设计设想。
2. `docs/AIplan.md` 只在 AI 功能发生改动时维护；前端和运动模块分别按对应规范文档维护。
3. 项目根目录只保留 `README.md`、`AGENTS.md` 和代码；所有项目说明文档统一放在 `docs/`。
4. 项目内所有地方都不得放置预览文件、测试文件、设计草稿、设计文档、临时文件等无关冗余文件，尤其是生成的设计稿之类。

## 二、AI 开发契约

1. AI 功能分为模型与运行时、AI 导入、AI Agent、数据问答工具四个逻辑子模块；开发前阅读 `docs/AI_ARCHITECTURE.md`，项目级影响同时核对 `docs/ARCHITECTURE.md`。
2. `docs/AI_ARCHITECTURE.md` 只记录已实现的 AI 架构、功能、工具、接口和开发契约；`docs/AIplan.md` 只记录版本规划、进度和未实现设想。
3. 新增或修改 AI 功能后，必须同步维护 `docs/AI_ARCHITECTURE.md`；涉及版本进度时同步 `docs/AIplan.md`；涉及数据库、前端或运动模块时，分别同步对应文档和代码。
4. 新增 AI 工具必须同时更新工具定义、受控查询/写入逻辑、注册清单、提示词、前端事件（如有变化）和测试。数据查询工具必须只读，不接受模型提供的 `user_id`、SQL、表名或列名；受控写工具须与只读工具分离、边界由代码强制（身份从 `RunnableConfig` 注入、日期/状态由代码固定、动作经 Pydantic 严格校验、复用运动模块统一落库逻辑并做防重复），不依赖提示词约束。
5. AI 导入必须复用运动模块现有的规范化、校验和落库逻辑，不得绕过统一运动契约或新增重复落库路径。
6. 提示词维护契约：
   - 提示词统一以 `.txt` 存放在 `app/ai/prompts/`，不在代码中硬编码大段提示词；新增提示词必须在 `loader.py` 的 `PROMPTS` 注册 ID 与文件映射，只能经 loader 按固定 ID 加载，不接受任意文件路径。
   - 提示词内的 `{变量}` 必须与调用点传入的变量集合完全一致（loader 已强制校验），增删变量时同步修改调用点；提示词列出的工具、能力和数量必须与实际注册一致，不写不存在的工具。
   - 版本号采用「名称.版本」（如 `agent_chat.v4`）；新版本启用、旧版本确认无引用后，必须同时删除其 `.txt` 文件与 `PROMPTS` 映射，删除前全项目搜索确认无调用，不保留死文件。
   - 测试提示词、无引用提示词、废弃提示词要进行清理
   - 提示词变更影响 AI 行为时同步 `docs/AI_ARCHITECTURE.md`，涉及版本进度同步 `docs/AIplan.md`；模型注册表与结构化 schema 的变更，同样确认变量、能力声明与代码一致。
7. 技能开发契约：
   - 平台技能只能 `scope=system`、`kind=code` 或 `kind=declarative`，普通用户在 `/agent/skills` 只读；管理员可在 `/system/skills` 维护平台技能：代码技能定义由代码注册、仅可启停，声明式技能可新建、编辑、版本化与删除。用户技能只能 `scope=user`、`kind=prompt`，仅创建者可见，禁止开放代码、SQL、表名或列名。声明式 DSL 只作为平台内部能力维护，不对用户开放创建或编辑。
   - 新增平台声明式数据源、字段或算子时，必须同步更新白名单、DSL 校验、执行器、平台只读展示和测试；任何绕过白名单的执行路径都不得合入。
   - 技能管理页路由为 `/agent/skills`，必须复用登录门禁与用户归属校验；平台技能对普通用户只读，用户技能越权返回 403；用户技能页只提供提示词编辑。管理员内置技能页为 `/system/skills`，统一走 `/api/system/system-skills`，自动受管理员门禁保护。

## 三、数据库与数据安全

1. 发生数据层改动时，自行查找数据库连接信息，执行必要 SQL，并完成数据库维护。
2. 数据库配置、LLM 密钥及其他保密配置通常位于 `.env`；确有需要时可以自行查找。
3. 新增或修改数据库表、字段时，必须同步新增或更新数据库 `COMMENT` 注释。
4. 冒烟测试或 E2E 测试后清理模拟数据时，必须保留原有数据，避免误删。

## 四、运动模块统一规范

1. 新增或修改运动模块时，必须遵守 `docs/SPORT_MODULE_GUIDELINES.md` 的“统一运动契约”。主表、心得表及必备字段、统一接口和当天卡/运动档案/全部记录/编辑详情四个页面区块是最低要求；可增加模块专属表、字段和接口。数据库细节以 `docs/数据库建表设计.md` 和 `scripts/schema.sql` 为准。
2. 用户提出新增运动模块时，先阅读 `docs/SPORT_MODULE_GUIDELINES.md` 的“新增运动模块需求确认”。用户未说明的模块专属需求，按清单提出建议并追问；已说明内容不重复询问。计划态和记录态的统一必填项仅为日期，其他必填项须由用户确认；完成确认后才能开发。
3. 运动模块的时间和时长必须统一：
   - 表单（包括计划态）提供开始时间、结束时间和时长，三者均可为空。
   - Excel 模板、JSON 和 AI 导入提供开始时间和结束时间，均可为空；未填写时长时按起止时间推导。
   - 列表和详情不按 `status` 隐藏时间或时长；有值显示实际值，无值显示“—”。
   - 总览日卡中的计划态时长按 0 计算；心得仅在记录态且有内容时展示。
   - 相关改动必须同步更新表单、导入导出、列表详情和总览，不得只改一处。

## 五、界面与运行要求

1. 删除多余标语、说明文字和次要标签。删除后若界面难以理解，说明布局有问题，应直接重新设计。
2. 每次开发后如需重启服务，完成操作后必须关闭服务，不得保留监听端口。

## 六、接口文档契约

1. `docs/API_REFERENCE.md` 是全部 HTTP 接口（页面轨 + API 轨）的唯一清单，人工维护、不自动生成，只记录已实现接口。
2. 任何路由的新增、删除、方法或路径调整、入参或出参变化、权限或返回形态变化，必须在同一次改动内更新 `docs/API_REFERENCE.md` 的对应模块表格与模块索引计数；不得留下文档与代码不一致的条目。
3. 表格固定五列：路由地址（含 HTTP 方法）、传参格式、请求字段、响应字段、简述作用。模块顺序与 `main.py` 注册顺序一致；同一模块内页面接口在前、API 接口在后。
4. 字段名一律使用代码中的原始英文名，不改写、不翻译、不合并；嵌套结构用 `items[]{...}` 表达，可空字段标注“可空”或默认值。
5. 复用度高的响应对象（分页包、训练/游泳/舞蹈记录、身材快照、总览聚合、周期月历、会话等）在第 13 节定义一次，模块表格只引用对象名，不重复展开。
6. 只声明前缀但没有接口的路由（如 `/api/auth`）不登记为接口，在模块表下用一行说明标注“预留”。
7. 本文件只写接口契约，不写业务规则、算法口径和实现细节；业务口径以 `docs/ARCHITECTURE.md` 及各专项文档为准，不得互相复制。
8. 接口统计值（模块接口数、合计）随接口变更同步修正；文档中不得出现“待补充”“TODO”类占位。
