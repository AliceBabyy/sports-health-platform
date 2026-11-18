# 体序 BODY ALMANAC · 接口文档

> 本文件是项目全部 HTTP 接口的唯一清单，面向人阅读、人工维护。
> 只记录已实现的接口：方法、路由、传参格式、请求字段、响应字段、作用。
> 维护规则写在根目录 `AGENTS.md` 第六节；业务口径与模块职责不在此重复，见 `docs/ARCHITECTURE.md`。
## 1. 通用约定

### 1.1 两条轨道

| 轨道 | 路由文件 | 前缀 | 返回 | 未登录 |
| --- | --- | --- | --- | --- |
| 页面轨 | `app/modules/*/router_pages.py` | `/xxx` | Jinja2 HTML | 303 → `/login` |
| API 轨 | `app/modules/*/router_api.py` | `/api/xxx` | JSON | 401 `{code:"UNAUTHORIZED", error:"未登录或会话已过期"}` |

### 1.2 公共约定

| 项 | 约定 |
| --- | --- |
| 认证 | 除 `/login`、`/register`、`/logout`、`/` 外，全部接口需登录；所有业务查询按登录用户过滤，请求体不接受 `user_id` |
| 错误体 | 业务错误 `{code, error}`；参数校验失败固定 422 `{code:"VALIDATION_ERROR", error:"请求参数无效"}` |
| 分页 | 统一 `{list, total, page, page_size, pages}`；`page ≥ 1`，`page_size` 取 1~100，默认 10 |
| 日期 | `YYYY-MM-DD`；月份参数 `YYYY-MM` |
| 时间 | ISO datetime，如 `2026-11-04T19:00:00` |
| 单位 | 时长存秒 `duration_s`，距离存米 `distance_m`，重量存 kg；界面展示时换算 |
| 两态 | 健身/游泳/舞蹈统一 `status`：`planned`（计划）/ `recorded`（记录）；统计只计 `recorded` |
| 归属 | 三运动与状态记录按主表 id 定位，一日可多条；身材 4 表按 `(user_id, record_date)` 唯一 |
| 文件 | xlsx 导入上限 20MB；AI 导入图片最多 3 张、单张 ≤ 2MB，仅 JPG/PNG/WebP |
| 派生值 | BMI、配速、划频、趋势、周期阶段、经期/周期长度均实时计算，不落库 |

### 1.3 模块索引

| 模块 | 路由前缀 | 页面接口 | API 接口 | 合计 |
| --- | --- | --- | --- | --- |
| 全局与入口 | `/` | 1 | 0 | 1 |
| 认证 auth | `/login`、`/register`、`/logout` | 5 | 0 | 5 |
| 身材数据 body | `/body`、`/api/body-metrics` | 1 | 9 | 10 |
| 健身训练 training | `/training`、`/api/training` | 1 | 15 | 16 |
| 游泳 swim | `/swim`、`/api/swim-records` | 1 | 13 | 14 |
| 舞蹈 dance | `/dance`、`/api/dance-records` | 1 | 13 | 14 |
| 生理周期 cycle | `/cycle`、`/api/cycle` | 1 | 10 | 11 |
| 状态记录 state_record | `/state-record`、`/api/state-record` | 1 | 7 | 8 |
| 个人信息 profile | `/profile`、`/api/profile` | 2 | 6 | 8 |
| 总览 overview | `/overview`、`/api/overview` | 1 | 2 | 3 |
| 电子教练 electronic_trainer | `/api/electronic-trainer` | 0 | 2 | 2 |
| AI 助手 agent | `/agent`、`/api/agent` | 3 | 25 | 28 |
| AI 运动报告 report | `/reports`、`/api/reports` | 1 | 4 | 5 |
| 每日训练建议 daily_advice | `/api/daily-advice` | 0 | 2 | 2 |
| 定时任务 scheduler | `/system/scheduler`、`/api/scheduler` | 1 | 6 | 7 |
| **合计** | — | **19** | **106** | **125** |

## 2. 全局与认证

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /` | 无 | 无 | 303 跳转 | 已登录跳 `/body`，未登录跳 `/login` |
| `GET /login` | 无 | 无 | HTML 页面 / 303 | 登录页；会话有效时直接 303 → `/body` |
| `POST /login` | Form | `username`、`password` | 303 → `/body`；失败返回 HTML 登录页（含 `error`、回显 `username`） | 校验账号密码并写入会话 |
| `GET /register` | 无 | 无 | HTML 页面 / 303 | 注册页；会话有效时 303 → `/body` |
| `POST /register` | Form | `username`（3~32）、`password`（≥6）、`display_name`、`gender`（`男`/`女`/空）、`age`（空或 1~120）、`restore_account`（bool） | 303 → `/body`（新建）或 `/profile`（恢复停用账号）；失败返回 HTML（含 `error`） | 注册；勾选恢复且原密码正确时复用原账号并登录 |
| `GET /logout` | 无 | 无 | 303 → `/login` | 清空会话并登出 |

> `app/modules/auth/router_api.py` 仅声明 `/api/auth` 前缀，当前没有任何接口，属预留。

## 3. 身材数据 body

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /body` | 无 | 无 | HTML 页面 | 身材页：最新快照、达成成就、初始趋势 |
| `GET /api/body-metrics` | Query | `page`、`page_size` | `{list:[{record_date, values{指标key: 数值}}], total, page, page_size, pages}` | 按日期合并 4 组记录，日期倒序分页 |
| `GET /api/body-metrics/template` | 无 | 无 | xlsx 文件流（`body_import_template.xlsx`） | 下载导入模板（基础记录/维度记录两 Sheet + 填写说明） |
| `POST /api/body-metrics/import` | Multipart | `file`（.xlsx，≤20MB） | `{ok, imported, failed[]{sheet,row,column,reason}}` | 导入 Excel；同日同组覆盖，留空列沿用该字段最近非空值 |
| `GET /api/body-metrics/export` | 无 | 无 | xlsx 文件流（`身材数据_YYYY-MM-DD.xlsx`） | 导出全部基础记录与维度记录，表头与导入模板一致 |
| `POST /api/body-metrics/{group}` | 路径参数 + JSON | 路径 `group`（`basic`/`goal`/`girth`/`target`）；体 `record_date`、`values{指标key: 数值}`（至少 1 项） | `{ok, group, record_date}` | 按组添加或覆盖；新日期未填字段继承最近非空值 |
| `PUT /api/body-metrics/{group}/{record_date}` | 路径参数 + JSON | 路径 `group`（仅 `basic`/`girth`）、`record_date`；体 `values` | `{ok, group, record_date}` | 单条更新，仅覆盖提交字段；该日无记录 404 |
| `DELETE /api/body-metrics` | Query | `record_date`（必填） | `{ok, deleted}` | 删除某日 4 组全部记录，`deleted` 为删除行数 |
| `GET /api/body-metrics/latest` | 无 | 无 | 身材快照（A.8） | 各维度最新值、较上次差值与 BMI |
| `GET /api/body-metrics/trend` | Query | `metric`（默认 `weight`；可选 `weight`/`body_fat`/`arm`/`chest`/`waist`/`hip`/`thigh`/`calf`）、`range`（默认 `month`；可选 `week`/`month`/`two_month`/`half_year`/`year`） | `{range, points:[{date, value 或 null}]}` | 趋势序列；窗口内无记录为 `null`，前端断线 |

