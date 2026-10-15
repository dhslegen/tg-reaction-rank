"""路由共用的依赖：应用上下文、DB 连接、管理员鉴权。"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..auth import COOKIE_NAME, session_valid
from ..context import AppContext
from ..db import connect

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "DELETE"}  # DELETE 无法由跨站表单发起
_ALLOWED_TYPES = ("application/json", "multipart/form-data")


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def get_db(ctx: Ctx) -> Iterator[sqlite3.Connection]:
    with connect(ctx.env.db_path) as conn:
        yield conn


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def require_admin(request: Request, conn: Db) -> None:
    if not session_valid(conn, request.cookies.get(COOKIE_NAME), int(time.time())):
        raise HTTPException(401, "请先登录")
    # 配合 SameSite=Strict：写操作只接受跨站表单无法伪造的 Content-Type
    if request.method not in _SAFE_METHODS:
        ctype = request.headers.get("content-type", "")
        if not ctype.startswith(_ALLOWED_TYPES):
            raise HTTPException(415, "只接受 JSON 或文件上传")


Admin = Depends(require_admin)
