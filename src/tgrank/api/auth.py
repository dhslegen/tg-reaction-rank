from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth import COOKIE_NAME, SESSION_TTL, create_session, delete_session, password_ok, session_valid
from .deps import Admin, Ctx, Db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(max_length=256)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, ctx: Ctx, conn: Db):
    ip = request.client.host if request.client else "?"
    now = time.time()
    wait = ctx.limiter.retry_after(ip, now)
    if wait:
        return JSONResponse({"detail": f"尝试次数过多，请 {wait // 60 + 1} 分钟后再试", "retry_after": wait}, status_code=429)
    if not password_ok(ctx.env.admin_password, body.password):
        ctx.limiter.record_failure(ip, now)
        raise HTTPException(401, "密码不正确")
    ctx.limiter.record_success(ip)
    token = create_session(conn, int(now))
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_TTL, path="/", httponly=True, samesite="strict",
        secure=request.url.scheme == "https",
    )
    return {"ok": True}


@router.post("/logout", dependencies=[Admin])
def logout(request: Request, response: Response, conn: Db):
    delete_session(conn, request.cookies.get(COOKIE_NAME, ""))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, conn: Db):
    """除登录外唯一不要求会话的接口：前端据此决定是否跳登录页，未登录时不报 401。"""
    return {"authenticated": session_valid(conn, request.cookies.get(COOKIE_NAME), int(time.time()))}
