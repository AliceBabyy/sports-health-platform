"""舞蹈页面路由：GET /dance。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.dance import service
from database import get_db

router = APIRouter()


@router.get("/dance")
def dance_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stats = service.stats(db, user.id)
    return render_page(
        request,
        "dance/index.html",
        {"active": "dance", "stats": stats},
    )