### 3.1 分组与字段

| `group` | 含义 | 允许的 `values` 字段 |
| --- | --- | --- |
| `basic` | 身体基础 | `height`（cm）、`weight`（kg）、`body_fat`（%） |
| `goal` | 期望指标 | `target_weight`（kg）、`target_body_fat`（%） |
| `girth` | 围度 | `neck`、`shoulder_width`、`arm`、`chest`、`waist`、`hip`、`thigh`、`calf`（cm） |
| `target` | 目标围度 | `target_arm`、`target_chest`、`target_waist`、`target_hip`、`target_thigh`、`target_calf`（cm） |

> 身高、颈围、肩宽与目标值不参与趋势；`metric` 传其他值返回 400。

## 4. 健身训练 training

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /training` | Query | `date`（可选，默认今天） | HTML 页面 | 单日视图（含前后翻页与健身档案） |
| `GET /api/training/daily` | Query | `date`（必填） | `{date, list:[训练对象]}` | 某日全部计划与记录，按 id 升序 |
| `POST /api/training` | JSON | `date`、`status`（`planned`/`recorded`，默认 `planned`）、`items[]{exercise_name(必填)、body_part、weight_kg、sets(1~99)、reps、target_weight_kg}`（至少 1 条）、`remark`（≤255）、`start_time`、`end_time`、`duration_s`（0~86400）、`avg_heart_rate`（1~300）、`max_heart_rate`（1~300）、`calories`（≥0） | 训练对象（A.4） | 新建计划或记录，一日可多条 |
| `POST /api/training/batch-delete` | JSON | `ids[]`（1~200） | `{deleted:[int], skipped:[int]}` | 批量删除计划/记录 |
| `GET /api/training/template` | 无 | 无 | xlsx 文件流（`training_plan_import_template.xlsx`） | 下载导入模板（每行一个动作 + 填写说明） |
| `POST /api/training/import` | Multipart | `file`（.xlsx，≤20MB） | 批量导入结果（A.13，健身版） | 按（日期, 训练组编号）合并为记录，统一 `recorded`；失败行不阻断 |
| `POST /api/training/import-json` | JSON | `plans[]{date、start_time、end_time、remark、avg_heart_rate、max_heart_rate、calories、items[]{同新建动作字段}}`（1~200 个，每个至少 1 动作） | 批量导入结果（A.13，健身版） | JSON 导入，逐计划校验后落 `recorded`；失败计划跳过 |
| `POST /api/training/ai-import` | Multipart | `prompt`（≤2000 字）、`images[]`（可选，≤3 张） | AI 导入结果（A.12，健身版） | 文字/图片识别为结构化计划并落库，复用 JSON 导入的校验与写入 |
| `POST /api/training/{record_id}/copy-to-today` | 路径参数 | 路径 `record_id` | `{plan: 训练对象}` | 一键复用历史计划，在今日新建 `planned` 计划 |
| `PUT /api/training/{record_id}` | 路径参数 + JSON | 路径 `record_id`；体 `date`、`items[]`、`remark`、`start_time`、`end_time`、`duration_s`、`avg_heart_rate`、`max_heart_rate`、`calories`（不含 `status`） | 训练对象（A.4） | 编辑计划/记录：改日期、动作、备注、起止与时长 |
| `DELETE /api/training/{record_id}` | 路径参数 | 路径 `record_id` | `{ok}` | 删除计划/记录（级联删动作与心得）；不存在 404 |
| `POST /api/training/{record_id}/complete` | 路径参数 | 路径 `record_id` | `{plan: 训练对象}` | 一键完成训练：`planned` → `recorded` 并写 `end_time`；已是记录 400 |
| `GET /api/training/{record_id}/note` | 路径参数 | 路径 `record_id` | `{note: {id, rating, best_movement, notes, next_steps} 或 null}` | 读取练后心得 |
| `PUT /api/training/{record_id}/note` | 路径参数 + JSON | 路径 `record_id`；体 `rating`（1~5）、`best_movement`（≤128）、`notes`、`next_steps` | `{note}` | 写心得（1:1 upsert）；仅 `recorded` 可写 |
| `GET /api/training` | Query | `page`、`page_size` | 分页包（A.1），`list` 为训练对象（A.4） | 全部计划与记录，日期与 id 倒序 |
| `GET /api/training/stats` | 无 | 无 | `{week_count, week_duration_s, month_count, month_duration_s}` | 健身档案：本周/本月记录态次数与时长 |

> 时长口径：手填 `duration_s` 优先；未填且起止时间齐备时按结束 − 开始推导。
> 新建记录态未给结束时间时，手动新建取当前时刻；Excel/JSON/AI 导入留空。

## 5. 游泳 swim

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /swim` | Query | `date`（可选，默认今天） | HTML 页面 | 游泳单日视图（计划 + 记录两态） |
| `GET /api/swim-records` | Query | `page`、`page_size` | 分页包（A.1），`list` 为游泳对象（A.5） | 全部记录分页，日期与 id 倒序 |
| `GET /api/swim-records/daily` | Query | `date`（必填） | `{date, list:[游泳对象]}` | 某日全部计划与记录 |
| `GET /api/swim-records/template` | 无 | 无 | xlsx 文件流（`swim_import_template.xlsx`） | 下载导入模板 |
| `POST /api/swim-records/import` | Multipart | `file`（.xlsx，≤20MB） | 批量导入结果（A.13，游泳版） | 每条有效行新建 `recorded` 记录；失败行不阻断 |
| `POST /api/swim-records/import-json` | JSON | `records[]{date、start_time、end_time、distance_m(必填)、duration_min、main_stroke（中文或 key）、avg_heart_rate、total_strokes、laps、avg_stroke_rate、calories、remark}`（≤500 条） | 批量导入结果（A.13，游泳版） | JSON 导入，统一 `recorded` |
| `POST /api/swim-records/ai-import` | Multipart | `prompt`（≤2000 字）、`images[]`（可选，≤3 张） | AI 导入结果（A.12，游泳版） | 文字/图片识别并落库，复用 JSON 导入校验 |
| `POST /api/swim-records` | JSON | `date`、`start_time`、`end_time`、`status`（默认 `recorded`）、`distance_m`、`duration_s`、`main_stroke`、`remark`（≤255）、`avg_heart_rate`（1~300）、`max_heart_rate`（1~300）、`total_strokes`（≥0）、`laps`（≥0）、`calories`、`avg_stroke_rate`（0~200） | 游泳对象（A.5） | 新建泳池记录/计划 |
| `POST /api/swim-records/batch-delete` | JSON | `ids[]`（1~200） | `{deleted:[int], skipped:[int]}` | 批量删除 |
| `PUT /api/swim-records/{record_id}` | 路径参数 + JSON | 路径 `record_id`；体同新建字段 | 游泳对象（A.5） | 编辑；已记录不能改回计划；不存在 404 |
| `DELETE /api/swim-records/{record_id}` | 路径参数 | 路径 `record_id` | `{ok}` | 删除单条；不存在 404 |
| `GET /api/swim-records/{record_id}/note` | 路径参数 | 路径 `record_id` | `{note: {id, rating, stroke_insight, notes} 或 null}` | 读取练后心得 |
| `PUT /api/swim-records/{record_id}/note` | 路径参数 + JSON | 路径 `record_id`；体 `rating`（1~5）、`stroke_insight`、`notes` | `{note}` | 写心得（1:1 upsert），仅 `recorded` 可写 |
| `GET /api/swim-records/stats` | 无 | 无 | `{count, total_distance_m, total_duration_s, avg_pace, avg_heart_rate, stroke_count{}, fastest_pace, slowest_pace, top_stroke, top_stroke_label, latest{date,distance_m,duration_s,pace,main_stroke,main_stroke_label,avg_stroke_rate} 或 null}` | 游泳档案，仅统计 `recorded` |

