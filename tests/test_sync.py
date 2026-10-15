import pytest
from telethon.errors import ChannelPrivateError, FloodWaitError

from fakes import channel, emoji, message, topic_created, user
from tgrank import store
from tgrank.db import connect
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R
from tgrank.tg.mapping import chat_info
from tgrank.tg.sync import Syncer

NOW = 1_790_000_000
DAY = 86400
A = user(7, "阿明")


def msgs(n, *, start=1, ts=NOW - 30 * DAY):
    return [message(i, f"消息{i}", ts=ts + i, sender=A, reactions=[emoji("👍", i)]) for i in range(start, start + n)]


@pytest.fixture
def syncer(authed, tg_env):
    return Syncer(authed, tg_env.db_path, clock=lambda: NOW)


def rows(tg_env, sql, *args):
    with connect(tg_env.db_path) as c:
        return c.execute(sql, args).fetchall()


async def add(syncer, world, entity, history):
    world.add_chat(entity, history)
    info = chat_info(entity)
    await syncer.add_chat(info)
    return info.chat_id


async def test_fetch_new_pages_until_empty_and_marks_complete(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(250))
    assert await syncer.fetch_new(cid) == 250
    assert world.calls.count("get_messages") == 4  # 100+100+50+空页
    assert rows(tg_env, "SELECT COUNT(*) FROM messages")[0][0] == 250
    chat = rows(tg_env, "SELECT history_complete, last_sync_at, sync_enabled FROM chats")[0]
    assert tuple(chat) == (1, NOW, 1)
    assert rows(tg_env, "SELECT api_synced_at FROM messages LIMIT 1")[0][0] == NOW


async def test_fetch_new_is_incremental(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(5))
    await syncer.fetch_new(cid)
    world.history[cid].update({m.id: m for m in msgs(3, start=6)})
    assert await syncer.fetch_new(cid) == 3


async def test_fetch_new_resumes_after_interruption(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(250))
    calls = {"n": 0}
    orig = world.clients[-1].get_messages

    async def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("服务端临时错误")
        return await orig(*a, **kw)
    world.clients[-1].get_messages = flaky
    await syncer.fetch_new(cid)
    assert rows(tg_env, "SELECT COUNT(*) FROM messages")[0][0] == 100  # 第一页已提交
    assert rows(tg_env, "SELECT history_complete FROM chats")[0][0] == 0
    world.clients[-1].get_messages = orig
    await syncer.fetch_new(cid)
    assert rows(tg_env, "SELECT COUNT(*) FROM messages")[0][0] == 250


async def test_forum_topics_from_api(syncer, world, tg_env):
    hist = [message(1, "general", ts=NOW), topic_created(10, "科幻", ts=NOW),
            message(11, "三体", ts=NOW, reply_to=10, forum_topic=True, reactions=[emoji("👍", 1)])]
    cid = await add(syncer, world, channel(1000000002, "读书会", forum=True), hist)
    await syncer.fetch_new(cid)
    assert dict(rows(tg_env, "SELECT topic_id, title FROM topics")) == {1: "General", 10: "科幻"}
    assert dict(rows(tg_env, "SELECT msg_id, topic_id FROM messages")) == {1: 1, 11: 10}


async def test_refresh_recent_updates_and_deletes(syncer, world, tg_env):
    old = message(1, "老消息", ts=NOW - 30 * DAY, reactions=[emoji("👍", 1)])
    recent = [message(i, f"新{i}", ts=NOW - DAY, reactions=[emoji("👍", 1)]) for i in (2, 3)]
    cid = await add(syncer, world, channel(1000000001, "群"), [old, *recent])
    await syncer.fetch_new(cid)
    world.history[cid][2] = message(2, "新2（已编辑）", ts=NOW - DAY, reactions=[emoji("👍", 9)])
    world.history[cid][1] = message(1, "老消息", ts=NOW - 30 * DAY, reactions=[emoji("👍", 50)])
    del world.history[cid][3]
    assert await syncer.refresh_recent(cid, days=7) == (1, 1)
    assert dict(rows(tg_env, "SELECT msg_id, count FROM reactions")) == {1: 1, 2: 9}  # 老消息不在刷新窗口
    assert rows(tg_env, "SELECT text FROM messages WHERE msg_id=2")[0][0] == "新2（已编辑）"


