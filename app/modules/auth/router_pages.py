"""认证页面路由：GET /login、POST /login、GET /logout。"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import render_page
from app.modules.auth.service import authenticate
from database import get_db

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/body", status_code=303)
    return render_page(request, "auth/login.html", {"active": "login"})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate(db, username.strip(), password)
    if user is None:
        return render_page(
            request, "auth/login.html", {"active": "login", "error": "用户名或密码错误", "username": username}
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/body", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
