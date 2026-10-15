from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..tg.manager import TgLoginError, TgUnavailable
from .deps import Admin, Ctx, Db

router = APIRouter(prefix="/api/tg", tags=["telegram"], dependencies=[Admin])


class PhoneIn(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


async def _wizard(coro):
    try:
        return await coro
    except TgLoginError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/status")
def status(ctx: Ctx):
    return ctx.tg.status()


@router.post("/login/phone")
async def login_phone(body: PhoneIn, ctx: Ctx):
    await _wizard(ctx.tg.login_phone(body.phone))
    return {"next": "code"}


@router.post("/login/code")
async def login_code(body: CodeIn, ctx: Ctx):
    return {"next": await _wizard(ctx.tg.login_code(body.code))}


@router.post("/login/password")
async def login_password(body: PasswordIn, ctx: Ctx):
    await _wizard(ctx.tg.login_password(body.password))
    return {"next": "done"}


@router.post("/logout")
async def logout(ctx: Ctx):
    await ctx.tg.logout()
    return {"ok": True}


async def dialogs_or_409(ctx) -> list:
    try:
        return await ctx.tg.list_dialogs()
    except TgUnavailable:
        raise HTTPException(409, "请先在「Telegram」页登录账号") from None


@router.get("/dialogs")
async def dialogs(ctx: Ctx, conn: Db):
    added = {r[0] for r in conn.execute("SELECT chat_id FROM chats WHERE sync_enabled = 1")}
    return [{
        "chat_id": d.chat_id, "title": d.title, "kind": d.kind, "is_forum": d.is_forum,
        "kind_label": "频道" if d.kind.endswith("_channel") else "群", "added": d.chat_id in added,
    } for d in await dialogs_or_409(ctx)]
