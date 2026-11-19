"""管理员账号保障（2026-11-19）：保证至少一名管理员，并同步配置指定的管理员登录名。

幂等、只升不降：不改变已有管理员的角色，也不会把管理员降级为普通用户。
"""
from sqlalchemy.orm import Session

from app.core.access import ADMIN_ROLE
from app.modules.auth.models import User
from config import settings


def admin_username_set() -> set[str]:
    """`ADMIN_USERNAMES` 逗号分隔（兼容中文逗号），忽略空白项。"""
    raw = settings.admin_usernames.replace("，", ",")
    return {name.strip() for name in raw.split(",") if name.strip()}


def ensure_admin_accounts(db: Session) -> int:
    """返回本次提升为管理员的账号数。"""
    promoted = 0

    usernames = admin_username_set()
    if usernames:
        rows = (
            db.query(User)
            .filter(User.username.in_(usernames), User.role != ADMIN_ROLE)
            .all()
        )
        for row in rows:
            row.role = ADMIN_ROLE
            promoted += 1

    has_admin = db.query(User).filter(User.role == ADMIN_ROLE).first() is not None
    if not has_admin:
        row = db.query(User).filter(User.status == "启用").order_by(User.id.asc()).first()
        if row is not None:
            row.role = ADMIN_ROLE
            promoted += 1

    if promoted:
        db.commit()
    return promoted
