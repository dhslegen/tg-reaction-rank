from tgrank import store
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R, TopicRecord

CHAT = ChatInfo(-1001, "群", "private_supergroup")


def msg(i, text="t", reactions=(), date=1000, reply_to=None, topic_id=None):
    return MessageRecord(i, date, "u", text, None, reply_to, topic_id, tuple(reactions))


def reactions_of(conn, i):
    return sorted(tuple(r) for r in conn.execute(
        "SELECT kind, key, count FROM reactions WHERE chat_id=? AND msg_id=?", (CHAT.chat_id, i)))


def row(conn, i):
    return conn.execute("SELECT * FROM messages WHERE chat_id=? AND msg_id=?", (CHAT.chat_id, i)).fetchone()


def test_upsert_chat_keeps_sync_enabled_once_set(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_chat(conn, ChatInfo(-1001, "改名", "private_supergroup"), sync_enabled=False)
    r = conn.execute("SELECT title, sync_enabled FROM chats").fetchone()
    assert tuple(r) == ("改名", 1)


def test_api_upsert_replaces_reactions_and_marks_synced(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1, reactions=[R("emoji", "👍", 2), R("emoji", "😂", 1)])], now=50)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1, text="改过", reactions=[R("emoji", "👍", 3)])], now=60)
    assert reactions_of(conn, 1) == [("emoji", "👍", 3)]
    assert row(conn, 1)["text"] == "改过" and row(conn, 1)["api_synced_at"] == 60


def test_api_upsert_removes_all_reactions_when_gone(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1, reactions=[R("emoji", "👍", 2)])], now=1)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1)], now=2)
    assert reactions_of(conn, 1) == []


def test_import_inserts_and_overwrites_previous_import(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=False)
    stats = store.import_messages(conn, CHAT.chat_id, [msg(1, reactions=[R("emoji", "👍", 1)])])
    assert stats == store.ImportStats(inserted=1, updated=0, kept=0)
    stats = store.import_messages(conn, CHAT.chat_id, [msg(1, text="新导出", reactions=[R("emoji", "👍", 4)])])
    assert stats == store.ImportStats(inserted=0, updated=1, kept=0)
    assert reactions_of(conn, 1) == [("emoji", "👍", 4)] and row(conn, 1)["text"] == "新导出"


def test_import_does_not_override_api_synced_message(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1, text="API 版", reactions=[R("emoji", "👍", 9)])], now=5)
    stats = store.import_messages(conn, CHAT.chat_id, [msg(1, text="旧导出", reactions=[R("emoji", "👍", 2)])])
    assert stats.kept == 1
    assert row(conn, 1)["text"] == "API 版" and reactions_of(conn, 1) == [("emoji", "👍", 9)]


def test_import_fills_missing_structure_on_api_message(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(2, reply_to=None, topic_id=None)], now=5)
    store.import_messages(conn, CHAT.chat_id, [msg(2, reply_to=1, topic_id=10)])
    assert (row(conn, 2)["reply_to"], row(conn, 2)["topic_id"]) == (1, 10)


def test_topics_overwrite_or_insert_missing(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_topics(conn, CHAT.chat_id, [TopicRecord(10, "科幻")], overwrite=True)
    store.upsert_topics(conn, CHAT.chat_id, [TopicRecord(10, "旧名"), TopicRecord(20, "历史")], overwrite=False)
    assert dict(conn.execute("SELECT topic_id, title FROM topics").fetchall()) == {10: "科幻", 20: "历史"}
    store.upsert_topics(conn, CHAT.chat_id, [TopicRecord(10, "硬科幻")], overwrite=True)
    assert conn.execute("SELECT title FROM topics WHERE topic_id=10").fetchone()[0] == "硬科幻"


def test_backfill_general_and_forum_flag(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=False)
    store.import_messages(conn, CHAT.chat_id, [msg(1), msg(5), msg(11, topic_id=10), msg(12)])
    store.mark_forum(conn, CHAT.chat_id, first_topic_id=10)
    assert [r[0] for r in conn.execute("SELECT topic_id FROM messages ORDER BY msg_id")] == [1, 1, 10, None]
    assert conn.execute("SELECT is_forum FROM chats").fetchone()[0] == 1


def test_delete_and_queries(conn):
    store.upsert_chat(conn, CHAT, sync_enabled=True)
    store.upsert_api_messages(conn, CHAT.chat_id, [msg(1, date=100, reactions=[R("paid", "", 1)]), msg(2, date=200), msg(3, date=300)], now=1)
    assert store.max_msg_id(conn, CHAT.chat_id) == 3
    assert store.ids_since(conn, CHAT.chat_id, 200) == [2, 3]
    assert store.delete_messages(conn, CHAT.chat_id, [1, 3, 99]) == 2
    assert store.max_msg_id(conn, CHAT.chat_id) == 2
    assert reactions_of(conn, 1) == []
    assert store.max_msg_id(conn, -42) is None
