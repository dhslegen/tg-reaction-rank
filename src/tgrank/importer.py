"""把上传的 Desktop 导出文件流式写入数据库。

按批提交：每批一个事务，中途出错只回滚当前批，已提交的批次在重新导入时会被覆盖或保留（API 优先）。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from . import store
from .db import connect, transaction
from .desktop import DesktopExport
from .records import MessageRecord, TopicRecord
from .store import ImportStats


@dataclass(frozen=True)
class ImportResult:
    chat_id: int
    title: str
    messages: int
    reacted: int
    stats: ImportStats

    def view(self) -> dict:
        return {**asdict(self), "stats": asdict(self.stats)}


def run_import(db_path: Path, file_path: Path, tz: ZoneInfo, *,
               progress: Callable[[int], None] = lambda n: None, batch: int = 1000) -> ImportResult:
    with open(file_path, "rb") as fp, connect(db_path) as conn:
        exp = DesktopExport(fp, tz)
        chat_id = exp.info.chat_id
        store.upsert_chat(conn, exp.info, sync_enabled=False)

        topics: dict[int, str] = {}   # 同一话题多次出现（改名）时以最后一次为准
        pending: list[MessageRecord] = []
        stats, count, reacted = ImportStats(), 0, 0

        def flush():
            nonlocal stats, pending
            with transaction(conn):
                stats += store.import_messages(conn, chat_id, pending)
            pending = []
            progress(count)

        for item in exp.records():
            if isinstance(item, TopicRecord):
                topics[item.topic_id] = item.title
                continue
            pending.append(item)
            count += 1
            reacted += bool(item.reactions)
            if len(pending) >= batch:
                flush()
        flush()

        api_synced = conn.execute("SELECT sync_enabled FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()[0]
        with transaction(conn):
            store.upsert_topics(conn, chat_id, [TopicRecord(k, v) for k, v in topics.items()], overwrite=not api_synced)
            if exp.is_forum:
                store.mark_forum(conn, chat_id, first_topic_id=exp.first_topic_id)
        return ImportResult(chat_id, exp.info.title, count, reacted, stats)
