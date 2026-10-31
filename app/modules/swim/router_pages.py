"""游泳页面路由：GET /swim。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.swim import service
from database import get_db

router = APIRouter()


@router.get("/swim")
def swim_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stats = service.stats(db, user.id)
    return render_page(
        request,
        "swim/index.html",
        {"active": "swim", "stats": stats},
    )
