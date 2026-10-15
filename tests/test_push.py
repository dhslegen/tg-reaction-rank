from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fakes import channel
from tgrank import boards, store
from tgrank.boards import BoardIn
from tgrank.db import connect
from tgrank.push import LIMIT, build_digest, last_push, send_digest, utf16_len
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R
from tgrank.settings import PushSettings, Settings, save_settings

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)  # 周一
TS = int(NOW.timestamp())
CHAT = -1001234567890


def seed(conn, n=3, text="正文", ago_days=1, chat=CHAT, title="饭群"):
    store.upsert_chat(conn, ChatInfo(chat, title, "private_supergroup"), sync_enabled=False)
    store.import_messages(conn, chat, [
        MessageRecord(i, TS - ago_days * 86400, f"人{i}", f"{text}{i}", None, None, None, (R("emoji", "👍", i),))
        for i in range(1, n + 1)])


@pytest.fixture
def db(conn):
    boards.ensure_builtin(conn)
    return conn


def test_digest_lists_top10_with_scores_and_links(db):
    seed(db, n=12)
    [msg] = build_digest(db, Settings(), TZ, NOW)
    assert "饭群" in msg and "综合" in msg
    assert msg.count('<a href="https://t.me/c/1234567890/') == 10
    assert "打开原消息" in msg and "https://" not in msg.replace('href="https://', "")  # 链接不裸露
    assert msg.index("人12") < msg.index("人3")
    assert "人2：" not in msg  # 第 11、12 名之外不出现


def test_digest_uses_push_window(db):
    seed(db, n=2, ago_days=10)
    assert build_digest(db, Settings(), TZ, NOW) == []
    monthly = Settings(push=PushSettings(frequency="monthly"))
    assert len(build_digest(db, monthly, TZ, NOW)) == 1


def test_only_push_enabled_boards(db):
    seed(db, n=2)
    builtin = boards.list_boards(db)[0]["id"]
    boards.update_board(db, builtin, BoardIn(name="综合", push_enabled=False))
    boards.create_board(db, BoardIn(name="点赞榜", push_enabled=True, weights={"👍": 2}))
    [msg] = build_digest(db, Settings(), TZ, NOW)
    assert "点赞榜" in msg and "综合" not in msg


def test_html_escaped(db):
    seed(db, n=1, text="<b>注入</b>&")
    [msg] = build_digest(db, Settings(), TZ, NOW)
    assert "&lt;b&gt;注入&lt;/b&gt;&amp;" in msg


def test_split_never_cuts_an_entry(db):
    for k in range(8):
        seed(db, n=10, text="很长的一段话" * 30, chat=-(10 ** 12 + 1000 + k), title=f"群{k}")
    parts = build_digest(db, Settings(), TZ, NOW)
    assert len(parts) > 1
    assert all(utf16_len(p) <= LIMIT for p in parts)
    assert sum(p.count("打开原消息") for p in parts) == 80
    for p in parts:
        assert p.count("<a ") == p.count("</a>") and p.count("<b>") == p.count("</b>")


def test_utf16_len_counts_astral_emoji_twice():
    assert utf16_len("a😂") == 3


async def test_send_to_saved_messages_and_record_result(authed, world, tg_env):
    with connect(tg_env.db_path) as c:
        seed(c, n=2)
    assert await send_digest(authed, tg_env.db_path, TZ, NOW) == 1
    entity, text, mode, preview = world.sent[0]
    assert entity == "me" and mode == "html" and preview is False
    with connect(tg_env.db_path) as c:
        result = last_push(c)
    assert result["ok"] is True and result["sent"] == 1


async def test_send_to_channel(authed, world, tg_env):
    cid = world.add_chat(channel(1000000077, "我的精华频道", megagroup=False))
    with connect(tg_env.db_path) as c:
        seed(c, n=2)
        save_settings(c, Settings(push=PushSettings(target=str(cid))))
    await send_digest(authed, tg_env.db_path, TZ, NOW)
    assert world.sent[0][0].channel_id == 1000000077


async def test_push_disabled_sends_nothing(authed, world, tg_env):
    with connect(tg_env.db_path) as c:
        seed(c, n=2)
        save_settings(c, Settings(push=PushSettings(enabled=False)))
    assert await send_digest(authed, tg_env.db_path, TZ, NOW) == 0
    assert world.sent == []


async def test_push_failure_recorded_not_silent(mgr, tg_env):
    with connect(tg_env.db_path) as c:
        seed(c, n=2)
    assert await send_digest(mgr, tg_env.db_path, TZ, NOW) == 0  # 未登录 Telegram
    with connect(tg_env.db_path) as c:
        result = last_push(c)
    assert result["ok"] is False and "Telegram" in result["error"]


async def test_nothing_to_push_recorded(authed, world, tg_env):
    assert await send_digest(authed, tg_env.db_path, TZ, NOW) == 0
    with connect(tg_env.db_path) as c:
        assert "没有" in last_push(c)["error"] and last_push(c)["ok"] is True
