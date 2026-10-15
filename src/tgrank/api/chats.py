from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response

from ..boards import BoardNotFound
from ..ranking import RankQuery, emoji_stats, rank
from .deps import Admin, Ctx, Db

router = APIRouter(prefix="/api/chats", tags=["chats"], dependencies=[Admin])


def _chat_or_404(conn, chat_id: int):
    row = conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "没有这个群")
    return row


def chat_view(row) -> dict:
    return {
        "chat_id": row["chat_id"], "title": row["title"], "kind": row["kind"], "username": row["username"],
        "is_forum": bool(row["is_forum"]), "sync_enabled": bool(row["sync_enabled"]),
        "source": "api" if row["sync_enabled"] else "import",
        "history_complete": bool(row["history_complete"]),
        "last_sync_at": row["last_sync_at"], "last_refresh_at": row["last_refresh_at"],
        "last_calibrate_at": row["last_calibrate_at"], "last_error": row["last_error"],
        "messages": row["messages"], "reacted": row["reacted"],
    }


@router.get("")
def list_chats(conn: Db):
    rows = conn.execute(
        """SELECT c.*,
             (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.chat_id) AS messages,
             (SELECT COUNT(DISTINCT msg_id) FROM reactions r WHERE r.chat_id = c.chat_id) AS reacted
           FROM chats c ORDER BY c.created_at, c.title""").fetchall()
    return [chat_view(r) for r in rows]


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat_id: int, conn: Db):
    _chat_or_404(conn, chat_id)
    conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
    return Response(status_code=204)


@router.get("/{chat_id}/topics")
def topics(chat_id: int, conn: Db):
    _chat_or_404(conn, chat_id)
    return [dict(r) for r in conn.execute(
        "SELECT topic_id, title FROM topics WHERE chat_id = ? ORDER BY topic_id", (chat_id,))]


@router.get("/{chat_id}/emojis")
def emojis(chat_id: int, conn: Db):
    _chat_or_404(conn, chat_id)
    return emoji_stats(conn, chat_id)


@router.get("/{chat_id}/ranking")
def ranking(
    chat_id: int, ctx: Ctx, conn: Db,
    board: int | None = None,
    range_: Annotated[Literal["7d", "30d", "year", "all", "custom"], Query(alias="range")] = "all",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    topic: int | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    _chat_or_404(conn, chat_id)
    if board is None:
        board = conn.execute("SELECT id FROM boards WHERE builtin = 1").fetchone()[0]
    query = RankQuery(chat_id, board, range_, date_from, date_to, topic, q, offset, limit)
    try:
        page = rank(conn, query, ctx.env.tz, datetime.now(ctx.env.tz))
    except BoardNotFound:
        raise HTTPException(404, "没有这个榜单") from None
    return {"items": page.items, "total": page.total, "link_base": page.link_base}
