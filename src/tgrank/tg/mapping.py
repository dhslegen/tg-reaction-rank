"""Telethon 对象 → 统一中间记录。逻辑移植自已验证的原型 fetch.py。"""
from __future__ import annotations

from telethon import utils
from telethon.tl import types

from ..records import ChatInfo, MessageRecord, ReactionRecord, TopicRecord, media_label, normalize_emoji

GENERAL_TOPIC_ID = 1


def chat_kind(entity) -> str:
    """对齐 Desktop 导出的 type 字段。"""
    if isinstance(entity, types.Channel):
        scope = "public" if entity.username else "private"
        return f"{scope}_supergroup" if entity.megagroup else f"{scope}_channel"
    return "private_group"


def chat_info(entity) -> ChatInfo:
    is_channel = isinstance(entity, types.Channel)
    return ChatInfo(
        chat_id=utils.get_peer_id(entity),
        title=utils.get_display_name(entity),
        kind=chat_kind(entity),
        username=getattr(entity, "username", None),
        is_forum=bool(getattr(entity, "forum", False)),
        access_hash=entity.access_hash if is_channel else None,
    )


def input_peer(chat_id: int, access_hash: int | None):
    """超级群/频道需要 access_hash；普通群（Chat）没有 access_hash，只用 id。"""
    real_id, peer_type = utils.resolve_id(chat_id)
    if peer_type is types.PeerChannel:
        return types.InputPeerChannel(real_id, access_hash or 0)
    return types.InputPeerChat(real_id)


def _reaction(rc) -> ReactionRecord | None:
    if not rc.count or rc.count <= 0:
        return None
    r = rc.reaction
    if isinstance(r, types.ReactionEmoji):
        return ReactionRecord("emoji", normalize_emoji(r.emoticon), rc.count)
    if isinstance(r, types.ReactionCustomEmoji):
        return ReactionRecord("custom_emoji", str(r.document_id), rc.count)
    if isinstance(r, types.ReactionPaid):
        return ReactionRecord("paid", "", rc.count)
    return ReactionRecord("unknown", "", rc.count)


def _media_fields(m) -> dict:
    """转成 Desktop 导出同名字段，再交给 records.media_label 统一生成占位文字。"""
    if isinstance(m.media, types.MessageMediaPhoto):
        return {"photo": True}
    if m.sticker:
        return {"media_type": "sticker", "sticker_emoji": (m.file and m.file.emoji) or ""}
    if m.gif:
        return {"media_type": "animation"}
    if m.video_note:
        return {"media_type": "video_message"}
    if m.voice:
        return {"media_type": "voice_message"}
    if m.audio:
        return {"media_type": "audio_file"}
    if m.video:
        return {"media_type": "video_file"}
    if isinstance(m.media, types.MessageMediaPoll):
        q = m.media.poll.question
        return {"poll": {"question": getattr(q, "text", q) or ""}}
    if isinstance(m.media, (types.MessageMediaGeo, types.MessageMediaGeoLive, types.MessageMediaVenue)):
        return {"location_information": {}}
    if isinstance(m.media, types.MessageMediaContact):
        return {"contact_information": {}}
    if m.document:
        return {"file": True}
    return {}


def _topic_of(reply_to) -> int:
    """话题群：带 forum_topic 标记的回复头指向话题根；没有标记的属于 General。"""
    if reply_to is not None and getattr(reply_to, "forum_topic", False):
        return reply_to.reply_to_top_id or reply_to.reply_to_msg_id or GENERAL_TOPIC_ID
    return GENERAL_TOPIC_ID


def to_record(m, *, chat_title: str, is_forum: bool) -> MessageRecord | TopicRecord | None:
    if isinstance(m, types.MessageService):
        if isinstance(m.action, types.MessageActionTopicCreate):
            return TopicRecord(m.id, m.action.title)
        if isinstance(m.action, types.MessageActionTopicEdit) and m.action.title:
            return TopicRecord(_topic_of(m.reply_to), m.action.title)
        return None
    if not isinstance(m, types.Message):
        return None

    reply = m.reply_to if isinstance(m.reply_to, types.MessageReplyHeader) else None
    reactions = ()
    if m.reactions and m.reactions.results:
        reactions = tuple(r for r in map(_reaction, m.reactions.results) if r is not None)
    return MessageRecord(
        msg_id=m.id,
        date=int(m.date.timestamp()),
        # 匿名管理员和以频道身份发言时 sender 是频道本身或为空
        sender=utils.get_display_name(m.sender) if m.sender else (m.post_author or chat_title),
        text=m.message or "",
        media=media_label(_media_fields(m)),
        reply_to=reply.reply_to_msg_id if reply else None,
        topic_id=_topic_of(reply) if is_forum else None,
        reactions=reactions,
    )
