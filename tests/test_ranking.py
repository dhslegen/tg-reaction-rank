from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tgrank import boards, store
from tgrank.boards import BoardIn
from tgrank.ranking import RankQuery, emoji_stats, rank, resolve_range
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R, TopicRecord

TZ = ZoneInfo("Asia/Shanghai")
CHAT = -1001234567890
DAY = 86400
T0 = int(datetime(2026, 10, 15, 12, 0, tzinfo=TZ).timestamp())  # “现在”


def m(i, reacts, *, ago_days=0, text="", topic=None, media=None):
    return MessageRecord(i, T0 - ago_days * DAY, f"u{i}", text or f"消息{i}", media, None, topic, tuple(reacts))


@pytest.fixture
def db(conn):
    boards.ensure_builtin(conn)
    store.upsert_chat(conn, ChatInfo(CHAT, "群", "private_supergroup", is_forum=True), sync_enabled=False)
    store.upsert_topics(conn, CHAT, [TopicRecord(1, "General"), TopicRecord(10, "科幻")], overwrite=True)
    store.import_messages(conn, CHAT, [
        m(1, [R("emoji", "👍", 3), R("emoji", "❤", 1)], topic=1),
        m(2, [R("emoji", "😂", 5), R("custom_emoji", "99", 2), R("paid", "", 1)], ago_days=3, topic=10, text="100% 好笑_真的"),
        m(3, [R("emoji", "👎", 4)], ago_days=40, topic=10),
        m(4, [], topic=1),                                    # 没有反应，不上榜
        m(5, [R("emoji", "👍", 8)], ago_days=400, topic=1, media="[图片]"),
    ])
    return conn


def q(**kw):
    base = dict(chat_id=CHAT, board_id=1, range="all", date_from=None, date_to=None, topic_id=None, q="", offset=0, limit=50)
    return RankQuery(**{**base, **kw})


def ids(page):
    return [i["msg_id"] for i in page.items]


NOW = datetime.fromtimestamp(T0, TZ)


def test_overall_board_is_reaction_count(db):
    page = rank(db, q(), TZ, NOW)
    assert ids(page) == [2, 5, 1, 3]
    assert [i["score"] for i in page.items] == [8, 8, 4, 4]
    assert page.total == 4
    assert page.link_base == "https://t.me/c/1234567890/"


def test_ties_broken_by_newer_first(db):
    page = rank(db, q(), TZ, NOW)
    assert ids(page)[:2] == [2, 5]


def test_single_emoji_board_hides_zero_scores(db):
    bid = boards.create_board(db, BoardIn(name="最好笑", default_weight=0, custom_emoji_weight=0, paid_weight=0, weights={"😂": 1}))
    page = rank(db, q(board_id=bid), TZ, NOW)
    assert ids(page) == [2] and page.items[0]["score"] == 5


def test_negative_weight_controversy_board(db):
    bid = boards.create_board(db, BoardIn(name="争议", weights={"👎": 3, "👍": -1}))
    page = rank(db, q(board_id=bid), TZ, NOW)
    # 3: 4×3=12；2: 5+2+1=8；1: -3+1=-2 被隐藏；5: -8 被隐藏
    assert [(i["msg_id"], i["score"]) for i in page.items] == [(3, 12), (2, 8)]


def test_custom_and_paid_weights(db):
    bid = boards.create_board(db, BoardIn(name="打赏", default_weight=0, custom_emoji_weight=0.5, paid_weight=10))
    page = rank(db, q(board_id=bid), TZ, NOW)
    assert [(i["msg_id"], i["score"]) for i in page.items] == [(2, 11)]


def test_heart_weight_matches_with_or_without_vs16(db):
    bid = boards.create_board(db, BoardIn(name="爱心", default_weight=0, custom_emoji_weight=0, paid_weight=0, weights={"❤️": 1}))
    assert ids(rank(db, q(board_id=bid), TZ, NOW)) == [1]


def test_time_ranges(db):
    assert ids(rank(db, q(range="7d"), TZ, NOW)) == [2, 1]
    assert ids(rank(db, q(range="30d"), TZ, NOW)) == [2, 1]
    assert ids(rank(db, q(range="year"), TZ, NOW)) == [2, 1, 3]


def test_resolve_range_uses_deployment_timezone():
    now = datetime(2026, 10, 15, 0, 30, tzinfo=TZ)  # 上海已是 15 日，UTC 还是 14 日
    lo, hi = resolve_range("7d", None, None, TZ, now)
    assert lo == int(datetime(2026, 10, 9, tzinfo=TZ).timestamp())
    lo, hi = resolve_range("custom", date(2026, 10, 1), date(2026, 10, 1), TZ, now)
    assert (lo, hi) == (int(datetime(2026, 10, 1, tzinfo=TZ).timestamp()), int(datetime(2026, 10, 2, tzinfo=TZ).timestamp()))
    lo, hi = resolve_range("custom", None, date(2026, 10, 1), TZ, now)
    assert lo == 0


def test_resolve_range_rejects_unknown():
    with pytest.raises(ValueError):
        resolve_range("forever", None, None, TZ, NOW)


def test_topic_filter(db):
    assert ids(rank(db, q(topic_id=10), TZ, NOW)) == [2, 3]


def test_keyword_search_escapes_like_wildcards(db):
    assert ids(rank(db, q(q="100%"), TZ, NOW)) == [2]
    assert ids(rank(db, q(q="_真"), TZ, NOW)) == [2]
    assert ids(rank(db, q(q="%"), TZ, NOW)) == [2]
    assert ids(rank(db, q(q="图片"), TZ, NOW)) == [5]


def test_paging(db):
    page = rank(db, q(offset=1, limit=2), TZ, NOW)
    assert ids(page) == [5, 1] and page.total == 4


def test_item_shape(db):
    item = rank(db, q(), TZ, NOW).items[0]
    assert item["topic"] == "科幻"
    assert item["reactions"] == [{"label": "😂", "count": 5}, {"label": "自定义表情", "count": 2}, {"label": "⭐", "count": 1}]
    assert item["sender"] == "u2"


def test_long_text_truncated(conn):
    boards.ensure_builtin(conn)
    store.upsert_chat(conn, ChatInfo(CHAT, "群", "private_supergroup"), sync_enabled=False)
    store.import_messages(conn, CHAT, [m(1, [R("emoji", "👍", 1)], text="长" * 300)])
    text = rank(conn, q(), TZ, NOW).items[0]["text"]
    assert len(text) == 201 and text.endswith("…")


def test_emoji_stats(db):
    stats = emoji_stats(db, CHAT)
    assert stats[0] == {"kind": "emoji", "key": "👍", "label": "👍", "count": 11}
    assert {"kind": "paid", "key": "", "label": "⭐", "count": 1} in stats
