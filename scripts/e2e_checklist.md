# 体序 E2E 验收清单（含整改验收）

> 依据《个人健康管理平台开发需求文档》V1 范围 + 2026-10 建模整改逐条核对。
> 状态图例：✅ 已实现并验证（自动化冒烟 37 项 + 35 单测 + 浏览器抽查）｜— 需求明确不在 V1（需求 10.2/10.3 边界）
> 验证记录：`scripts/smoke_test.py`（服务运行后执行）；单测 `tests/`（pytest）；浏览器抽查记录见本文件末尾。

## 0. 建模整改验收（2026-10-31）

| 整改项 | 实现 | 状态 | 落点 |
| --- | --- | --- | --- |
| ① users 加性别/年龄 + **去身高** | users 现有 gender varchar(8) / age integer（均可空）；`height_cm` 已 DROP——身高统一由 body_basic_records 记录 | ✅ | `auth/models.py` + 库 ALTER（DROP COLUMN） |
| ② 注册功能（账户密码 + display_name/性别/年龄） | GET/POST `/register`；校验：用户名 3~32、密码 ≥6、昵称必填、年龄 1~120；注册页不再收身高（提示稍后在身材数据记录）；注册成功写会话 303→/body | ✅ | `auth/router_pages.py` + `templates/auth/register.html` + login 页注册入口 |
| ③ **body_metric_records 宽表→4 张拆分表** | ① body_basic_records（身高/体重/体脂率）② body_basic_goal（目标体重/目标体脂率）③ body_dimensions_records（颈/肩/臂/胸/腰/臀/大腿/小腿围）④ body_dimensions_goal（目标臂/胸/腰/臀/大腿/小腿围）；均含 user_id + created_at/updated_at，UNIQUE(user_id, record_date)；分组映射集中在 `constants.py::BODY_GROUPS` | ✅ | `body/models.py`（4 表）+ `service.py::upsert_group` + 库重建（旧宽表 DROP） |
| ④ 身材页 4 个分类添加按钮 + 未填字段沿用 | 页面 4 按钮（基础/期望/围度/目标围度）分别打开对应弹窗；默认显示记录日期最新一条；新增记录未填字段自动沿用该字段最近一次非空值（占位提示"沿用 X/新增"）；同日同组重复保存只覆盖当日已提交字段 | ✅ | `templates/body/index.html` + `static/js/body.js`（GROUP_OPENERS/GROUP_FORMS/GROUP_MODALS）+ `service.py::_inherit_value` |
| ⑤ training_plan_items 可空 + reps 字符串 + target_weight 放开 | body_part/weight_kg/sets/reps 四列可空；reps varchar(32)（如 "10+8+6"）；target_weight_kg 计划/记录均可填；容量按个数首段数字计，空负荷跳过 | ✅ | `training/{models,schemas,service}.py` + `training.js`（计划表单加目标重量列、reps 文本框） |
| ⑥ training_notes.status_text 可空 | status_text 改为 nullable，空心得存 NULL | ✅ | `training/models.py` + 库 ALTER |
| ⑦ swim_records.main_stroke 可空 | main_stroke 改 nullable，表单加「未填写」选项，空值存 NULL | ✅ | `swim/{models,schemas,router_api}.py` + `swim/index.html` + `swim.js` |