> 校验：`recorded` 需距离 + 时长（或完整起止时间由后端推导）；`planned` 需目标距离；结束时间必须晚于开始时间；主泳姿限 `freestyle`/`breaststroke`/`backstroke`/`butterfly`/`mixed`。

## 6. 舞蹈 dance

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /dance` | Query | `date`（可选，默认今天） | HTML 页面 | 舞蹈单日视图（计划 + 记录两态） |
| `GET /api/dance-records` | Query | `page`、`page_size`、`dance_type`（可选筛选） | 分页包（A.1），`list` 为舞蹈对象（A.6） | 全部记录分页，可按舞种筛选 |
| `GET /api/dance-records/daily` | Query | `date`（必填） | `{date, list:[舞蹈对象]}` | 某日全部计划与记录 |
| `GET /api/dance-records/template` | 无 | 无 | xlsx 文件流（`dance_record_import_template.xlsx`） | 下载导入模板 |
| `POST /api/dance-records/import` | Multipart | `file`（.xlsx，≤20MB） | 批量导入结果（A.13，舞蹈版） | 每行新建一条 `recorded` 记录；失败行不阻断 |
| `POST /api/dance-records/import-json` | JSON | `records[]{date、start_time、end_time、dance_type、stars(1~5)、teacher、style、duration_s、avg_heart_rate、max_heart_rate、calories、remark}`（≤500 条） | 批量导入结果（A.13，舞蹈版） | JSON 导入，统一 `recorded` |
| `POST /api/dance-records/ai-import` | Multipart | `prompt`（≤2000 字）、`images[]`（可选，≤3 张） | AI 导入结果（A.12，舞蹈版） | 文字/图片识别并落库，复用 JSON 导入校验 |
| `POST /api/dance-records` | JSON | `date`、`start_time`、`end_time`、`status`（默认 `recorded`）、`dance_type`（1~32，必填）、`stars`（1~5，必填）、`teacher`（≤64）、`remark`（≤255）、`style`（≤64）、`duration_s`、`avg_heart_rate`（1~300）、`max_heart_rate`（1~300）、`calories` | 舞蹈对象（A.6） | 新建课程计划/记录 |
| `POST /api/dance-records/batch-delete` | JSON | `ids[]`（1~200） | `{deleted:[int], skipped:[int]}` | 批量删除 |
| `PUT /api/dance-records/{record_id}` | 路径参数 + JSON | 路径 `record_id`；体同新建字段 | 舞蹈对象（A.6） | 编辑；已记录不能改回计划；不存在 404 |
| `DELETE /api/dance-records/{record_id}` | 路径参数 | 路径 `record_id` | `{ok}` | 删除单条；不存在 404 |
| `GET /api/dance-records/{record_id}/note` | 路径参数 | 路径 `record_id` | `{note: {id, rating, video_effect, notes} 或 null}` | 读取练后心得 |
| `PUT /api/dance-records/{record_id}/note` | 路径参数 + JSON | 路径 `record_id`；体 `rating`（1~5）、`video_effect`（1~5）、`notes` | `{note}` | 写心得（1:1 upsert），仅 `recorded` 可写 |
| `GET /api/dance-records/stats` | 无 | 无 | `{count, total_duration_s, avg_duration_s, avg_heart_rate, max_heart_rate, avg_stars, total_calories, dance_types[[舞种,次数]], month_count}` | 舞蹈档案，仅统计 `recorded` |

> 校验：计划态与记录态都必须有 `dance_type` 与 `stars`；未填 `duration_s` 且起止时间齐备时自动推导。

## 7. 生理周期 cycle

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /cycle` | 无 | 无 | HTML 页面 / 303 | 周期页；男性账号 303 → `/body` |
| `GET /api/cycle/settings` | 无 | 无 | `{cycle_length, period_length}` | 读取参考周期与参考经期（默认 28 / 5） |
| `PUT /api/cycle/settings` | JSON | `cycle_length`（22~45）、`period_length`（2~8） | `{cycle_length, period_length}` | 修改参考值；须满足 `period_length + 15 ≤ cycle_length` |
| `GET /api/cycle/periods` | 无 | 无 | `{list:[{id, start_date, end_date, period_length, cycle_length}]}` | 月经记录列表，长度按记录实时派生，算不出为 `null` |
| `POST /api/cycle/periods` | JSON | `start_date`、`end_date`（可空） | `{id, start_date, end_date}` | 新建月经记录；同日重复 409，段长越界 422 |
| `PUT /api/cycle/periods/{record_id}` | 路径参数 + JSON | 路径 `record_id`；体 `start_date`（可空）、`end_date`（可空，显式 `null` 可清空） | `{id, start_date, end_date}` | 修改；日期冲突 409，不存在 404 |
| `DELETE /api/cycle/periods/{record_id}` | 路径参数 | 路径 `record_id` | `{ok}` | 删除月经记录；不存在 404 |
| `GET /api/cycle/logs` | Query | `page`、`page_size` | 分页包（A.1），`list` 为 `{id, date, pain_level, note, period_id}` | 周期日志分页；仅疼痛或 note 有值的行，日期与 id 倒序 |
| `PUT /api/cycle/pain/{log_date}` | 路径参数 + JSON | 路径 `log_date`；体 `pain_level`（0~3） | `{ok, log_date, pain_level, period_id}` | 按日写入/覆盖疼痛等级；仅 recorded 经期可写，返回归属的 `period_records.id` |
| `PUT /api/cycle/note/{log_date}` | 路径参数 + JSON | 路径 `log_date`；体 `note`（≤255，可空串清空） | `{ok, log_date, note, pain_level, period_id}` | 写入/覆盖当日 note；非经期日保存时 `pain_level`、`period_id` 置 null |
| `GET /api/cycle/calendar` | Query | `month`（`YYYY-MM`） | 周期月历（A.10） | 逐日阶段、双份激素文案、四档状态、三态经期、疼痛 / note 与今日概览 |

