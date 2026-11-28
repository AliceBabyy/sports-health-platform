"""运动报告生成 CLI：自动触发由应用内调度器完成，本脚本是手动补跑入口。

用法：
    python scripts/generate_reports.py --scan --dry-run
    python scripts/generate_reports.py --scan
    python scripts/generate_reports.py --type weekly --anchor 2026-11-09 --user 1
    python scripts/generate_reports.py --type monthly --user 1 --force

说明：
- `--scan` 走 `app.modules.system.scheduler.runner.run_task("report.scan")`，与页面「立即执行」同一路径：
  PostgreSQL advisory lock 与后台定时任务互斥，执行结果写入 `job_runs` 表留痕，日志写 logs/scheduler.log。
- `--type` 模式直接调用 report.service.generate，用于单用户、单周期重跑与排查。
"""
import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.models.registry import current_alias
from app.modules.auth.models import User
from app.modules.report import service
from app.modules.report.facts import build_facts, resolve_period
from app.modules.system.scheduler.runner import run_task
from config import settings
from database import SessionLocal

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "scheduler.log"


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def run_scan(dry_run: bool, limit: int) -> int:
    """补跑上周周报与上月月报；dry_run 只打印将处理的周期，不调模型。"""
    if dry_run:
        db = SessionLocal()
        try:
            tasks = service.scan_due(db, limit=limit, check_switch=False)
            for task in tasks:
                print(json.dumps(task, ensure_ascii=False))
            logging.info("试运行：到期任务 %d 个", len(tasks))
            return 0
        finally:
            db.close()

    result = run_task("report.scan", {"limit": limit}, source="cli")
    logging.info("扫描完成：%s（%dms）", result["message"], result["duration_ms"])
    for item in (result.get("detail") or {}).get("items", []):
        logging.info(
            "  %s user_id=%s %s %s",
            item.get("status"), item.get("user_id"), item.get("period_label"), item.get("error") or "",
        )
    return 0 if result["status"] == "success" else 1


def run_one(args) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == args.user).first()
        if user is None:
            logging.error("用户不存在 user_id=%s", args.user)
            return 2
        anchor = date.fromisoformat(args.anchor) if args.anchor else None
        if args.dry_run:
            period = resolve_period(args.type, anchor)
            facts = build_facts(db, user, period)
            print(json.dumps(
                {
                    "type": period.type,
                    "period_label": period.label,
                    "period_start": period.start.isoformat(),
                    "period_end": period.end.isoformat(),
                    "partial": period.partial,
                    "has_any_record": facts["completeness"]["has_any_record"],
                    "totals": facts["totals"],
                },
                ensure_ascii=False,
            ))
            return 0
        result = service.generate(db, user, args.type, anchor, force=args.force)
        report = result.get("report") or {}
        logging.info(
            "已生成 user_id=%s %s %s status=%s mode=%s",
            args.user, args.type, result["period"]["label"], report.get("status"), report.get("mode"),
        )
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 运动报告生成（周报/月报）")
    parser.add_argument("--scan", action="store_true", help="补跑到期周期（上周周报 + 上月月报）")
    parser.add_argument("--type", choices=["weekly", "monthly"], help="直接生成指定类型")
    parser.add_argument("--anchor", help="周期锚点日 YYYY-MM-DD（缺省今天）")
    parser.add_argument("--user", type=int, help="用户 ID（直接生成时必填）")
    parser.add_argument("--force", action="store_true", help="强制重新生成（已 ready 也重写）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将处理的周期，不调用模型")
    parser.add_argument("--limit", type=int, default=100, help="单次扫描最多处理的任务数")
    args = parser.parse_args()

    setup_logging()
    if not args.scan and not args.type:
        parser.error("请使用 --scan 或 --type weekly|monthly")
    if args.scan:
        return run_scan(args.dry_run, args.limit)
    if not args.user:
        parser.error("--type 模式需要 --user")
    logging.info(
        "报告任务开始 scan=%s type=%s anchor=%s user=%s dry_run=%s auto=%s model=%s",
        args.scan, args.type, args.anchor, args.user, args.dry_run,
        settings.report_auto_enabled,
        current_alias("report.monthly" if args.type == "monthly" else "report.weekly"),
    )
    return run_one(args)


if __name__ == "__main__":
    sys.exit(main())
