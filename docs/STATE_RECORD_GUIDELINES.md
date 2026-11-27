# 状态记录开发规范

本文档记录状态记录模块（`/state-record`、`/api/state-record`）的统一记录项契约与新增记录项流程。系统整体结构见 [ARCHITECTURE.md](ARCHITECTURE.md)，数据库设计见 [数据库建表设计.md](数据库建表设计.md)，页面与样式规范见 [FRONTEND_GUIDELINES.md](FRONTEND_GUIDELINES.md)。

状态记录**不是运动模块**，不适用 [SPORT_MODULE_GUIDELINES.md](SPORT_MODULE_GUIDELINES.md) 的统一运动契约：没有计划态、起止时间、时长、心率、热量，也不提供 Excel / JSON / AI 导入。

## 一、记录项模型

- 一个记录项 = **按天的一条主观状态**：一个可空星级（0~5）+ 一段描述（≤255 字，可空）。
- 每个记录项独立一张表 `state_<type>_record`，表结构必须同构：

  | 列 | 类型 | 空 | 说明 |
  | --- | --- | --- | --- |
  | `id` | integer | NOT NULL | 主键（各表 identity 各自从 1 开始） |
  | `user_id` | integer | NOT NULL | FK → `users(id)`，`ON DELETE CASCADE` |
  | `date` | date | NOT NULL | 记录日期（同类一天一行） |
  | `star` | smallint | 可空 | 0~5；`0` = 明确最低分，`null` = 未评 |
  | `remark` | varchar(255) | 可空 | 描述 |
  | `created_at` | timestamp | NOT NULL | 默认 `now()` |
  | `updated_at` | timestamp | NOT NULL | 默认 `now()`，ORM `onupdate` 刷新 |

- 约束固定为 `UNIQUE (user_id, date)`（命名 `uq_state_<type>_user_date`），索引固定为 `ix_state_<type>_record_user_id`、`ix_state_<type>_record_user_date_id (user_id, date, id)`。
- 表名、类型键、约束名、索引名与 COMMENT 均以 `<type>` 为唯一变量；类型键使用小写英文 snake_case，上线后**不得改名**（改名必须同时迁移数据、索引、约束与 `type` 映射）。
- 只有「按天、单值」的状态才用本模块。同一天多条、需要明细行/时长/多个数值/文件导入的，另建独立模块，不硬塞进状态记录表。

## 二、类型注册的单一事实源

记录项类型只在 `app/modules/state_record/models.py` 注册一次：

1. `TYPE_<NAME>` 常量；
2. `STATE_TYPES` 元组（**顺序即页面当日块、筛选项和默认表单顺序**）；
3. `STATE_TYPE_LABELS` 中文标签；
4. 对应的 `XxxRecord` 模型类；
5. `STATE_MODELS` 映射。

其余位置必须从注册表派生，不得另写一份类型数组：

| 位置 | 派生方式 |
| --- | --- |
| `app/modules/state_record/schemas.py` | `Literal[tuple(STATE_TYPES)]`，新增类型自动接受 |
| `app/modules/state_record/service.py` | 列表、当日聚合、月历有记录标记、批量删除均遍历 `STATE_TYPES` / `STATE_MODELS` |
| `app/modules/state_record/router_api.py`、`router_pages.py` | 通用路由，不按类型分支；页面把 `state_types` / `state_type_labels` 注入模板 |
| `app/templates/state_record/index.html` | 筛选项与编辑弹窗选项用 `state_types` 循环；JS 从 `window.STATE_TYPES` / `window.STATE_TYPE_LABELS` 读取 |
| `app/modules/agent/tools/definitions.py` | `STATE_TYPE = Literal["all", *STATE_TYPES]` |
| `app/modules/agent/skills/definition.py` | 直接导入 `STATE_TYPES` |
| `app/modules/daily_advice/facts.py`、`app/modules/report/facts.py` | 遍历 `STATE_TYPES` 自动纳入事实快照 |
| `app/static/js/report.js` | 遍历 `facts.state.types`，不硬编码类型 key |

只允许在以下位置为某个类型补充**展示文案**（不复制类型枚举本身）：`state_record.js` 的 `TYPE_TAG`（标签配色，未登记回退 `tag-gray`）、`BLOCK_PLACEHOLDER`（输入占位，未登记用通用文案）。

## 三、新增记录项标准流程

新增一个状态记录项时，必须一次完成以下清单；缺任何一项都视为未完成：