## 1. 身材数据 BD

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| BD-01 | 身材维度 4 组分表字段（基础 3 / 期望 2 / 围度 8 / 目标围度 6，共 19 项） | ✅ | `app/core/constants.py` BODY_FIELDS + BODY_GROUPS（Key→列名/分组映射） |
| BD-02 | 记录身材数据（4 组分别 upsert；同日同组重复保存只覆盖当日已提交字段；新日期未填字段沿用最近一次非空值） | ✅ | `body/service.py::upsert_group` + `_inherit_value`；4 表唯一约束 uq_body_*_user_date |
| BD-03 | BMI 计算（体重kg ÷ 身高m²，健康区间 18.5~23.9） | ✅ | `body/service.py::latest_snapshot` 返回 bmi + 区间文案 |
| BD-10 | 趋势四档：本周（周一~周日 7 点当日值） | ✅ | `trend_service.py::build_trend` range=week |
| BD-11 | 趋势四档：本月（每天当日值） | ✅ | 同上 range=month |
| BD-12 | 趋势四档：近半年（每月 1/10/20 号，窗口 [锚点-10 天,锚点] 11 天均值） | ✅ | 同上 range=half_year（窗口 11 天，锚点=采样日） |
| BD-13 | 趋势四档：近一年（每月 1/15 号，窗口 [锚点-15 天,锚点] 16 天均值） | ✅ | 同上 range=year（窗口 16 天） |
| BD-14 | 无记录断线不插值（connectNulls:false） | ✅ | FE-17；折线图 connectNulls:false |
| BD-20 | 身材数据页布局（4 指标卡 / 趋势图 / 剪影 / 记录表格；**页面默认显示记录日期最新一条**） | ✅ | `templates/body/index.html` + `static/js/body.js`（latest_snapshot 渲染指标卡与剪影） |
| BD-21 | **4 个分类添加按钮 + 4 弹窗**（基础 3 字段 / 期望 2 / 围度 8 / 目标围度 6；记录日期默认当天，可自选） | ✅ | `body/index.html` btnAddBasic/btnAddGoal/btnAddGirth/btnAddTarget + modalBasic/Goal/Girth/Target |
| BD-22 | 删除身材记录（按日删除当日 4 组全部） | ✅ | `/api/body-metrics` DELETE（record_date）→ `service.py::delete_day` |
| BD-23 | 目标值（target_*）不参与趋势 | ✅ | TREND_KEYS（基础+围度 11 维）；趋势接口对目标值返回 400 |
| BD-24 | 表格按日期合并 4 组展示（同日多组并成一行） | ✅ | `/api/body-metrics` GET（list_records 合并分页）+ body.js 表格渲染 |

## 2. 健身训练 TR

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| TR-01 | 训练计划日面板（动作/部位/重量/组数/个数） | ✅ | `templates/training/index.html` 日视图（空值显示 —） |
| TR-02 | 训练计划周面板 | ✅ | `/api/training/plans/week` + 周视图 |
| TR-03 | 新建/编辑计划（手动创建，无自动生成；负荷可空） | ✅ | formPlan + `/api/training/plans/{date}` POST/PUT |
| TR-10 | 是否开始训练确认弹窗（仅底部两按钮） | ✅ | FE-14；modalStart 仅「仅编辑/开始训练」 |
| TR-11 | 记录模式（计划转可编辑训练记录） | ✅ | `training.js` record 模式 |
| TR-12 | 组间休息/RPE 细节行（计划态） | ✅ | 日面板细节行 |
| TR-13 | 期望突破重量列（target_weight_kg，计划/记录均可填） | ✅ | 计划表单 + 记录模式列 + schema |
| TR-14 | 组数显示 n × m（m 为字符串，如 10+8+6 原样展示） | ✅ | FE-13；reps 字符串透传 |
| TR-15 | 勾选完成动作（对钩描边不填充黑） | ✅ | FE-11；`base.css` checkmark |
| TR-16 | 开始训练记录开始时间 | ✅ | `training/service.py::start_record`（mode=training 写 started_at） |
| TR-17 | 保存训练记录（后端算时长 saved_at-started_at） | ✅ | `save_record` 返回 duration_s；前端庆祝弹窗展示分钟 |
| TR-20 | 庆祝弹窗（时长/动作数/完成动作/总容量/心得确认/取消） | ✅ | modalCelebrate（FE-15 confetti 关闭即停） |
| TR-21 | 填写训练心得弹窗（状态文本 + 星级；文本可空） | ✅ | modalNote（status_text nullable + rating 1~5） |
| TR-22 | 当日保存后锁定（recorded 不可再改/删/重复保存） | ✅ | 接口幂等保护（400 提示） |
| TR-23 | 取消记录模式（未保存前可退出） | ✅ | `/plans/{date}/cancel` |
| TR-24 | 训练历史（已保存记录 + 心得，分页） | ✅ | `/api/training/history` + 历史表格 |
| TR-25 | 周期联动（结合生理周期给当日强度建议） | ✅ | 侧栏周期联动卡（cycle_link） |

## 3. 游泳 SW

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| SW-01 | 游泳记录 CRUD | ✅ | `/api/swim-records` |
| SW-02 | 配速计算（秒/100m，保留 1 位；格式 2'16） | ✅ | `swim/service.py::calc_pace` |
| SW-03 | 划频计算（划/min） | ✅ | `calc_stroke_rate` |

