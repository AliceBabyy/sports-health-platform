# V1 端到端验收清单（E2E Checklist）

> 依据《个人健康管理平台开发需求文档》V1 范围逐条核对。
> 状态图例：✅ 已实现并验证（自动化冒烟 20/20 + 27 单测 + 浏览器人工抽查）｜— 需求明确不在 V1（需求 10.2/10.3 边界）
> 验证记录：`scripts/smoke_test.py`（服务运行后执行）；单测 `tests/`（pytest）；浏览器人工抽查记录见本文件末尾。

## 1. 身材数据 BD

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| BD-01 | 身材指标 Key 集合（身高/体重/BMI/体脂率…共 8 项） | ✅ | `app/core/constants.py` BODY_METRICS（body_fat 为第 8 项） |
| BD-02 | 记录身材数据（按日 upsert，同日多条取最后一条） | ✅ | `body/service.py::upsert`；唯一索引 user+metric_key+record_date |
| BD-03 | BMI 计算（体重kg ÷ 身高m²，健康区间 18.5~23.9） | ✅ | `body/service.py::latest_snapshot` 返回 bmi + 区间文案 |
| BD-10 | 趋势四档：本周（周一~周日 7 点当日值） | ✅ | `trend_service.py::build_trend` range=week |
| BD-11 | 趋势四档：本月（每天当日值） | ✅ | 同上 range=month |
| BD-12 | 趋势四档：近半年（每月 1/10/20 号，窗口 [锚点-10 天,锚点] 11 天均值） | ✅ | 同上 range=half_year（窗口 11 天，锚点=采样日） |
| BD-13 | 趋势四档：近一年（每月 1/15 号，窗口 [锚点-15 天,锚点] 16 天均值） | ✅ | 同上 range=year（窗口 16 天） |
| BD-14 | 无记录断线不插值（connectNulls:false） | ✅ | FE-17；折线图 connectNulls:false |
| BD-20 | 身材数据页布局（4 指标卡 / 月趋势图 / 剪影 / 记录表格） | ✅ | `templates/body/index.html` + `static/js/body.js` |
| BD-21 | 添加/编辑身材记录弹窗（表单 7 字段） | ✅ | `body/index.html` formMetric |
| BD-22 | 删除身材记录（当日/按日） | ✅ | `/api/body-metrics` DELETE（按日）、DELETE /{id} |

## 2. 健身训练 TR

| 需求编号 | 需求点 | 状态 | 落点 |
| --- | --- | --- | --- |
| TR-01 | 训练计划日面板（动作/部位/重量/组数/个数） | ✅ | `templates/training/index.html` 日视图 |
| TR-02 | 训练计划周面板 | ✅ | `/api/training/plans/week` + 周视图 |
| TR-03 | 新建/编辑计划（手动创建，无自动生成） | ✅ | formPlan + `/api/training/plans/{date}` POST/PUT |
| TR-10 | 是否开始训练确认弹窗（仅底部两按钮） | ✅ | FE-14；modalStart 仅「仅编辑/开始训练」 |
| TR-11 | 记录模式（计划转可编辑训练记录） | ✅ | `training.js` record 模式 |
| TR-12 | 组间休息/RPE 细节行（计划态） | ✅ | 日面板细节行 |
| TR-13 | 期望突破重量列（target_weight_kg） | ✅ | 记录模式列 + schema |
| TR-14 | 组数显示 n × m（中间乘号 ×） | ✅ | FE-13 |
| TR-15 | 勾选完成动作（对钩描边不填充黑） | ✅ | FE-11；`base.css` checkmark |
| TR-16 | 开始训练记录开始时间 | ✅ | `training/service.py::start_record`（mode=training 写 started_at） |
| TR-17 | 保存训练记录（后端算时长 saved_at-started_at） | ✅ | `save_record` 返回 duration_s；前端庆祝弹窗展示分钟 |
| TR-20 | 庆祝弹窗（时长/动作数/完成动作/总容量/心得确认/取消） | ✅ | modalCelebrate（FE-15 confetti 关闭即停） |
| TR-21 | 填写训练心得弹窗（状态文本 + 星级） | ✅ | modalNote（status_text + rating 1~5） |
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

- ✅ `python -m pytest tests/ -q`：27 passed
- ✅ `scripts/smoke_test.py`：20/20 通过（登录、5 页面、未登录拦截、核心 API、写链路+清理）
- ✅ 浏览器人工抽查（2026-10-30）：
  - 登录 → 身材/训练/游泳/舞蹈/周期五页渲染正常，无 console 报错
  - 周期：记录月经 2026-10-16 → 阶段重算正确（排卵日 10-29、今天=第 15 天排卵期后期）、预测下次 11-13
  - 训练：新建计划（杠铃深蹲 70×5×8）→ 开始训练 → 保存记录 → 心得；已保存终态锁定（cancel/start/重复 save 均被 400 拦截）
  - 修复记录：training 表单表头误用 .plan-form-item 类导致保存 JS 报错（已改 plan-form-head）；周期锚点前日期误推算 + 无记录预测下次错误（已修）
