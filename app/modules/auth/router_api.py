"""认证 API 路由（V1 薄层，预留）。"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["auth"])
