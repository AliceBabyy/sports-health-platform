"""系统管理区（2026-11-19）：页面 `/system` 与 API `/api/system` 的命名空间聚合点。

`scheduler/` 子包为应用内定时任务（APScheduler + scheduled_jobs/job_runs）；后续管理员
功能（用户管理、操作日志等）按同样方式作为子包挂入。
"""