1. **模型与注册**：在 `models.py` 增加 `TYPE_*`、`STATE_TYPES`、`STATE_TYPE_LABELS`、模型类与 `STATE_MODELS`；在 `models_registry.py` 导入新模型，保证 `Base.metadata.create_all` 建表。
2. **DDL**：在 `scripts/schema.sql` 增加 `state_<type>_record` 建表、两条索引与全部 `COMMENT ON TABLE/COLUMN`；同步更新文件头的变更记录。
3. **迁移**：在 `scripts/migrate_state_record.py` 的 `TABLES` 增加新表（脚本幂等，已有库重跑即可补建），并更新脚本头注释。
4. **数据库文档**：更新 `docs/数据库建表设计.md` 的表清单、关系图、状态记录小节、设计要点、变更记录与全库表数量（业务表 / 含框架表的总数）。
5. **页面**：确认模板筛选项与弹窗选项来自 `state_types`；在 `state_record.js` 只为新类型补 `TYPE_TAG`（可选）与 `BLOCK_PLACEHOLDER`（可选），新增块标题自动取「今日{标签}状况」；需要新配色时在 `tokens.css` + `base.css` 增加 `.tag-<type>`。
6. **API 文档**：`docs/API_REFERENCE.md` 第 8 节 `type` 枚举、`/daily` 的 records 键、A.7 标签列表同步；**不新增接口、不改路由前缀、不改分页包**。
7. **AI 与派生消费**：确认 `get_state_records` 枚举、声明式技能类型、每日建议 `state` 块、报告 `facts.state.types` 与报告事实面板均已自动覆盖；若新项要参与每日建议硬约束或报告专属指标，必须显式修改 `hard_limits` / `_state_facts` 并补测试，不能只靠提示词或“自动遍历”。
8. **提示词**：提示词不得写死记录项数量或枚举；当前 `daily_advice.v3` 只描述“各记录项（type / 星级 / 备注，标签见 labels）”。若确需让模型对新项做特殊判断，按 `AGENTS.md` 二.6 升级提示词版本并删除旧版本文件与映射。
9. **测试**：更新 `tests/test_state_record.py` 的类型全集断言、空日聚合键集合、CRUD/唯一/批量删除覆盖；更新 `tests/test_agent_tools.py` 的 `per_type` 断言；必要时补新项 roundtrip 测试。至少运行 `pytest tests/test_state_record.py tests/test_agent_tools.py -q`。
10. **文档与自检**：更新 `README.md`、`docs/ARCHITECTURE.md`、`docs/FRONTEND_GUIDELINES.md`；全局搜索 `四类|四表|三类|三表` 确认无残留（历史变更记录除外）；确认七个通用接口仍全部可用（列表、`/daily`、`/calendar`、新建、编辑、单条删除、`/batch-delete`）。

## 四、输入与接口契约

- `star`：`0~5` 整数或 `null`；`0` 是明确最低分，不得被当成未评；`null` 前端显示 `—`；越界（`<0` 或 `>5`）由 Pydantic 拒绝。方向语义按记录项定义：食欲 / 情绪 / 恢复越高越好；肌肉疼痛 / 炎症越高表示越明显（炎症 0 = 没有炎症）。新增记录项时必须在每日建议提示词与消费文档里写明方向，不能只靠字段名推断。
- `remark`：≤255 字，可空；前端提交前 `trim()`，空串按 `null` 落库。
- `date`：必填 `YYYY-MM-DD`；同用户同类型同一天只允许一行，重复新建返回 `409`，编辑撞日同样 `409`。
- 编辑按路径 `record_id` + body 的 `type` 定位表；类型决定落哪张表，页面编辑时类型不可改（改类型 = 删除后重建）。
- 删除单条必须带 `?type=`；批量删除 `items[]{id, type}` 每条自带类型（跨表 id 会重复，不能只按 id 删）。
- 不设软删除、不设导入导出；新增记录项复用现有 7 个 API，不新增 `/api/state-record/<type>` 之类的前缀。

## 五、页面契约

- 页面自上而下三张卡片：月历 → 当日状态 → 全部记录；`three-row-stack` 纵向堆叠，内容随卡片宽度铺满。
- 「当日状态」按 `STATE_TYPES` 顺序渲染全部记录项：桌面两列网格、每行 2 个记录项，760px 以下单列；每块内联五星 + 「0」最低分按钮 + 自适应高度描述框 + 保存；有记录时块内可删除；不弹新增表单，只有列表行内「编辑」才走表单弹窗。
- 月历「有记录」标记覆盖所有类型（任一项有记录即标记）；阶段配色与周期推算逻辑不随新增记录项改变，男性或无周期记录时阶段置空。
- 类型标签最低要求：食欲橙 / 肌肉疼痛灰 / 炎症红 / 情绪紫 / 恢复蓝；新类型未配专属色时回退灰色，但仍应有可读的中文标签。
- 详情复用 `base.html` 的 `#modalDetail`；列表列固定为日期 / 类型 / 星级 / 描述 / 操作。

## 六、变更记录

- 2026-11-11：状态记录模块建立（食欲 / 肌肉疼痛 / 炎症），按天记录、跨表合并分页、月历阶段归并。
- 2026-11-13：新增情绪（`mood`）记录项，并补详情/批量删除。
- 2026-11-26：新增恢复（`recovery`）记录项；类型注册、前端类型数组与服务端 `state_types` 统一为单一事实源；`daily_advice` 提示词升级 `v3`，状态字段说明改为类型无关，后续新增记录项无需再改提示词。