> 男性账号访问本模块全部 API 返回 403 `{code:"FORBIDDEN", error:"男性账号不开放生理周期模块"}`。

## 8. 状态记录 state_record

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /state-record` | 无 | 无 | HTML 页面 | 状态记录页：月历 + 当日四类记录 + 全部记录 |
| `GET /api/state-record` | Query | `page`、`page_size`、`type`（可选，`appetite`/`myalgia`/`inflammation`/`mood`） | 分页包（A.1），`list` 为状态记录对象（A.7） | 跨四表合并分页，日期与 id 倒序；`type` 非法 400 |
| `GET /api/state-record/daily` | Query | `date`（必填） | `{date, records{appetite, myalgia, inflammation, mood：记录对象或 null}}` | 某日四类记录，未记录的类型为 `null` |
| `GET /api/state-record/calendar` | Query | `month`（`YYYY-MM`） | `{year, month, days:[{date, phase_key 或 null, phase_group 或 null, phase_label 或 null, has_record}]}` | 月历：复用周期阶段并归并三档，标记当日是否有记录 |
| `POST /api/state-record` | JSON | `date`、`type`、`star`（0~5，可空）、`remark`（≤255，可空） | 状态记录对象（A.7） | 新建；同用户同类型同一天唯一，重复 409 |
| `POST /api/state-record/batch-delete` | JSON | `items[]{id, type}`（1~200 条） | `{deleted:[{id,type}], skipped:[{id,type}]}` | 跨表批量删除，每条自带类型定位表 |
| `PUT /api/state-record/{record_id}` | 路径参数 + JSON | 路径 `record_id`；体 `date`、`type`、`star`、`remark` | 状态记录对象（A.7） | 按 id 编辑；日期冲突 409，不存在 404 |
| `DELETE /api/state-record/{record_id}` | 路径参数 + Query | 路径 `record_id`；查询 `type`（必填） | `{ok}` | 按 id + 类型删除单条 |

> `star` 语义：`0` 为明确最低分，`null` 为未评星，`1~5` 为星级。

## 9. 个人信息 profile

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /profile` | 无 | 无 | HTML 页面 | 账号资料页（基本资料、密码、注销；显示账号创建/更新时间） |
| `GET /profile/health-profile` | 无 | 无 | HTML 页面 | 健康/运动档案页：未填写直接展示问卷，已填写展示答案并支持编辑/清空 |
| `POST /api/profile` | JSON | `display_name`（≤32，必填）、`gender`（`男`/`女`/空）、`age`（字符串，空或 1~120） | `{ok, display_name, gender, age}` | 更新基本资料，返回最新值供顶栏同步 |
| `POST /api/profile/password` | JSON | `current_password`、`new_password`、`confirm_password` | `{ok}` | 修改密码：校验当前密码、两次新密码一致、新密码 ≥6 且不得与旧密码相同 |
| `DELETE /api/profile/account` | JSON | `mode`（`retain`/`purge`）、`current_password` | `{ok}` | 注销账号：`retain` 停用保留数据，`purge` 删除用户及全部关联数据；成功后清会话 |
| `GET /api/profile/health-profile` | 无 | 无 | `{ok, filled, completed_at, answers{题目key: 文本}}` | 读取健康/运动档案；未填写时 `filled=false`、`answers={}` |
| `PUT /api/profile/health-profile` | JSON | `answers{题目key: 文本}`（key 须为 `questions.py` 定义的题目；未传的题保持原值，空串清空该题；单题长度按题目上限） | `{ok, filled, completed_at, answers}` | 保存档案；全部答案清空时删除档案行并返回 `filled=false`；未知 key 或超长 400 |
| `DELETE /api/profile/health-profile` | 无 | 无 | `{ok}` | 清空档案（删除档案行），页面回到问卷态 |

## 10. 总览 overview

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /overview` | 无 | 无 | HTML 页面 | 运动总览页（日/周/月切换） |
| `GET /api/overview` | Query | `granularity`（`day`/`week`/`month`，默认 `week`）、`date`（可选，默认今天） | 总览聚合（A.9） | 按日/周/月聚合三运动计数、汇总卡与图表序列 |
| `GET /api/overview/day` | Query | `date`（必填） | `{date, fitness:[训练对象], swim:[游泳对象], dance:[舞蹈对象], labels{fitness, swim, dance}}` | 单日详情，供总览弹窗与详情页 |

> 时长口径：健身优先 `duration_s`，缺失时按 `recorded` 的 `end_time − start_time` 推导；游泳/舞蹈取 `duration_s`；计划态时长计 0。

## 11. 电子教练 electronic_trainer

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /api/electronic-trainer/models` | 无 | 无 | `{models:[{name, capabilities[]}]}` | 列出已注册模型及声明能力（`text`/`vision`/`tools`/`structured_output`） |
| `POST /api/electronic-trainer/probe` | JSON | `model`（可选，默认配置模型）、`text`（1~200） | `{model, prompt_version, answer}` | 连接探针：验证模型可用并返回结构化 `answer`；模型不支持 400，调用失败 502 |

> 这两个接口只做模型连通性与结构化输出验证，不读写运动数据，不承担 Agent 对话能力。

