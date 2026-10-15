"""按榜单实时打分排行。分数不落库：SUM(count × weight) 在查询时算。"""
from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .boards import BoardNotFound
from .records import link_base, reaction_label

RANGES = ("7d", "30d", "year", "all", "custom")
FAR_FUTURE = 2 ** 62
TEXT_LIMIT = 200


@dataclass(frozen=True)
class RankQuery:
    chat_id: int
    board_id: int
    range: str = "all"
    date_from: date | None = None
    date_to: date | None = None
    topic_id: int | None = None
    q: str = ""
    offset: int = 0
    limit: int = 50
    window: tuple[int, int] | None = None   # 显式 [lo, hi) UTC 秒，优先于 range（推送用）


@dataclass(frozen=True)
class RankPage:
    items: list[dict]
    total: int
    link_base: str | None


def _day_start(d: date, tz: ZoneInfo) -> int:
    return int(datetime.combine(d, time.min, tzinfo=tz).timestamp())


def resolve_range(key: str, date_from: date | None, date_to: date | None, tz: ZoneInfo, now: datetime) -> tuple[int, int]:
    """返回 [lo, hi) 的 UTC 秒；所有「天」的边界都按部署时区 TZ 计算，而不是浏览器时区。"""
    today = now.astimezone(tz).date()
    if key == "all":
        return 0, FAR_FUTURE
    if re.fullmatch(r"\d{1,3}d", key) and int(key[:-1]) > 0:   # 「近 N 天」：含今天在内的 N 个自然日
        days = int(key[:-1])
        return _day_start(today - timedelta(days=days - 1), tz), FAR_FUTURE
    if key == "year":
        return _day_start(date(today.year, 1, 1), tz), FAR_FUTURE
    if key == "custom":
        lo = _day_start(date_from, tz) if date_from else 0
        hi = _day_start(date_to + timedelta(days=1), tz) if date_to else FAR_FUTURE
        return lo, hi
    raise ValueError(f"未知的时间范围：{key}")


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_SCORE = """SUM(r.count * CASE r.kind
                 WHEN 'emoji'        THEN COALESCE(w.weight, b.default_weight)
                 WHEN 'custom_emoji' THEN b.custom_emoji_weight
                 WHEN 'paid'         THEN b.paid_weight
                 ELSE b.default_weight END)"""


def _fmt_score(x: float) -> int | float:
    x = round(x, 2)
    return int(x) if x == int(x) else x


def rank(conn: sqlite3.Connection, q: RankQuery, tz: ZoneInfo, now: datetime) -> RankPage:
    if conn.execute("SELECT 1 FROM boards WHERE id = ?", (q.board_id,)).fetchone() is None:
        raise BoardNotFound(q.board_id)
    chat = conn.execute("SELECT kind FROM chats WHERE chat_id = ?", (q.chat_id,)).fetchone()

    lo, hi = q.window or resolve_range(q.range, q.date_from, q.date_to, tz, now)
    where = ["r.chat_id = :chat", "m.date >= :lo", "m.date < :hi"]
    params: dict = {"chat": q.chat_id, "board": q.board_id, "lo": lo, "hi": hi}
    if q.topic_id is not None:
        where.append("m.topic_id = :topic")
        params["topic"] = q.topic_id
    if q.q.strip():
        where.append("(m.text LIKE :q ESCAPE '\\' OR COALESCE(m.media, '') LIKE :q ESCAPE '\\')")
        params["q"] = _like_pattern(q.q.strip())

    scored = f"""
        SELECT r.msg_id AS msg_id, {_SCORE} AS score
        FROM reactions r
        JOIN messages m ON m.chat_id = r.chat_id AND m.msg_id = r.msg_id
        JOIN boards b ON b.id = :board
        LEFT JOIN board_weights w ON w.board_id = b.id AND r.kind = 'emoji' AND w.emoji = r.key
        WHERE {' AND '.join(where)}
        GROUP BY r.msg_id
        HAVING score > 0"""

    total = conn.execute(f"SELECT COUNT(*) FROM ({scored})", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT s.score, m.msg_id, m.date, m.sender, m.text, m.media, m.topic_id, t.title AS topic
            FROM ({scored}) s
            JOIN messages m ON m.chat_id = :chat AND m.msg_id = s.msg_id
            LEFT JOIN topics t ON t.chat_id = m.chat_id AND t.topic_id = m.topic_id
            ORDER BY s.score DESC, m.date DESC, m.msg_id DESC
            LIMIT :limit OFFSET :offset""",
        {**params, "limit": q.limit, "offset": q.offset},
    ).fetchall()

    reacts = _reactions_for(conn, q.chat_id, [r["msg_id"] for r in rows])
    items = [{
        "msg_id": r["msg_id"], "date": r["date"], "sender": r["sender"],
        "text": r["text"] if len(r["text"]) <= TEXT_LIMIT else r["text"][:TEXT_LIMIT] + "…",
        "media": r["media"], "topic_id": r["topic_id"], "topic": r["topic"],
        "score": _fmt_score(r["score"]), "reactions": reacts.get(r["msg_id"], []),
    } for r in rows]
    return RankPage(items, total, link_base(q.chat_id, chat["kind"]) if chat else None)


def _reactions_for(conn, chat_id: int, ids: list[int]) -> dict[int, list[dict]]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict[int, list[dict]] = {}
    for r in conn.execute(
        f"SELECT msg_id, kind, key, count FROM reactions WHERE chat_id = ? AND msg_id IN ({marks}) ORDER BY count DESC, kind, key",
        (chat_id, *ids),
    ):
        out.setdefault(r["msg_id"], []).append({"label": reaction_label(r["kind"], r["key"]), "count": r["count"]})
    return out


def emoji_stats(conn, chat_id: int) -> list[dict]:
    """该群出现过的反应及总次数，建榜单时供用户挑选表情。"""
    return [
        {"kind": r["kind"], "key": r["key"], "label": reaction_label(r["kind"], r["key"]), "count": r["n"]}
        for r in conn.execute(
            """SELECT kind, key, SUM(count) AS n FROM reactions WHERE chat_id = ?
               GROUP BY kind, key ORDER BY n DESC, kind, key""", (chat_id,))
    ]
