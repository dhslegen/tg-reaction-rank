import shutil
from zoneinfo import ZoneInfo

import pytest

from conftest import FIXTURES
from tgrank import store
from tgrank.desktop import DesktopFormatError
from tgrank.importer import run_import
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R

TZ = ZoneInfo("Asia/Shanghai")
FORUM = -1002222222222


@pytest.fixture
def db_path(tmp_path, conn):
    return tmp_path / "test.db"  # 与 conftest 的 conn 同一个库，已迁移


def copy(tmp_path, name):
    dst = tmp_path / f"upload-{name}"
    shutil.copy(FIXTURES / name, dst)
    return dst


def test_import_forum_end_to_end(tmp_path, db_path, conn):
    seen = []
    result = run_import(db_path, copy(tmp_path, "desktop_forum.json"), TZ, progress=seen.append, batch=2)
    assert (result.chat_id, result.title, result.messages, result.reacted) == (FORUM, "读书会", 5, 5)
    assert result.stats.inserted == 5
    assert seen and seen[-1] == 5
    topics = dict(conn.execute("SELECT msg_id, topic_id FROM messages ORDER BY msg_id").fetchall())
    assert topics == {1: 1, 11: 10, 12: 10, 21: 20, 23: 1}  # 话题前的消息已回填 General
    assert dict(conn.execute("SELECT topic_id, title FROM topics").fetchall()) == {1: "General", 10: "科幻", 20: "中国历史"}
    assert conn.execute("SELECT is_forum, sync_enabled FROM chats").fetchone()[:] == (1, 0)


def test_import_keeps_api_data_and_topic_titles(tmp_path, db_path, conn):
    store.upsert_chat(conn, ChatInfo(FORUM, "读书会", "public_supergroup", is_forum=True), sync_enabled=True)
    store.upsert_topics(conn, FORUM, [store_topic(10, "科幻（API 名）")], overwrite=True)
    store.upsert_api_messages(conn, FORUM, [MessageRecord(12, 1, "乙", "API 正文", None, 11, 10, (R("emoji", "😂", 99),))], now=5)
    result = run_import(db_path, copy(tmp_path, "desktop_forum.json"), TZ)
    assert result.stats.kept == 1
    assert conn.execute("SELECT text FROM messages WHERE msg_id=12").fetchone()[0] == "API 正文"
    assert conn.execute("SELECT title FROM topics WHERE topic_id=10").fetchone()[0] == "科幻（API 名）"
    assert conn.execute("SELECT sync_enabled FROM chats").fetchone()[0] == 1


def store_topic(tid, title):
    from tgrank.records import TopicRecord
    return TopicRecord(tid, title)


def test_bad_file_raises_and_leaves_no_chat(tmp_path, db_path, conn):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "x"}')
    with pytest.raises(DesktopFormatError):
        run_import(db_path, bad, TZ)
    assert conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 0


def test_truncated_file_rolls_back_partial_batches(tmp_path, db_path, conn):
    raw = (FIXTURES / "desktop_basic.json").read_text(encoding="utf-8")
    cut = tmp_path / "cut.json"
    cut.write_text(raw[: raw.index('"id": 6')], encoding="utf-8")
    with pytest.raises(DesktopFormatError):
        run_import(db_path, cut, TZ, batch=2)
    # 部分批次已写入是可接受的（下次重导会补齐），但不能有半条消息：反应与消息一致
    orphans = conn.execute("SELECT COUNT(*) FROM reactions r LEFT JOIN messages m USING(chat_id, msg_id) WHERE m.msg_id IS NULL").fetchone()[0]
    assert orphans == 0