## 12. AI 助手 agent

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /agent` | 无 | 无 | HTML 页面 | AI 助手页（会话列表 + 对话区 + 模型下拉） |
| `GET /agent/skills` | 无 | 无 | HTML 页面 | 技能管理页（平台/我的技能列表 + 用户提示词编辑/平台只读展示） |
| `GET /agent/personas` | 无 | 无 | HTML 页面 | 角色管理页（平台角色只读 + 用户角色提示词编辑，保存即生效） |
| `GET /api/agent/conversations` | 无 | 无 | `{list:[会话对象（A.11）]}` | 当前用户会话列表，按最近消息时间倒序；含角色会话标识与角色名 |
| `POST /api/agent/conversations` | JSON | `model_name`（可选，≤64）、`persona_id`（可选，角色 id） | 会话对象（A.11） | 新建会话（分配 `thread_id`）；传 `persona_id` 即创建角色会话并固定该角色版本，之后不可切换；模型不支持 400，角色不可用 400/403 |
| `PUT /api/agent/conversations/{conversation_id}` | 路径参数 + JSON | 路径 `conversation_id`；体 `title`（1~64） | 会话对象（A.11） | 重命名会话；不存在 404 |
| `DELETE /api/agent/conversations/{conversation_id}` | 路径参数 | 路径 `conversation_id` | `{ok}` | 硬删除会话与 checkpointer 线程；生成中 409，不存在 404 |
| `GET /api/agent/conversations/{conversation_id}/messages` | 路径参数 | 路径 `conversation_id` | `{conversation_id, persona:{id,key,name,version_no}（可空）, turns:[{user, assistant（可空）, tool_runs:[{tool, args, data（可空）}]}]}` | 按一轮问答聚合读取历史，含工具调用轨迹与当前角色快照，供前端重建工具状态与明细折叠 |
| `POST /api/agent/conversations/{conversation_id}/messages` | 路径参数 + JSON | 路径 `conversation_id`；体 `content`（1~2000）、`client_msg_id`（1~64）、`model_name`（可选） | `text/event-stream`，事件见 12.1 | 发送消息并以 SSE 流式返回回复；前置校验失败以 JSON 返回 400/404/409 |
| `POST /api/agent/conversations/{conversation_id}/messages/regenerate` | 路径参数 + JSON | 路径 `conversation_id`；体 `client_msg_id`（1~64）、`model_name`（可选） | `text/event-stream`，事件见 12.1 | 重新生成最近一轮：回滚上一条 AI 回答后流式覆盖；前置校验失败以 JSON 返回 400/404/409 |
| `GET /api/agent/personas` | 无 | 无 | `{list:[角色对象（A.20）]}` | 平台内置角色（2 个）+ 当前用户私有角色 |
| `GET /api/agent/personas/{persona_id}` | 路径参数 | 路径 `persona_id` | 角色对象（A.20） | 角色详情；不存在 404，非本人用户角色 403 |
| `POST /api/agent/personas` | JSON | `name`（1~48）、`key`（1~48）、`description`（≤200）、`definition{schema_version,prompt}` | 角色对象（A.20） | 创建用户私有角色，保存即生成 v1 并生效；定义或键/名冲突 400 |
| `PUT /api/agent/personas/{persona_id}` | 路径参数 + JSON | 路径 `persona_id`；体同 `POST` | 角色对象（A.20） | 保存用户角色：定义变化才新增版本并立即生效，已有角色会话仍用旧版本；平台角色 403 |
| `POST /api/agent/personas/{persona_id}/status` | 路径参数 + JSON | 路径 `persona_id`；体 `status`（`active`/`disabled`） | 角色对象（A.20） | 启用/停用角色；停用只禁止新建角色会话，已绑定会话仍可继续；平台角色 403 |
| `DELETE /api/agent/personas/{persona_id}` | 路径参数 | 路径 `persona_id` | `{ok}` | 删除用户角色及其版本；被角色会话引用时 409，平台角色 403 |
| `GET /api/agent/skills` | 无 | 无 | `{list:[技能对象（A.14）]}` | 当前用户可见的平台技能与自己的私有技能 |
| `GET /api/agent/skills/runs` | Query | `limit`（默认 20，最大 100） | `{list:[技能运行记录（A.15）]}` | 当前用户全部技能运行记录；此路由必须位于 `/{skill_id}` 之前 |
| `POST /api/agent/skills/validate` | JSON | `kind`（仅 `prompt`，默认 `prompt`）、`definition`（可空，定义对象） | `{ok, errors[], warnings[]}` | 校验用户提示词定义，不落库 |
| `GET /api/agent/skills/{skill_id}` | 路径参数 | 路径 `skill_id` | 技能对象（A.14） | 技能详情；不存在 404，非本人用户技能 403 |
| `POST /api/agent/skills` | JSON | `name`（1~48）、`key`（1~48）、`slash_alias`（可空 ≤24）、`description`（≤200）、`category`、`kind`（仅 `prompt`，默认 `prompt`）、`definition` | 技能对象（A.14） | 创建用户私有提示词技能草稿；非法类型由请求模型返回 422，定义或键/别名冲突返回 400 |
| `PUT /api/agent/skills/{skill_id}` | 路径参数 + JSON | 路径 `skill_id`；体同 `POST` | 技能对象（A.14） | 保存用户提示词技能草稿（定义变化才新增版本）；平台技能 403 |
| `POST /api/agent/skills/{skill_id}/validate` | 路径参数 + JSON | 路径 `skill_id`；体 `definition`（可空，空则用当前版本） | `{ok, errors[], warnings[]}` | 按技能当前 kind 校验定义；平台代码技能返回不可修改警告 |
| `POST /api/agent/skills/{skill_id}/publish` | 路径参数 | 路径 `skill_id` | 技能对象（A.14） | 发布最新用户技能版本并设为 active；平台技能 403 |
| `POST /api/agent/skills/{skill_id}/status` | 路径参数 + JSON | 路径 `skill_id`；体 `status`（`active`/`disabled`/`archived`） | 技能对象（A.14） | 启用/停用/归档用户技能；平台技能 403 |
| `DELETE /api/agent/skills/{skill_id}` | 路径参数 | 路径 `skill_id` | `{ok}` | 删除用户技能及其版本/运行记录；平台技能 403 |
| `POST /api/agent/skills/{skill_id}/test` | 路径参数 + JSON | 路径 `skill_id`；体 `args`（参数字典） | 技能结果（A.15）；缺参返回 `{ok:false,status:"invalid_args",missing[],errors[],warnings[]}` | 试运行技能并写入 `trigger=test` 审计 |
| `GET /api/agent/skills/{skill_id}/runs` | 路径参数 + Query | 路径 `skill_id`；Query `limit`（默认 20） | `{list:[技能运行记录（A.15）]}` | 单技能运行记录；非本人用户技能 403 |

### 12.1 SSE 事件

| 事件 | `data` 字段 | 说明 |
| --- | --- | --- |
| `start` | `conversation_id`、`thread_id` | 开始生成 |
| `delta` | `content` | 正文增量 token |
| `tool_start` | `tool`、`label`、`kind`、`origin`、`version`、`skill`、`args` | 模型或斜杠链路发起工具/技能调用 |
| `tool_result` | `tool`、`label`、`kind`、`origin`、`version`、`skill`、`data` | 工具/技能返回结果（对象或 `{text}`）；技能结果含 `outputs/caveats/meta` |
| `done` | `conversation_id`、`title`、`last_message_at`、`persona`（可空，`{id,key,name,version_no}`） | 生成完成；首条消息自动取前 12 字作标题 |
| `error` | `message` | 生成失败（固定文案） |

> 同一会话同时只允许一个生成；重复 `client_msg_id` 返回 409。`X-Accel-Buffering: no`、`Cache-Control: no-cache`。消息内容以 `/技能名 自由文本` 开头时走技能解析；缺参数先返回一条追问 delta 并写入历史，下一条普通文本自动合并原命令继续解析。

## 13. AI 运动报告 report

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /reports` | Query | `type`（`weekly`/`monthly`，默认 `weekly`）、`anchor`（可选，日期 `YYYY-MM-DD`，默认今天） | HTML 页面 | 报告页：周/月切换、周期步进、生成/删除与历史列表 |
| `GET /api/reports` | Query | `type`（`weekly`/`monthly`）、`anchor`（可选） | 报告视图（A.16） | 读取某周期事实快照与已生成叙事；无报告时 `report=null` |
| `POST /api/reports/generate` | JSON | `type`（`weekly`/`monthly`）、`anchor`（可选）、`force`（bool，默认 `false`） | 报告视图（A.16） | 生成/复用报告；已 ready 且数据未变直接返回，`force` 强制重写；同周期并发 409，模型失败 502 |
| `GET /api/reports/history` | Query | `type`（可选筛选）、`page`（默认 1）、`page_size`（默认 10，1~50） | `{items:[{id,type,type_label,period_start,period_end,period_label,status,mode,headline,generated_at}], total, page, page_size}` | 历史报告列表，按周期倒序；软删除项不返回 |
| `DELETE /api/reports/{report_id}` | Path | 无 | `{ok:true, id}` | 软删除报告；已删除的周期不再被自动扫描重新生成 |

