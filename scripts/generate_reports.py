"""AI 运动报告生成 CLI：系统计划任务每 30 分钟 --scan，周一生成上周、每月 1 日生成上月。

用法：
    python scripts/generate_reports.py --scan --dry-run
    python scripts/generate_reports.py --scan
    python scripts/generate_reports.py --type weekly --anchor 2026-11-09 --user 1
    python scripts/generate_reports.py --type monthly --user 1 --force

说明：
- 应用进程内不跑常驻循环；由 Windows 任务计划程序按计划调用本脚本。
- --scan 用 PostgreSQL advisory lock 防重入；单实例串行生成，日志写 logs/report_task.log。
- 已 ready / 已软删除的周期跳过；failed 且 attempts >= REPORT_MAX_ATTEMPTS 不再自动重试。
"""
import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.report import service
from app.modules.report.facts import build_facts, resolve_period
from config import settings
from database import SessionLocal, engine

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "report_task.log"
LOCK_KEY = 2026111701  # 报告扫描互斥锁（任意固定整数，确保全项目唯一）


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
    db = SessionLocal()
    lock_conn = engine.connect()
    locked = False
    try:
        locked = bool(
            lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar()
        )
        if not locked:
            logging.info("已有报告任务在运行，本次跳过")
            return 0

        tasks = service.scan_due(db, limit=limit)
        logging.info("到期任务 %d 个", len(tasks))
        if dry_run:
            for task in tasks:
                print(json.dumps(task, ensure_ascii=False))
            return 0

        failed = 0
        for task in tasks:
            user = db.query(User).filter(User.id == task["user_id"]).first()
            if user is None:
                logging.warning("用户不存在，跳过 user_id=%s", task["user_id"])
                continue
            try:
                service.generate(
                    db,
                    user,
                    task["period_type"],
                    date.fromisoformat(task["anchor"]),
                    force=bool(task.get("refresh")),
                )
                logging.info(
                    "已生成 user_id=%s %s %s", task["user_id"], task["period_type"], task["period_label"]
                )
            except AppError as exc:
                failed += 1
                logging.warning(
                    "生成失败 user_id=%s %s %s：%s",
                    task["user_id"], task["period_type"], task["period_label"], exc.message,
                )
            except Exception:
                failed += 1
                logging.exception(
                    "生成异常 user_id=%s %s %s",
                    task["user_id"], task["period_type"], task["period_label"],
                )
        logging.info("本次完成，失败 %d 个", failed)
        return 0
    finally:
        if locked:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        lock_conn.close()
        db.close()


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
    parser.add_argument("--scan", action="store_true", help="扫描到期周期（上周周报 + 上月月报）")
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
        settings.report_auto_enabled, settings.report_model or settings.ai_default_model,
    )
    return run_one(args)


if __name__ == "__main__":
    sys.exit(main())