## 4. 舞蹈 DA

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| DA-01 | 舞蹈记录 CRUD + 汇总卡 + 舞种筛选 chips | ✅ | `/api/dance-records` + `dance/index.html` |

## 5. 生理周期 MC

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| MC-01 | 周期设置（默认 28/5） | ✅ | `cycle_settings` 表 + `/api/cycle/settings` |
| MC-02 | 记录月经开始（可补结束日；可选更新周期/经期长度） | ✅ | `create_period` |
| MC-03 | 每日疼痛记录（0~3，重写覆盖） | ✅ | `set_pain` + 页面按钮组 |
| MC-04 | 七阶段推算（经期/排卵期前期/排卵日/排卵期后期/黄体前期/黄体中期/黄体后期，独立枚举） | ✅ | `phase_for`（PHASE_* 枚举不合并） |
| MC-05 | 排卵日 = 周期长度 - 14；预测下次月经 | ✅ | `ovulation_date_for`、`next_period_date` |
| MC-10 | 运动三档：精力旺盛/状态良好/适合休息 | ✅ | `sport_level_for` |
| MC-11 | 疼痛 ≥2 一律「适合休息」（最高优先级） | ✅ | `sport_level_for` 首判 |
| MC-12 | 月历（阶段/运动等级/疼痛标注） | ✅ | `/api/cycle/calendar` + 月历网格 |
| MC-13 | 侧边栏「今天」小卡（周期第 N 天 + 运动等级） | ✅ | `get_today_summary` + sidebar |
| — | 周期概览（本次经期起止/排卵日/下次月经/进度） | ✅ | calendar overview + 详情卡 |

## 6. 前端与全局 FE

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| FE-01 | 字体栈 | ✅ | `tokens.css` --font-family |
| FE-10 | 按钮文字居中 | ✅ | `base.css` .btn |
| FE-16 | 左侧固定导航 | ✅ | `layout.css` + sidebar |
| FE-17 | 折线图断线不插值 | ✅ | body.js connectNulls:false |
| FE-18 | SVG 剪影引线 | ✅ | body/index.html 剪影标注 |
| 全局 | /api JSON、分页 {list,total,page,page_size} | ✅ | `core/pagination.py` |
| 全局 | 时长存秒、距离存米 | ✅ | 各 schema |
| 全局 | 未登录拦截（页面 303→/login、API 401） | ✅ | `core/deps.py` |
| 10.2 | 原型演示数据不实现 | — | 边界 |
| 10.3 | CSV 导出 / 顶栏搜索 / 计划模板 / 风格面板不实现 | — | 边界 |

## 7. 验证记录

- ✅ `python -m pytest tests/ -q`：35 passed（含 4 表拆分 upsert/继承/latest 合并/列表合并/delete_day 6 用例、趋势聚合适配、training reps 字符串与可空字段用例）
- ✅ `scripts/smoke_test.py`：37 项通过（登录、注册去身高、5 页面、未登录拦截、核心 API、4 组写链路、未填字段继承断言、跨组字段 400、训练 reps/可空写链路、清理）
- ✅ 浏览器抽查（2026-10-31，4 表整改后）：
  - 注册页：/register 渲染正常（用户名/密码/昵称/性别/年龄，无身高输入）；注册新用户后直入 /body
  - 身材页：4 个添加按钮（基础/期望/围度/目标围度）+ 4 弹窗；占位提示正确（无历史"新增"、有历史"沿用 165 / 沿用 60"）；填写今日体重保存后 latest 身高自动沿用昨日 165、体重 delta +1.0；表格按日期合并 2 行展示；趋势下拉 11 基础维度
  - 训练页：计划表单含目标重量列、reps 文本框；保存可空字段计划后日面板正确显示（— × 10+8+6、容量 0）；记录模式组件正常
  - 修复记录：V1 期 3 个真实 bug 已修复（training 表头类名、周期无记录预测、锚点前日期误打阶段）；整改期无新回归
- ✅ 数据库结构核对：users 无 height_cm（已 DROP）；body 旧宽表 body_metric_records 已 DROP；4 新表（basic/goal/girth/target）全部列 + uq_body_*_user_date 约束 + created_at/updated_at；training_plan_items 四列可空 + reps varchar；notes.status_text 可空；swim.main_stroke 可空（information_schema 逐项核对）
