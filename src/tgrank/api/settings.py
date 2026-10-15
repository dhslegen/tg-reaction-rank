from __future__ import annotations

from fastapi import APIRouter

from ..settings import Settings, load_settings, save_settings
from .deps import Admin, Ctx, Db

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Admin])


@router.get("")
def get_settings(conn: Db) -> Settings:
    return load_settings(conn)


@router.put("")
def put_settings(body: Settings, ctx: Ctx, conn: Db) -> Settings:
    save_settings(conn, body)
    if ctx.scheduler is not None:
        ctx.scheduler.apply(body)  # 立即按新节奏重排任务
    return body