> 报告只统计 `recorded` 记录；计划单独计数、不计入训练量。热量沿用总览口径只汇总游泳+舞蹈。未结束周期仍返回 `period_end`（周日/月末），事实截至 `as_of` 并标 `partial`；未来周期读取/生成返回 400。

## 14. 每日训练建议 daily_advice

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /api/daily-advice` | Query | `date`（可选，`YYYY-MM-DD`，默认今天） | 每日建议视图（A.19） | 读取某天的建议；无行 `status="none"`，其余字段为 `null` |
| `POST /api/daily-advice/regenerate` | JSON | `date`（可选，仅允许今天）、`force`（bool，默认 `false`） | 每日建议视图（A.19） | 生成或复用当天建议；跨天 400，生成中 409，模型失败 502 |

> 只读本人当天一行，返回体不含 `facts` 与 `data_hash`。侧栏刷新按钮发送 `force=true`；同一行 60 秒内重复刷新直接返回已有结果，避免连点刷模型。`text` 为三段要点（今日建议 ≤20 字 / 健身建议 ≤20 字 / 依据 ≤40 字，每行 `- ` 开头、`\n` 分隔、句末无句号），前端用 `pre-line` 原样换行。

## 15. 定时任务 scheduler

| 路由地址 | 传参格式 | 请求字段 | 响应字段 | 简述作用 |
| --- | --- | --- | --- | --- |
| `GET /system/scheduler` | 无 | 无 | HTML 页面 | 任务卡列表、新建/编辑弹窗与执行历史 |
| `GET /api/scheduler/jobs` | 无 | 无 | `{list[], total}`，元素为 `scheduled_job`（A.17） | 任务列表：表达式、下次执行、上次结果与累计次数 |
| `POST /api/scheduler/jobs` | JSON | `job_key`（必填，须存在于代码注册表）、`trigger_type`（`cron`/`date`/`interval`）、`trigger_expr`（必填）、`timezone`（可空，默认 Asia/Shanghai）、`params`（对象，默认 `{}`）、`enabled`（默认 true）、`misfire_grace_seconds`（可空，0~86400） | `scheduled_job`（201） | 新建任务；表达式与参数在此校验，保存即注册内存作业 |
| `PATCH /api/scheduler/jobs/{job_id}` | JSON | 上述字段均可选且可空（`job_key` 不可改） | `scheduled_job` | 改表达式 / 启停 / 改名；停用即移除内存作业 |
| `DELETE /api/scheduler/jobs/{job_id}` | 路径参数 | 无 | `{ok: true}` | 删除任务定义与其执行记录 |
| `POST /api/scheduler/jobs/{job_id}/run` | 路径参数 | 无 | `{status, message, duration_ms, detail}` | 立即执行一次（线程池内同步跑，写入 `job_runs`） |
| `GET /api/scheduler/runs` | Query | `job_id`（可选）、`page`、`page_size`（默认 20） | 分页包，`list[]` 为 `job_run`（A.18） | 执行历史，按开始时间倒序 |

> 表达式口径：cron 为标准五段式（分 时 日 月 星期），**星期字段只接受 mon~sun 英文缩写**，数字写法返回 400；interval 形如 `10m`/`2h`/`1d`（最小 60 秒）；date 形如 `2026-11-20 15:40` 且必须晚于当前时间。任务参数结构由代码注册表约束，多余字段返回 422。任务为实例级配置，不按用户隔离。「立即执行」为同步执行，耗时较长时请求会等待。

## 16. 响应对象字典

### A.1 分页包

| 字段 | 说明 |
| --- | --- |
| `list` | 当前页数据数组 |
| `total` | 总条数 |
| `page` | 当前页码 |
| `page_size` | 每页条数 |
| `pages` | 总页数；无数据为 0 |

### A.2 错误响应

| 字段 | 说明 |
| --- | --- |
| `code` | `BAD_REQUEST` / `UNAUTHORIZED` / `FORBIDDEN` / `NOT_FOUND` / `REQUEST_FAILED` / `VALIDATION_ERROR` |
| `error` | 中文错误文案 |

### A.3 导入错误项

| 字段 | 说明 |
| --- | --- |
| `sheet` | Sheet 名；JSON 导入固定为 `JSON` |
| `row` | 行号（从 1 起） |
| `column` | 中文列名 |
| `reason` | 失败原因 |

### A.4 训练对象 TrainingPlan

| 字段 | 说明 |
| --- | --- |
| `id`、`date`、`status`、`remark` | 主键、日期、两态、备注 |
| `start_time`、`end_time`、`duration_s` | 起止时间、时长（秒） |
| `avg_heart_rate`、`max_heart_rate`、`calories` | 平均/最大心率、热量 |
| `item_count`、`total_sets`、`total_volume`、`body_parts_summary` | 动作数、总组数、总容量、部位摘要 |
| `items[]` | `{id, sort, exercise_name, body_part, weight_kg, sets, reps, target_weight_kg}` |
| `note` | `{id, rating, best_movement, notes, next_steps, status_text}` 或 `null`；`status_text` 为旧版自由文本，仅历史数据 |

### A.5 游泳对象 SwimRecord

| 字段 | 说明 |
| --- | --- |
| `id`、`date`、`status`、`remark` | 主键、日期、两态、备注 |
| `start_time`、`end_time` | 起止时间 |
| `distance_m`、`duration_s`、`pace` | 距离、时长、配速（min/100m，派生） |
| `avg_heart_rate`、`max_heart_rate`、`calories` | 平均/最大心率、热量 |
| `total_strokes`、`laps`、`avg_stroke_rate` | 总划水、趟数、平均划频（次/分，未填时派生） |
| `main_stroke`、`main_stroke_label` | 主泳姿 key 与中文名 |
| `note` | `{id, rating, stroke_insight, notes}` 或 `null` |

### A.6 舞蹈对象 DanceRecord

| 字段 | 说明 |
| --- | --- |
| `id`、`date`、`status`、`remark` | 主键、日期、两态、备注 |
| `start_time`、`end_time`、`duration_s` | 起止时间、时长（秒） |
| `dance_type`、`stars`、`teacher`、`style` | 舞种、星级、老师、风格 |
| `avg_heart_rate`、`max_heart_rate`、`calories` | 平均/最大心率、热量 |
| `note` | `{id, rating, video_effect, notes}` 或 `null` |

### A.7 状态记录对象 StateRecord

| 字段 | 说明 |
| --- | --- |
| `id`、`date`、`star`、`remark` | 主键、日期、星级（0~5 或 null）、描述 |
| `type`、`type_label` | 类型 key 与中文标签（食欲/肌肉疼痛/炎症/情绪） |
| `created_at`、`updated_at` | 创建/更新时间 |

### A.8 身材快照 BodySnapshot

| 字段 | 说明 |
| --- | --- |
| 19 个指标 key | 每个为 `{value, record_date, delta, prev_value}`；key 见 3.1 |
| `bmi`、`bmi_state` | BMI 与状态（偏轻/正常/超重/肥胖） |
| `latest_dates` | `{basic, goal, girth, target}` 各组最新日期 |
| `metrics`、`labels` | 指标 key 数组与 key→中文标签映射（仅最新接口返回） |

### A.9 总览聚合 OverviewAggregate

| 字段 | 说明 |
| --- | --- |
| `granularity`、`date`、`start`、`end` | 粒度、锚点日期、窗口起止 |
| `days[]` | `{date, weekday, sports{fitness, swim, dance}}` |
| `sports` 单项 | `{plans, records, minutes, kcal, remarks[], items[]{id, status, tag, main, minutes, remark}}`；`tag` 为「计/记」 |
| `stats` | `{records, plans, minutes, kcal, days, per_sport{fitness, swim, dance}}` |
| `chart` | `{labels[], fitness[], swim[], dance[]}`；`day` 粒度为 `null` |

### A.10 周期月历 CycleCalendar

| 字段 | 说明 |
| --- | --- |
| `year`、`month`、`days[]` | 年月与逐日数据 |
| `days` 单项 | `{date, phase_key, phase_label, phase_source, sport_level, sport_label, hormone_text, is_period, period_state, period_label, pain_level, pain_recorded, note, is_recorded_start, cycle_day, segment_source}`；`hormone_text` 为当前阶段双份文案中的一份（含换行，70 字内）；`pain_level` 可空（仅经期可写）；`note` 为当日 note 或 null |
| `overview` | `{has_records, reference_cycle_length, reference_period_length, latest_cycle_length, latest_period_length, next_period, overdue_days, ovulation_date, cycle_day_today, cycle_length_today, today_source, progress}` |
| `today` | `{date, phase_key, phase_label, sport_level, sport_label, note}` |

### A.11 会话对象 Conversation

| 字段 | 说明 |
| --- | --- |
| `id`、`title`、`model_name` | 主键、标题、会话级模型（可空） |
| `thread_id` | LangGraph 线程 UUID（checkpointer 键） |
| `kind` | `default` 普通会话 / `persona` 角色会话；由 `persona_id` 派生，不落库 |
| `persona_id` / `persona_name` / `persona_version_no` / `persona_status` | 角色会话绑定的角色、显示名、创建时版本号、角色当前状态；普通会话均为 `null` |
| `last_message_at`、`created_at` | 最近消息时间、创建时间 |

### A.12 AI 导入结果

| 字段 | 说明 |
| --- | --- |
| `ok` | 是否成功 |
| `payload` | 规范化后的识别结果：健身 `{plans:[...]}`，游泳/舞蹈 `{records:[...]}` |
| `ai` | `{model, prompt_version, elapsed_ms, warnings[]}` |
| `imported`、`created_ids[]`、`failed[]` | 导入条数、新建 id、失败明细（A.3） |
| `message` | 无可导入记录或校验未通过时的说明（可选） |
| 健身额外 | `items_imported`（动作数）、`training_ids`（等同 `created_ids`） |

### A.13 批量导入结果

| 变体 | 字段 |
| --- | --- |
| 健身 Excel/JSON | `{ok, imported, created_ids[], items_imported, failed[]}` |
| 游泳/舞蹈 Excel/JSON | `{ok, imported, created_ids[], failed[]}` |
| 身材 Excel | `{ok, imported, failed[]}` |

### A.14 技能对象

| 字段 | 说明 |
| --- | --- |
| `id` | 技能主键 |
| `scope` | `system` 平台 / `user` 用户私有 |
| `key` | 稳定技能键，工具名为 `skill_<key>` |
| `name` / `slash_alias` | 显示名 / 斜杠别名（用户技能可空） |
| `description` / `category` | 能力描述 / 分类 |
| `kind` | `code` 平台代码技能 / `declarative` 平台声明式技能 / `prompt` 用户提示词技能 |
| `status` | `draft` / `active` / `disabled` / `archived` |
| `current_version_no` / `version_no` | 当前发布版本 / 本次返回版本 |
| `published` / `can_edit` / `can_delete` | 是否已发布 / 当前用户是否可编辑 / 当前用户是否可删除；平台技能均为否，用户提示词技能可编辑，用户历史声明式技能只可删除 |
| `definition` | 平台声明式 DSL 或用户提示词定义 `{schema_version,prompt}`；平台代码技能为 `{kind:"code", code_key}` 或空 |
| `updated_at` | 更新时间 |

### A.15 技能运行记录

| 字段 | 说明 |
| --- | --- |
| `id` / `skill_id` / `version_no` | 运行主键、技能与版本 |
| `scope` / `name` / `kind` / `version` / `skill` | 试运行结果中的技能元信息 |
| `trigger` / `status` | `slash` / `model` / `test`；`ok` / `insufficient_data` / `invalid_args` / `failed` |
| `args` / `parse` | 归一化参数 / 解析元信息（model、prompt_version、strategy、耗时、warnings） |
| `sample_size` / `duration_ms` | 样本条数 / 执行耗时 |
| `error_code` / `error_message` | 失败错误码与说明 |
| `range` / `outputs` / `facts` / `summary` / `caveats` | 技能结果契约；试运行和运行记录接口返回；提示词技能 `range=null`、`outputs=[]`、`sample_size=0`、`summary` 为提示词指令 |

### A.16 报告视图 ReportView

| 字段 | 说明 |
| --- | --- |
| `type` / `type_label` | `weekly` / `monthly` 与中文「周报 / 月报」 |
| `period{type,label,start,end,as_of,partial,range_label}` | 周期信息；未结束周期 `partial=true`，`as_of` 为事实截止日 |
| `facts` | 事实快照：`metrics`（key → `{key,label,value,unit,display}`）、`cards[]{key,label,value,unit,display,delta_text,delta_dir}`、`totals` / `prev_totals`、`sports{fitness,swim,dance}`、`body{weight,body_fat,waist,hip}`、`state{types,pain_days,mood_low_days}`、`cycle`（可空）、`weekly_breakdown`（月报）、`notes`、`completeness`、`kcal_scope` / `kcal_note` |
| `report` | 可空；无报告或已删除时为 `null`。含 `id` / `type` / `type_label` / `period_start` / `period_end` / `period_label` / `status` / `mode` / `headline` / `narrative` / `stale` / `generated_at` / `model_name` / `prompt_version` / `attempts` / `error{code,message}` |
| `report.status` / `mode` | `generating` / `ready` / `failed`；`ai` / `rule`（规则文案，未调模型） |
| `report.narrative` | `{headline,summary,highlights[]{title,detail,evidence[]},watchouts[]{...},next_actions[]{...},caveats[],cycle_note}`；`evidence` 为 `facts.metrics` 的真实 key |
| `status` / `stale` / `auto_enabled` | 页面状态（`none` / `generating` / `ready` / `failed` / `deleted`）、数据是否已过期、自动生成是否启用 |

### A.17 定时任务对象 ScheduledJob

| 字段 | 说明 |
| --- | --- |
| `id` / `job_key` / `name` | 主键、代码注册表任务键、显示名 |
| `job_desc` / `available` | 注册表里的任务说明；`available=false` 表示该任务键已从代码中移除 |
| `trigger_type` / `trigger_expr` | `cron` / `date` / `interval` 与原始表达式 |
| `trigger_display` | 中文描述，如「每周一 08:00」「每月 1 日 08:00」「每 10 分钟」 |
| `timezone` | 触发时区 |
| `params` | 任务参数对象（结构由注册表 schema 约束） |
| `enabled` | 是否启用（停用时不注册内存作业） |
| `misfire_grace_seconds` | 错过宽限秒数；`null` 表示用全局默认 |
| `next_run_at` | 下次触发时间；调度器未运行时为 `null` |
| `last_run_at` / `last_status` / `last_status_label` | 上次执行时间与结果（`success` 成功 / `failed` 失败 / `skipped` 已跳过 / `running` 执行中） |
| `last_message` / `last_duration_ms` / `run_count` | 上次结果摘要、耗时、累计执行次数（含手动） |

### A.18 执行记录对象 JobRun

| 字段 | 说明 |
| --- | --- |
| `id` / `job_id` / `job_key` / `job_name` | 记录主键、所属任务（可空）、任务键与显示名 |
| `source` / `source_label` | `schedule` 定时 / `manual` 手动 / `cli` 命令行 |
| `status` / `status_label` | `running` / `success` / `failed` / `skipped` 与中文标签 |
| `started_at` / `duration_ms` | 开始时间与耗时 |
| `message` | 结果摘要或失败原因 |

> 导入语义：失败行/计划只记录错误，不阻断其他行；健身、游泳、舞蹈导入一律落 `recorded`，不覆盖已有数据。

### A.19 每日训练建议 DailyAdviceView

| 字段 | 说明 |
| --- | --- |
| `date` | 建议所属日 |
| `status` / `mode` | `none`（未生成）/ `generating` / `ready` / `failed`；`ai`（模型生成）/ `rule`（无数据规则文案） |
| `verdict` / `focus` / `intensity` | 适合 / 克制 / 休息；有氧 / 无氧 / 有氧+无氧 / 恢复；低 / 中 / 高（未生成时为 `null`） |
| `body_parts` | 建议的健身部位数组，最多 2 个；休息与纯有氧日为空数组 |
| `text` | 侧栏三段要点：今日建议 ≤20 字 / 健身建议 ≤20 字 / 依据 ≤40 字，每行以 `- ` 开头、行间用 `\n` 分隔、句末不带句号 |
| `tag` | 标签色语义 `good` / `average` / `rest`，对应页面 `tag-good` / `tag-average` / `tag-rest` |
| `generated_at` | 生成完成时间；未生成为 `null` |
| `error` | 失败时 `{code, message}`，否则为 `null` |

### A.20 角色对象 Persona

| 字段 | 说明 |
| --- | --- |
| `id` / `scope` / `key` | 主键、`system` 平台内置 / `user` 用户私有、稳定角色键 |
| `name` / `description` | 角色显示名、角色定位 |
| `status` | `active` / `disabled` |
| `sort_order` | 平台角色排序；用户角色为 0 |
| `current_version_no` / `version_no` | 当前生效版本 / 本次返回版本 |
| `published` | 返回版本是否已发布 |
| `can_edit` / `can_delete` | 当前用户是否可编辑/删除；平台角色均为否 |
| `definition` | 角色定义 `{schema_version:1, prompt}`；平台角色只读展示 |
| `updated_at` | 更新时间 |

## 17. 维护

- 本文件人工维护，不由代码自动生成；只增删改与代码一致的内容。
- 新增、删除、改方法、改路径、改入参/出参、改权限或改返回形态时，同步修改对应模块表格与 1.3 的计数。
- 复用度高的响应对象只在第 16 节定义一次，表格引用对象名，不重复展开。
- 本文件只写接口契约；业务规则、算法口径和实现细节见 `docs/ARCHITECTURE.md` 与各专项文档。
- 完整维护契约见根目录 `AGENTS.md` 第六节。
