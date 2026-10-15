"""写入与基础查询。函数本身不开事务，由调用方用 db.transaction() 按批包裹。"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass

from .records import ChatInfo, MessageRecord, TopicRecord

GENERAL_TOPIC_ID = 1


@dataclass(frozen=True)
class ImportStats:
    inserted: int = 0
    updated: int = 0
    kept: int = 0   # 已有 API 同步版本，只补结构字段

    def __add__(self, o: ImportStats) -> ImportStats:
        return ImportStats(self.inserted + o.inserted, self.updated + o.updated, self.kept + o.kept)


def upsert_chat(conn: sqlite3.Connection, info: ChatInfo, *, sync_enabled: bool) -> None:
    conn.execute(
        """INSERT INTO chats(chat_id, title, kind, username, access_hash, is_forum, sync_enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET
             title = excluded.title, kind = excluded.kind,
             username = COALESCE(excluded.username, chats.username),
             access_hash = COALESCE(excluded.access_hash, chats.access_hash),
             is_forum = MAX(chats.is_forum, excluded.is_forum),
             sync_enabled = MAX(chats.sync_enabled, excluded.sync_enabled)""",
        (info.chat_id, info.title, info.kind, info.username, info.access_hash, int(info.is_forum), int(sync_enabled), int(time.time())),
    )


def _replace_reactions(conn, chat_id: int, m: MessageRecord) -> None:
    conn.execute("DELETE FROM reactions WHERE chat_id = ? AND msg_id = ?", (chat_id, m.msg_id))
    conn.executemany(
        """INSERT INTO reactions(chat_id, msg_id, kind, key, count) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT DO UPDATE SET count = count + excluded.count""",  # 同一归一键出现两次时合并
        [(chat_id, m.msg_id, r.kind, r.key, r.count) for r in m.reactions],
    )


def _write_message(conn, chat_id: int, m: MessageRecord, api_synced_at: int | None) -> None:
    conn.execute(
        """INSERT INTO messages(chat_id, msg_id, date, sender, text, media, reply_to, topic_id, api_synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id, msg_id) DO UPDATE SET
             date = excluded.date, sender = excluded.sender, text = excluded.text, media = excluded.media,
             reply_to = excluded.reply_to,
             topic_id = COALESCE(excluded.topic_id, messages.topic_id),
             api_synced_at = COALESCE(excluded.api_synced_at, messages.api_synced_at)""",
        (chat_id, m.msg_id, m.date, m.sender, m.text, m.media, m.reply_to, m.topic_id, api_synced_at),
    )
    _replace_reactions(conn, chat_id, m)


def upsert_api_messages(conn, chat_id: int, records: Iterable[MessageRecord], *, now: int) -> int:
    """API 数据是权威来源：整体覆盖正文与反应，并打上同步时间。"""
    n = 0
    for m in records:
        _write_message(conn, chat_id, m, now)
        n += 1
    return n


def import_messages(conn, chat_id: int, records: Iterable[MessageRecord]) -> ImportStats:
    """导出文件通常是比 API 更旧的快照，所以 API 同步过的消息只补空的结构字段。"""
    inserted = updated = kept = 0
    for m in records:
        cur = conn.execute(
            "SELECT api_synced_at FROM messages WHERE chat_id = ? AND msg_id = ?", (chat_id, m.msg_id)
        ).fetchone()
        if cur is None:
            _write_message(conn, chat_id, m, None)
            inserted += 1
        elif cur["api_synced_at"] is None:
            _write_message(conn, chat_id, m, None)
            updated += 1
        else:
            conn.execute(
                """UPDATE messages SET reply_to = COALESCE(reply_to, ?), topic_id = COALESCE(topic_id, ?)
                   WHERE chat_id = ? AND msg_id = ?""",
                (m.reply_to, m.topic_id, chat_id, m.msg_id),
            )
            kept += 1
    return ImportStats(inserted, updated, kept)


def upsert_topics(conn, chat_id: int, topics: Iterable[TopicRecord], *, overwrite: bool) -> None:
    conflict = "DO UPDATE SET title = excluded.title" if overwrite else "DO NOTHING"
    conn.executemany(
        f"INSERT INTO topics(chat_id, topic_id, title) VALUES (?, ?, ?) ON CONFLICT(chat_id, topic_id) {conflict}",
        [(chat_id, t.topic_id, t.title) for t in topics],
    )


def mark_forum(conn, chat_id: int, *, first_topic_id: int | None) -> None:
    """标记为话题群；第一个话题创建前的消息都属于 General。"""
    conn.execute("UPDATE chats SET is_forum = 1 WHERE chat_id = ?", (chat_id,))
    if first_topic_id is not None:
        conn.execute(
            "UPDATE messages SET topic_id = ? WHERE chat_id = ? AND topic_id IS NULL AND msg_id < ?",
            (GENERAL_TOPIC_ID, chat_id, first_topic_id),
        )


def delete_messages(conn, chat_id: int, ids: Iterable[int]) -> int:
    ids = list(ids)
    n = 0
    for i in range(0, len(ids), 500):  # 避开 SQLite 变量个数上限
        chunk = ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        n += conn.execute(f"DELETE FROM messages WHERE chat_id = ? AND msg_id IN ({marks})", (chat_id, *chunk)).rowcount
    return n


def max_msg_id(conn, chat_id: int) -> int | None:
    return conn.execute("SELECT MAX(msg_id) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()[0]


def ids_since(conn, chat_id: int, since_ts: int) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT msg_id FROM messages WHERE chat_id = ? AND date >= ? ORDER BY msg_id", (chat_id, since_ts))]