async def test_refresh_batches_of_100(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(230, ts=NOW - DAY))
    await syncer.fetch_new(cid)
    world.calls.clear()
    await syncer.refresh_recent(cid, days=7)
    assert world.calls.count("get_messages") == 3


async def test_calibrate_deletes_vanished_and_updates(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(5))
    await syncer.fetch_new(cid)
    del world.history[cid][2]
    world.history[cid][4] = message(4, "改过", ts=NOW - 30 * DAY + 4, reactions=[emoji("😂", 3)])
    assert await syncer.calibrate(cid) == (4, 1)
    assert [r[0] for r in rows(tg_env, "SELECT msg_id FROM messages ORDER BY msg_id")] == [1, 3, 4, 5]
    assert rows(tg_env, "SELECT key FROM reactions WHERE msg_id=4")[0][0] == "😂"


async def test_calibrate_keeps_messages_outside_visible_range(syncer, world, tg_env):
    """新成员不可见历史：API 只能看到 50 之后的消息，导入的 1..10 不能被当成已删除。"""
    entity = channel(1000000001, "群")
    cid = await add(syncer, world, entity, msgs(5, start=50))
    with connect(tg_env.db_path) as c:
        store.import_messages(c, cid, [MessageRecord(i, NOW - 400 * DAY, "u", "导入", None, None, None, (R("emoji", "👍", 1),)) for i in range(1, 11)])
    await syncer.fetch_new(cid)
    await syncer.calibrate(cid)
    assert rows(tg_env, "SELECT COUNT(*) FROM messages")[0][0] == 15


async def test_calibrate_aborts_on_error_without_deleting(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(150))
    await syncer.fetch_new(cid)
    for i in range(1, 150):
        del world.history[cid][i]
    world.fail("get_messages", FloodWaitError(request=None, capture=99999))
    await syncer.calibrate(cid)
    assert rows(tg_env, "SELECT COUNT(*) FROM messages")[0][0] == 150
    assert "限流" in rows(tg_env, "SELECT last_error FROM chats")[0][0]


async def test_calibrate_skipped_until_history_complete(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(5))
    assert await syncer.calibrate(cid) is None


async def test_inaccessible_chat_paused_with_reason(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(5))
    del world.history[cid]  # 假世界里取不到历史 → ChannelPrivateError
    await syncer.fetch_new(cid)
    chat = rows(tg_env, "SELECT sync_enabled, last_error FROM chats")[0]
    assert chat[0] == 0 and "无法访问" in chat[1]


async def test_busy_chat_is_skipped(syncer, world, tg_env):
    cid = await add(syncer, world, channel(1000000001, "群"), msgs(5))
    async with syncer.chat_lock(cid):
        assert await syncer.fetch_new(cid) is None


async def test_run_all_iterates_enabled_chats(syncer, world, tg_env):
    a = await add(syncer, world, channel(1000000001, "甲"), msgs(3))
    b = await add(syncer, world, channel(1000000002, "乙"), msgs(4))
    with connect(tg_env.db_path) as c:
        store.upsert_chat(c, ChatInfo(-1000000000009, "导入群", "private_supergroup"), sync_enabled=False)
    await syncer.run_all("fetch_new")
    counts = dict(rows(tg_env, "SELECT chat_id, COUNT(*) FROM messages GROUP BY chat_id"))
    assert counts == {a: 3, b: 4}


async def test_basic_group_uses_input_peer_chat(syncer, world, tg_env):
    from telethon.tl import types
    basic = types.Chat(id=4242, title="小群", photo=types.ChatPhotoEmpty(), participants_count=3, date=None, version=1)
    cid = await add(syncer, world, basic, [message(1, "hi", ts=NOW, reactions=[emoji("👍", 1)])])
    assert cid == -4242
    assert await syncer.fetch_new(cid) == 1
