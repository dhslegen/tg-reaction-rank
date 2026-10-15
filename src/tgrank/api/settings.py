from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from ..db import connect
from ..push import last_push, send_digest
from ..settings import Settings, load_settings, save_settings
from .deps import Admin, Ctx, Db

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Admin])


@router.get("/settings")
def get_settings(conn: Db) -> Settings:
    return load_settings(conn)


@router.put("/settings")
def put_settings(body: Settings, ctx: Ctx, conn: Db) -> Settings:
    save_settings(conn, body)
    if ctx.scheduler is not None:
        ctx.scheduler.apply(body)  # 立即按新节奏重排任务
    return body


@router.get("/schedule")
def schedule(ctx: Ctx, conn: Db):
    return {"jobs": ctx.scheduler.view() if ctx.scheduler else [], "last_push": last_push(conn)}


@router.post("/push/test")
async def push_test(ctx: Ctx):
    """立即按当前设置推送一次（即使定期推送已关闭），用来验证目标和格式。"""
    env = ctx.env
    sent = await send_digest(ctx.tg, env.db_path, env.tz, datetime.now(env.tz), force=True)
    with connect(env.db_path) as conn:
        return {"sent": sent, "last_push": last_push(conn)}
