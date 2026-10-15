"""API 同步的三种流程。每次 Telegram 请求只取一页（≤100 条），每页一个事务提交，
所以中途失败或重启后都能从本地最大 id 继续。

- fetch_new：从本地最大 id 往后拉到没有为止；首次添加群时就是全量回填。
- refresh_recent：按 id 批量重取最近 N 天的消息，更新反应/编辑，消失的删除。
- calibrate：全量重扫，修正老消息的编辑与删除；只删除「API 可见范围」内确实消失的消息。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from telethon import errors

from .. import store
from ..db import connect, transaction
from ..records import ChatInfo, MessageRecord, TopicRecord
from .manager import TgManager, TgUnavailable
from .mapping import GENERAL_TOPIC_ID, input_peer, to_record

log = logging.getLogger(__name__)
PAGE = 100
NO_ACCESS = (errors.ChannelPrivateError, errors.ChannelInvalidError, errors.PeerIdInvalidError,
             errors.ChatIdInvalidError, errors.ChatForbiddenError)


class Syncer:
    def __init__(self, mgr: TgManager, db_path: Path, *, clock: Callable[[], float] = time.time):
        self.mgr, self.db_path, self.clock = mgr, db_path, clock
        self._locks: dict[int, asyncio.Lock] = {}

    @asynccontextmanager
    async def chat_lock(self, chat_id: int):
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            yield

    def busy(self, chat_id: int) -> bool:
        lock = self._locks.get(chat_id)
        return lock is not None and lock.locked()

    def _chat(self, chat_id: int):
        with connect(self.db_path) as conn:
            return conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()

    async def add_chat(self, info: ChatInfo) -> None:
        with connect(self.db_path) as conn, transaction(conn):
            store.upsert_chat(conn, info, sync_enabled=True)
            conn.execute("UPDATE chats SET last_error = NULL WHERE chat_id = ?", (info.chat_id,))
            if info.is_forum:
                store.upsert_topics(conn, info.chat_id, [TopicRecord(GENERAL_TOPIC_ID, "General")], overwrite=False)

    # ---------- 公共骨架 ----------
    async def _guarded(self, chat_id: int, body):
        """每群一把锁（忙则跳过），并把错误记到 chats.last_error 而不是让调度任务崩掉。"""
        if self.busy(chat_id):
            return None
        async with self.chat_lock(chat_id):
            chat = self._chat(chat_id)
            if chat is None or not chat["sync_enabled"]:
                return None
            try:
                result = await body(chat)
            except TgUnavailable:
                raise
            except NO_ACCESS:
                self._set_error(chat_id, "无法访问这个群（可能已退群或被移出），已暂停同步", pause=True)
                return None
            except errors.FloodWaitError as e:
                self._set_error(chat_id, f"Telegram 限流 {e.seconds} 秒，本轮已跳过，稍后自动重试")
                return None
            except Exception as e:
                log.exception("同步群 %s 失败", chat_id)
                self._set_error(chat_id, f"同步失败：{e}")
                return None
            self._set_error(chat_id, None)
            return result

    def _set_error(self, chat_id: int, message: str | None, *, pause: bool = False) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE chats SET last_error = ?, sync_enabled = CASE WHEN ? THEN 0 ELSE sync_enabled END WHERE chat_id = ?",
                (message, pause, chat_id))

    def _write_page(self, chat, page, *, stamp_column: str | None = None) -> int:
        """把一页 Telethon 消息写库，返回写入的普通消息条数。"""
        records = [to_record(m, chat_title=chat["title"], is_forum=bool(chat["is_forum"])) for m in page if m is not None]
        messages = [r for r in records if isinstance(r, MessageRecord)]
        topics = [r for r in records if isinstance(r, TopicRecord)]
        now = int(self.clock())
        with connect(self.db_path) as conn, transaction(conn):
            store.upsert_api_messages(conn, chat["chat_id"], messages, now=now)
            store.upsert_topics(conn, chat["chat_id"], topics, overwrite=True)
            if stamp_column:
                conn.execute(f"UPDATE chats SET {stamp_column} = ? WHERE chat_id = ?", (now, chat["chat_id"]))
        return len(messages)

    async def _page_after(self, chat, min_id: int):
        peer = input_peer(chat["chat_id"], chat["access_hash"])
        return await self.mgr.call(lambda c: c.get_messages(peer, limit=PAGE, min_id=min_id, reverse=True))

    # ---------- 三种流程 ----------
    async def fetch_new(self, chat_id: int) -> int | None:
        async def body(chat):
            with connect(self.db_path) as conn:
                cursor = store.max_msg_id(conn, chat_id) or 0
            total = 0
            while page := [m for m in await self._page_after(chat, cursor) if m is not None]:
                total += self._write_page(chat, page, stamp_column="last_sync_at")
                cursor = max(m.id for m in page)
            with connect(self.db_path) as conn:
                conn.execute("UPDATE chats SET history_complete = 1, last_sync_at = ? WHERE chat_id = ?",
                             (int(self.clock()), chat_id))
            return total
        return await self._guarded(chat_id, body)

    async def refresh_recent(self, chat_id: int, *, days: int) -> tuple[int, int] | None:
        async def body(chat):
            with connect(self.db_path) as conn:
                ids = store.ids_since(conn, chat_id, int(self.clock()) - days * 86400)
            peer = input_peer(chat_id, chat["access_hash"])
            updated = deleted = 0
            for i in range(0, len(ids), PAGE):
                batch = ids[i:i + PAGE]
                found = await self.mgr.call(lambda c, b=batch: c.get_messages(peer, ids=b))
                gone = [mid for mid, m in zip(batch, found) if m is None]
                updated += self._write_page(chat, found)
                if gone:
                    with connect(self.db_path) as conn, transaction(conn):
                        deleted += store.delete_messages(conn, chat_id, gone)
            with connect(self.db_path) as conn:
                conn.execute("UPDATE chats SET last_refresh_at = ? WHERE chat_id = ?", (int(self.clock()), chat_id))
            return updated, deleted
        return await self._guarded(chat_id, body)

    async def calibrate(self, chat_id: int) -> tuple[int, int] | None:
        async def body(chat):
            if not chat["history_complete"]:
                return None
            with connect(self.db_path) as conn:
                ceiling = store.max_msg_id(conn, chat_id) or 0
            seen: set[int] = set()
            first_seen: int | None = None
            cursor = updated = 0
            # 任何异常都会直接跳出、不执行下面的删除：扫描不完整时宁可不删
            while page := [m for m in await self._page_after(chat, cursor) if m is not None]:
                updated += self._write_page(chat, page)
                ids = [m.id for m in page]
                seen.update(ids)
                first_seen = ids[0] if first_seen is None else first_seen
                cursor = max(ids)
            deleted = 0
            if first_seen is not None:
                with connect(self.db_path) as conn, transaction(conn):
                    local = [r[0] for r in conn.execute(
                        "SELECT msg_id FROM messages WHERE chat_id = ? AND msg_id BETWEEN ? AND ?",
                        (chat_id, first_seen, ceiling))]
                    deleted = store.delete_messages(conn, chat_id, [i for i in local if i not in seen])
                    conn.execute("UPDATE chats SET last_calibrate_at = ? WHERE chat_id = ?", (int(self.clock()), chat_id))
            return updated, deleted
        return await self._guarded(chat_id, body)

    async def run_all(self, kind: str, **kwargs) -> None:
        """对所有开启同步的群执行一种流程；Telegram 整体不可用时立即停止。"""
        with connect(self.db_path) as conn:
            chat_ids = [r[0] for r in conn.execute("SELECT chat_id FROM chats WHERE sync_enabled = 1 ORDER BY chat_id")]
        for chat_id in chat_ids:
            try:
                await getattr(self, kind)(chat_id, **kwargs)
            except TgUnavailable:
                log.info("Telegram 当前不可用（%s），跳过本轮 %s", self.mgr.state.value, kind)
                return
