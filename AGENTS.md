# sports-health-platform 唯一约定

## 一、文档入口与使用规则

`AGENTS.md` 是项目开发规则的唯一入口：先按任务类型查阅对应文档，再实施修改；详细实现内容写入对应文档，不在本文件重复展开。

| 任务 | 开始前阅读 | 修改后维护 |
| --- | --- | --- |
| 任意功能或模块 | `docs/ARCHITECTURE.md` | `README.md`、`docs/ARCHITECTURE.md`、`scripts/schema.sql`、`docs/数据库建表设计.md` |
| AI 功能 | `docs/ARCHITECTURE.md`、`docs/AI_ARCHITECTURE.md`、`docs/AIplan.md` | `docs/AI_ARCHITECTURE.md`；版本进度维护 `docs/AIplan.md`；并同步上述通用文档 |
| 前端页面、样式或交互 | `docs/ARCHITECTURE.md`、`docs/FRONTEND_GUIDELINES.md` | `docs/FRONTEND_GUIDELINES.md`，并同步上述通用文档 |
| 运动模块 | `docs/ARCHITECTURE.md`、`docs/SPORT_MODULE_GUIDELINES.md`、`docs/数据库建表设计.md` | `docs/SPORT_MODULE_GUIDELINES.md`、`docs/ARCHITECTURE.md`、`docs/数据库建表设计.md`、`scripts/schema.sql`，并同步 `README.md` |
| 数据库表或字段 | `docs/数据库建表设计.md`、`docs/ARCHITECTURE.md` | `docs/数据库建表设计.md`、`scripts/schema.sql`，并维护数据库 `COMMENT` 注释 |

1. `docs/ARCHITECTURE.md` 只记录已实现的系统结构、功能和约束，不记录未实现内容或设计设想。
2. `docs/AIplan.md` 只在 AI 功能发生改动时维护；前端和运动模块分别按对应规范文档维护。
3. 项目根目录只保留 `README.md`、`AGENTS.md` 和代码；所有项目说明文档统一放在 `docs/`。不得放置预览文件、测试文件、设计草稿等无关冗余文件。

## 二、AI 开发契约

1. AI 功能分为模型与运行时、AI 导入、AI Agent、数据问答工具四个逻辑子模块；开发前阅读 `docs/AI_ARCHITECTURE.md`，项目级影响同时核对 `docs/ARCHITECTURE.md`。
2. `docs/AI_ARCHITECTURE.md` 只记录已实现的 AI 架构、功能、工具、接口和开发契约；`docs/AIplan.md` 只记录版本规划、进度和未实现设想。
3. 新增或修改 AI 功能后，必须同步维护 `docs/AI_ARCHITECTURE.md`；涉及版本进度时同步 `docs/AIplan.md`；涉及数据库、前端或运动模块时，分别同步对应文档和代码。
4. 新增 AI 工具必须同时更新工具定义、受控查询、注册清单、提示词、前端事件（如有变化）和测试。工具必须只读，不接受模型提供的 `user_id`、SQL、表名或列名。
5. AI 导入必须复用运动模块现有的规范化、校验和落库逻辑，不得绕过统一运动契约或新增重复落库路径。
6. 提示词、模型注册表和结构化 schema 的变更，必须确认变量、能力声明与实际代码一致，并更新 AI 文档。

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
