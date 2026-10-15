"""定期精华推送：每群 × 每个启用推送的榜单取前 10，发到收藏夹或私人频道。

不推回原群：账号通常不是原群管理员，往原群发机器生成的消息容易触发风控。
"""
from __future__ import annotations

import html
import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import boards
from .db import connect
from .ranking import RankQuery, rank
from .settings import PushSettings, Settings, load_settings
from .tg.manager import TgManager, TgUnavailable
from .tg.mapping import input_peer

log = logging.getLogger(__name__)
TOP_N = 10
LIMIT = 4000          # Telegram 单条上限 4096（UTF-16 单元），留余量；这里按含 HTML 标签的长度算，更保守
SUMMARY_CHARS = 80
RESULT_KEY = "push_last"


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _summary(item: dict) -> str:
    text = " ".join(item["text"].split())
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS] + "…"
    return " ".join(p for p in (item["media"], text) if p) or "（无文字）"


def _entry(n: int, item: dict, link_base: str | None) -> str:
    line = f"{n}. <b>{item['score']} 分</b> {html.escape(item['sender'])}：{html.escape(_summary(item))}"
    if link_base:
        line += f' <a href="{link_base}{item["msg_id"]}">打开原消息</a>'
    return line


def _midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, dtime.min, tzinfo=tz)


def _shift_month(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return d.replace(year=y, month=m + 1)  # monthday 限定 1–28，任何月份都存在


def push_window(p: PushSettings, tz: ZoneInfo, now: datetime) -> tuple[datetime, datetime]:
    """本期统计区间 [start, end)，均为 TZ 下的 00:00。

    默认以「上一个触发日 → 本次触发日」为界，相邻两期首尾相接、不漏不重；触发日当天的消息归下一期。
    手动设了 range_days 时取今天之前的 N 个完整自然日。手动测试推送按同一规则，把当前时刻视为触发时刻。
    """
    today = now.astimezone(tz).date()
    if p.range_days:
        end = today
        return _midnight(end - timedelta(days=p.range_days), tz), _midnight(end, tz)
    if p.frequency == "weekly":
        end = today - timedelta(days=(today.weekday() - p.weekday) % 7)
        return _midnight(end - timedelta(days=7), tz), _midnight(end, tz)
    end = today.replace(day=p.monthday) if today.day >= p.monthday else _shift_month(today.replace(day=p.monthday), -1)
    return _midnight(_shift_month(end, -1), tz), _midnight(end, tz)


def _md(d: date) -> str:
    return f"{d.month}月{d.day}日"


def build_digest(conn, settings: Settings, tz: ZoneInfo, now: datetime) -> list[str]:
    """返回已分段的 HTML 消息；分段只发生在条目之间，续段会重复小标题。"""
    start, end = push_window(settings.push, tz, now)
    window = (int(start.timestamp()), int(end.timestamp()))
    push_boards = [b for b in boards.list_boards(conn) if b["push_enabled"]]
    chats = conn.execute(
        "SELECT chat_id, title FROM chats c WHERE EXISTS (SELECT 1 FROM reactions r WHERE r.chat_id = c.chat_id) ORDER BY title"
    ).fetchall()

    sections: list[tuple[str, list[str]]] = []
    for chat in chats:
        for b in push_boards:
            page = rank(conn, RankQuery(chat["chat_id"], b["id"], window=window, limit=TOP_N), tz, now)
            if page.items:
                title = f"<b>{html.escape(chat['title'])} · {html.escape(b['name'])}</b>"
                sections.append((title, [_entry(i + 1, it, page.link_base) for i, it in enumerate(page.items)]))
    if not sections:
        return []

    parts: list[str] = []
    current = f"🏆 <b>{_md(start.date())}–{_md((end - timedelta(days=1)).date())} 精华</b>"
    for title, entries in sections:
        current += f"\n\n{title}"
        for entry in entries:
            if utf16_len(current) + 1 + utf16_len(entry) > LIMIT:
                parts.append(current)
                current = f"{title}（续）"
            current += f"\n{entry}"
    parts.append(current)
    return parts


def _record(conn, *, ok: bool, sent: int, error: str | None) -> None:
    value = json.dumps({"at": int(time.time()), "ok": ok, "sent": sent, "error": error}, ensure_ascii=False)
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (RESULT_KEY, value))


def last_push(conn) -> dict | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (RESULT_KEY,)).fetchone()
    return json.loads(row[0]) if row else None


async def send_digest(mgr: TgManager, db_path: Path, tz: ZoneInfo, now: datetime, *, force: bool = False) -> int:
    """生成并发送精华；结果（含失败原因）写入 meta，设置页可见，绝不静默失败。"""
    with connect(db_path) as conn:
        settings = load_settings(conn)
        if not settings.push.enabled and not force:
            return 0
        parts = build_digest(conn, settings, tz, now)
    sent = 0
    try:
        if not parts:
            with connect(db_path) as conn:
                _record(conn, ok=True, sent=0, error="这段时间没有收到反应的消息，没有可推送的内容")
            return 0
        target = settings.push.target
        if target == "me":
            entity = "me"
        else:
            found = next((d for d in await mgr.list_dialogs() if str(d.chat_id) == target), None)
            if found is None:
                raise LookupError("找不到推送目标频道，请在设置页重新选择")
            entity = input_peer(found.chat_id, found.access_hash)
        for part in parts:
            await mgr.call(lambda c, p=part: c.send_message(entity, p, parse_mode="html", link_preview=False))
            sent += 1
    except TgUnavailable:
        error = f"Telegram 当前不可用（状态：{mgr.state.value}），请在「Telegram」页检查登录"
    except Exception as e:
        log.exception("精华推送失败")
        error = f"推送失败：{e}"
    else:
        with connect(db_path) as conn:
            _record(conn, ok=True, sent=sent, error=None)
        return sent
    with connect(db_path) as conn:
        _record(conn, ok=False, sent=sent, error=error)
    return sent
