"""两种数据来源（Desktop 导出 JSON、Telethon API）共用的中间模型与规范化规则。

解析层只产出这里的不可变记录，入库层只认这里的记录，两边不直接耦合。
"""
from __future__ import annotations

from dataclasses import dataclass

VS16 = "\ufe0f"  # 表情变体选择符：用户输入的 ❤️ 带它，Telegram 反应里的 ❤ 不带


@dataclass(frozen=True)
class ReactionRecord:
    kind: str   # emoji | custom_emoji | paid | unknown
    key: str    # emoji：规范化后的表情；custom_emoji：document_id；其余为空串
    count: int


@dataclass(frozen=True)
class MessageRecord:
    msg_id: int
    date: int                       # UTC unix 秒
    sender: str
    text: str
    media: str | None
    reply_to: int | None
    topic_id: int | None
    reactions: tuple[ReactionRecord, ...] = ()


@dataclass(frozen=True)
class TopicRecord:
    topic_id: int
    title: str


@dataclass(frozen=True)
class ChatInfo:
    chat_id: int                    # marked id
    title: str
    kind: str                       # 与 Desktop 导出的 type 字段一致
    username: str | None = None
    is_forum: bool = False
    access_hash: int | None = None  # 只有 API 来源才有


def normalize_emoji(s: str) -> str:
    return s.replace(VS16, "").strip()


def flatten_text(raw) -> str:
    """Desktop 导出的 text 可能是字符串，也可能是「字符串 / {type, text}」混合数组。"""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(p if isinstance(p, str) else str(p.get("text") or "") for p in raw)
    return ""


_MEDIA = {
    "sticker": "贴纸", "animation": "GIF", "video_file": "视频", "video_message": "视频消息",
    "voice_message": "语音", "audio_file": "音频",
}


def media_label(m: dict) -> str | None:
    """按 Desktop 导出的媒体字段生成占位文字；Telethon 映射也先转成同样的字段再调用这里。"""
    if m.get("photo"):
        return "[图片]"
    if m.get("media_type"):
        emoji = m.get("sticker_emoji")
        return f"[{_MEDIA.get(m['media_type'], '媒体')}{' ' + emoji if emoji else ''}]"
    if m.get("file"):
        return "[文件]"
    if m.get("poll") is not None:
        return f"[投票] {(m['poll'] or {}).get('question') or ''}".rstrip()
    if m.get("location_information") is not None:
        return "[位置]"
    if m.get("contact_information") is not None:
        return "[联系人]"
    return None


CHANNEL_OFFSET = 10 ** 12   # Telethon 的 marked id：频道/超级群为 -(10^12 + id)


def _is_channel_like(kind: str) -> bool:
    return "supergroup" in kind or "channel" in kind


def marked_chat_id(raw_id: int | str, kind: str) -> int:
    """Desktop 导出里超级群 id 通常不带 -100 前缀（个别版本带），统一成 Telethon 的 marked id。"""
    n = int(raw_id)
    if _is_channel_like(kind):
        return n if n < 0 else -(CHANNEL_OFFSET + n)
    if kind == "private_group":
        return -abs(n)
    return n


def link_base(chat_id: int, kind: str) -> str | None:
    """t.me/c/<去掉 -100 的 id>/<msg_id> 对成员可用；普通群和私聊拼不出跳转链接。"""
    if not _is_channel_like(kind):
        return None
    return f"https://t.me/c/{-chat_id - CHANNEL_OFFSET}/"


def desktop_reaction(r: dict) -> ReactionRecord | None:
    try:
        count = int(r.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    kind = r.get("type")
    if kind == "emoji":
        return ReactionRecord("emoji", normalize_emoji(str(r.get("emoji") or "")), count)
    if kind == "custom_emoji":
        return ReactionRecord("custom_emoji", str(r.get("document_id") or ""), count)
    if kind == "paid":
        return ReactionRecord("paid", "", count)
    return ReactionRecord("unknown", "", count)


# U+1F000 以上默认就是彩色表情呈现，只有少数例外（🕊 是 Telegram 的可选反应之一）
_TEXT_DEFAULT_HIGH = {0x1F441, 0x1F54A, 0x1F321, 0x1F576, 0x1F5E8}
_NO_VS = {0x200D, 0xFE0F} | set(range(0x1F3FB, 0x1F400))  # ZWJ、变体符、肤色修饰符本身不补


def display_emoji(key: str) -> str:
    """归一化去掉的 FE0F 只用于分组匹配；展示时给默认文本呈现的字符补回，避免 ❤ 显示成黑色心形。"""
    out = []
    for i, ch in enumerate(key):
        out.append(ch)
        cp = ord(ch)
        nxt = key[i + 1] if i + 1 < len(key) else ""
        if cp in _NO_VS or nxt == VS16 or (nxt and 0x1F3FB <= ord(nxt) <= 0x1F3FF):
            continue
        if cp < 0x1F000 or cp in _TEXT_DEFAULT_HIGH:
            out.append(VS16)
    return "".join(out)


def reaction_label(kind: str, key: str) -> str:
    if kind == "paid":
        return "⭐"
    if kind == "emoji" and key:
        return display_emoji(key)
    if kind == "custom_emoji":
        return "自定义表情"
    return "?"
