"""一键初始化：建表（create_all）+ 创建/更新初始账号（bcrypt）。

用法：
    python scripts/init_db.py                        # 默认 admin / admin123
    python scripts/init_db.py lrx mypass "若东"       # 自定义账号

说明：账号已存在时更新密码与显示名（幂等，可重复执行）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models_registry  # noqa: F401  触发全部模型注册，供 create_all 建全部表
from app.core.security import hash_password
from app.modules.auth.models import User
from database import Base, SessionLocal, engine


def main() -> None:
    parser = argparse.ArgumentParser(description="个人健康管理平台 · 初始化数据库")
    parser.add_argument("username", nargs="?", default="admin", help="登录用户名（默认 admin）")
    parser.add_argument("password", nargs="?", default="admin123", help="登录密码（默认 admin123，仅限本地开发）")
    parser.add_argument("display_name", nargs="?", default="", help="顶栏显示名（默认取用户名）")
    args = parser.parse_args()

    print("[1/2] 创建数据表 ...")
    Base.metadata.create_all(bind=engine)
    print("      完成。")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if user is None:
            user = User(
                username=args.username,
                password_hash=hash_password(args.password),
                display_name=args.display_name or args.username,
            )
            db.add(user)
            db.commit()
            print(f"[2/2] 已创建账号：{args.username}（显示名：{args.display_name or args.username}）")
        else:
            user.password_hash = hash_password(args.password)
            if args.display_name:
                user.display_name = args.display_name
            db.commit()
            print(f"[2/2] 账号已存在，已更新密码/显示名：{args.username}")
    finally:
        db.close()

    print("完成。启动：uvicorn main:app --port 8010 --reload")


if __name__ == "__main__":
    main()
