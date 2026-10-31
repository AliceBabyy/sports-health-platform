"""认证页面路由：GET/POST /login、GET /register、POST /register、GET /logout。

身高不再属于 users（由 body_basic_records 记录），注册仅收集账号/昵称/性别/年龄。
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.auth.service import authenticate, create_user
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


@router.get("/register")
def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/body", status_code=303)
    return render_page(request, "auth/register.html", {"active": "register"})


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    gender: str = Form(""),
    age: str = Form(""),
    db: Session = Depends(get_db),
):
    username = username.strip()
    display_name = display_name.strip()
    if len(username) < 3 or len(username) > 32:
        return _register_error(request, "用户名长度需为 3~32 个字符", username, display_name, gender, age)
    if len(password) < 6:
        return _register_error(request, "密码长度至少 6 位", username, display_name, gender, age)
    if not display_name:
        return _register_error(request, "请填写昵称", username, display_name, gender, age)
    if db.query(User).filter(User.username == username).first() is not None:
        return _register_error(request, "用户名已存在，请换一个", username, display_name, gender, age)

    age_val: int | None = None
    if age.strip():
        try:
            age_val = int(age.strip())
            if not (1 <= age_val <= 120):
                raise ValueError
        except ValueError:
            return _register_error(request, "年龄需为 1~120 的整数", username, display_name, gender, age)

    user = create_user(db, username, password, display_name, gender or None, age_val)
    request.session["user_id"] = user.id
    return RedirectResponse("/body", status_code=303)


def _register_error(request: Request, error: str, username: str, display_name: str, gender: str, age: str):
    return render_page(
        request,
        "auth/register.html",
        {
            "active": "register",
            "error": error,
            "username": username,
            "display_name": display_name,
            "gender": gender,
            "age": age,
        },
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
