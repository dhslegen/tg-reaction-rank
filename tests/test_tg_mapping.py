from telethon.tl import types

from fakes import channel, custom, emoji, message, paid, topic_created, topic_edited, user
from tgrank.records import ChatInfo, MessageRecord, ReactionRecord as R, TopicRecord
from tgrank.tg.mapping import chat_info, input_peer, to_record

AMING = user(7, "阿", "明")


def test_regular_message():
    m = message(5, "你好", ts=1_788_000_000, sender=AMING, reply_to=3,
                reactions=[emoji("❤️", 2), custom(99, 1), paid(3)])
    assert to_record(m, chat_title="群", is_forum=False) == MessageRecord(
        5, 1_788_000_000, "阿 明", "你好", None, 3, None,
        (R("emoji", "❤", 2), R("custom_emoji", "99", 1), R("paid", "", 3)))


def test_anonymous_admin_falls_back_to_signature_then_title():
    assert to_record(message(1, "x", post_author="管理员"), chat_title="群", is_forum=False).sender == "管理员"
    assert to_record(message(1, "x"), chat_title="群", is_forum=False).sender == "群"


def test_forum_topic_resolution():
    in_topic = message(11, "a", reply_to=10, forum_topic=True)
    reply_in_topic = message(12, "b", reply_to=11, forum_topic=True, top_id=10)
    general = message(13, "c")
    general_reply = message(14, "d", reply_to=13)
    rec = lambda m: to_record(m, chat_title="g", is_forum=True)  # noqa: E731
    assert [rec(m).topic_id for m in (in_topic, reply_in_topic, general, general_reply)] == [10, 10, 1, 1]
    assert rec(reply_in_topic).reply_to == 11


def test_service_messages():
    assert to_record(topic_created(10, "科幻"), chat_title="g", is_forum=True) == TopicRecord(10, "科幻")
    assert to_record(topic_edited(30, 10, "硬科幻"), chat_title="g", is_forum=True) == TopicRecord(10, "硬科幻")
    other = types.MessageService(id=2, peer_id=types.PeerChannel(1), date=message(1).date,
                                 action=types.MessageActionChatJoinedByLink(inviter_id=1))
    assert to_record(other, chat_title="g", is_forum=False) is None


def test_media_placeholders():
    photo = message(1, media=types.MessageMediaPhoto(photo=types.PhotoEmpty(1)))
    sticker_doc = types.Document(id=1, access_hash=1, file_reference=b"", date=None, mime_type="image/webp", size=1, dc_id=1,
                                 attributes=[types.DocumentAttributeSticker(alt="😂", stickerset=types.InputStickerSetEmpty())])
    sticker = message(2, media=types.MessageMediaDocument(document=sticker_doc))
    poll = message(3, media=types.MessageMediaPoll(
        poll=types.Poll(id=1, question=types.TextWithEntities("吃啥", []), answers=[], hash=0), results=types.PollResults()))
    rec = lambda m: to_record(m, chat_title="g", is_forum=False).media  # noqa: E731
    assert (rec(photo), rec(sticker), rec(poll)) == ("[图片]", "[贴纸 😂]", "[投票] 吃啥")


def test_chat_info_and_input_peer():
    ch = channel(1234567890, "读书会", forum=True, username="books", access_hash=555)
    info = chat_info(ch)
    assert info == ChatInfo(-1001234567890, "读书会", "public_supergroup", "books", True, 555)
    peer = input_peer(info.chat_id, info.access_hash)
    assert isinstance(peer, types.InputPeerChannel) and (peer.channel_id, peer.access_hash) == (1234567890, 555)
    basic = types.Chat(id=4242, title="小群", photo=types.ChatPhotoEmpty(), participants_count=3, date=None, version=1)
    assert chat_info(basic) == ChatInfo(-4242, "小群", "private_group", None, False, None)
    assert input_peer(-4242, None) == types.InputPeerChat(4242)
    assert chat_info(channel(9, "频道", megagroup=False)).kind == "private_channel"
