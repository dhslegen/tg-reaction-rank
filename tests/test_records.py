import pytest

from tgrank.records import (
    ReactionRecord, desktop_reaction, flatten_text, link_base, marked_chat_id,
    media_label, normalize_emoji, reaction_label,
)


def test_normalize_emoji_strips_variation_selector():
    assert normalize_emoji("❤️") == "❤"
    assert normalize_emoji(" 👍 ") == "👍"


def test_flatten_text_handles_string_and_mixed_array():
    assert flatten_text("hi") == "hi"
    assert flatten_text(["a ", {"type": "bold", "text": "b"}, {"type": "link"}, "c"]) == "a bc"
    assert flatten_text(None) == ""


@pytest.mark.parametrize("msg,label", [
    ({"photo": "x"}, "[图片]"),
    ({"media_type": "sticker", "sticker_emoji": "😂"}, "[贴纸 😂]"),
    ({"media_type": "video_file"}, "[视频]"),
    ({"media_type": "weird"}, "[媒体]"),
    ({"file": "x"}, "[文件]"),
    ({"poll": {"question": "吃啥"}}, "[投票] 吃啥"),
    ({"location_information": {}}, "[位置]"),
    ({"contact_information": {}}, "[联系人]"),
    ({}, None),
])
def test_media_label(msg, label):
    assert media_label(msg) == label


@pytest.mark.parametrize("raw,kind,expected", [
    (1234567890, "private_supergroup", -1001234567890),
    ("-1001234567890", "public_supergroup", -1001234567890),
    (1234567890, "private_channel", -1001234567890),
    (4242, "private_group", -4242),
    (-4242, "private_group", -4242),
    (777, "personal_chat", 777),
    (100, "private_supergroup", -1000000000100),  # 与 Telethon utils.get_peer_id 一致，而非字符串拼接
])
def test_marked_chat_id(raw, kind, expected):
    assert marked_chat_id(raw, kind) == expected


def test_link_base_only_for_supergroups_and_channels():
    assert link_base(-1001234567890, "private_supergroup") == "https://t.me/c/1234567890/"
    assert link_base(-4242, "private_group") is None
    assert link_base(-1000000000100, "private_channel") == "https://t.me/c/100/"


@pytest.mark.parametrize("raw,record", [
    ({"type": "emoji", "count": 3, "emoji": "❤️"}, ReactionRecord("emoji", "❤", 3)),
    ({"type": "custom_emoji", "count": 2, "document_id": "99"}, ReactionRecord("custom_emoji", "99", 2)),
    ({"type": "paid", "count": 5}, ReactionRecord("paid", "", 5)),
    ({"type": "who-knows", "count": 1}, ReactionRecord("unknown", "", 1)),
    ({"type": "emoji", "count": 0, "emoji": "👍"}, None),
    ({"type": "emoji", "count": "x", "emoji": "👍"}, None),
])
def test_desktop_reaction(raw, record):
    assert desktop_reaction(raw) == record


def test_reaction_label():
    assert reaction_label("paid", "") == "⭐"
    assert reaction_label("emoji", "😂") == "😂"
    assert reaction_label("emoji", "❤") == "❤\ufe0f"
    assert reaction_label("custom_emoji", "99") == "自定义表情"


@pytest.mark.parametrize("key,shown", [
    ("❤", "❤\ufe0f"),                       # 默认文本呈现的单字符补回 FE0F
    ("🕊", "🕊\ufe0f"),
    ("❤\u200d🔥", "❤\ufe0f\u200d🔥"),        # ZWJ 序列只给 U+1F000 以下的基字符补
    ("👨\u200d💻", "👨\u200d💻"),
    ("👍🏻", "👍🏻"),
])
def test_display_emoji(key, shown):
    from tgrank.records import display_emoji
    assert display_emoji(key) == shown
