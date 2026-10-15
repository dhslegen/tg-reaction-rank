import io
import json
import tracemalloc
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tgrank.desktop import DesktopExport, DesktopFormatError
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord, TopicRecord

FIX = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Asia/Shanghai")


def load(name):
    exp = DesktopExport(open(FIX / name, "rb"), TZ)
    items = list(exp.records())
    return exp, [i for i in items if isinstance(i, MessageRecord)], [i for i in items if isinstance(i, TopicRecord)]


def test_basic_chat_info():
    exp, msgs, topics = load("desktop_basic.json")
    assert exp.info == ChatInfo(chat_id=-1001234567890, title="周末吃饭群", kind="private_supergroup")
    assert not exp.is_forum and topics == []


def test_basic_messages_skip_service_and_keep_all_regular():
    _, msgs, _ = load("desktop_basic.json")
    assert [m.msg_id for m in msgs] == [2, 3, 4, 5, 6]
    m3 = next(m for m in msgs if m.msg_id == 3)
    assert m3.text == "上次那家辣到哭了 😂"
    assert m3.reply_to == 2 and m3.topic_id is None
    assert m3.date == 1788228120
    assert m3.reactions == (
        ReactionRecord("emoji", "😂", 5),
        ReactionRecord("custom_emoji", "5368324170671202286", 2),
        ReactionRecord("paid", "", 1),
    )


def test_basic_media_sender_and_heart_normalized():
    _, msgs, _ = load("desktop_basic.json")
    by = {m.msg_id: m for m in msgs}
    assert by[4].media == "[图片]" and by[4].text == ""
    assert by[5].sender == "匿名" and by[5].reactions == ()
    assert ReactionRecord("emoji", "❤", 1) in by[2].reactions
    assert by[6].media == "[贴纸 🔥]"


def test_forum_topics_resolved_through_reply_chain():
    exp, msgs, topics = load("desktop_forum.json")
    assert exp.is_forum
    by = {m.msg_id: m.topic_id for m in msgs}
    # 第一条话题创建之前的消息流式读取时还不知道是话题群，留空，由导入器按 first_topic_id 回填 General
    assert by == {1: None, 11: 10, 12: 10, 21: 20, 23: 1}
    assert exp.first_topic_id == 10
    titles = {}
    for t in topics:
        titles[t.topic_id] = t.title  # 后出现的覆盖先出现的（话题改名）
    assert titles == {1: "General", 10: "科幻", 20: "中国历史"}


def test_falls_back_to_local_date_when_unixtime_missing():
    doc = {"name": "g", "type": "private_supergroup", "id": 1, "messages": [
        {"id": 1, "type": "message", "date": "2026-01-01T08:00:00", "text": "x"}]}
    exp = DesktopExport(io.BytesIO(json.dumps(doc).encode()), TZ)
    [m] = list(exp.records())
    assert m.date == 1767225600  # 2026-01-01 00:00 UTC


@pytest.mark.parametrize("payload,needle", [
    (b'{"name": "x"}', "messages"),
    (b'{"chats": {"list": []}}', "messages"),
    (b'[1,2]', "messages"),
    (b'{"name": "x", "type": "private_supergroup", "id": 1, "messages": [{"id": 1', "JSON"),
    (b'{"name": "x", "messages": []}', "id"),
    (b'not json', "JSON"),
])
def test_rejects_non_export(payload, needle):
    with pytest.raises(DesktopFormatError, match=needle):
        exp = DesktopExport(io.BytesIO(payload), TZ)
        list(exp.records())


def test_streaming_import_does_not_load_whole_file(tmp_path):
    big = tmp_path / "big.json"
    filler = "很长的消息" * 200
    with open(big, "w", encoding="utf-8") as f:
        f.write('{"name":"big","type":"private_supergroup","id":5,"messages":[')
        for i in range(1, 20001):
            if i > 1:
                f.write(",")
            json.dump({"id": i, "type": "message", "date_unixtime": str(1700000000 + i), "from": "u",
                       "text": filler, "reactions": [{"type": "emoji", "count": 1, "emoji": "👍"}]}, f, ensure_ascii=False)
        f.write("]}")
    size = big.stat().st_size
    tracemalloc.start()
    count = 0
    with open(big, "rb") as fp:
        for _ in DesktopExport(fp, TZ).records():
            count += 1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert count == 20000
    assert peak < size / 4, f"峰值 {peak} 字节，文件 {size} 字节"
