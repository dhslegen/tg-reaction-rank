"""假的 Telegram：FakeWorld 是“服务端”，FakeTelegramClient 只实现本项目用到的客户端方法。

消息、实体、反应都用真实的 Telethon TL 类型构造，保证映射代码面对的是真实结构。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

from telethon import utils
from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError, PasswordHashInvalidError
from telethon.tl import types

UTC = timezone.utc


def channel(cid: int, title: str, *, forum=False, megagroup=True, username=None, access_hash=777):
    return types.Channel(id=cid, title=title, photo=types.ChatPhotoEmpty(), date=datetime(2024, 1, 1, tzinfo=UTC),
                         megagroup=megagroup, broadcast=not megagroup, forum=forum, username=username,
                         access_hash=access_hash)


def user(uid: int, first: str, last: str | None = None):
    return types.User(id=uid, first_name=first, last_name=last)


def emoji(e: str, n: int):
    return types.ReactionCount(reaction=types.ReactionEmoji(e), count=n)


def custom(doc_id: int, n: int):
    return types.ReactionCount(reaction=types.ReactionCustomEmoji(doc_id), count=n)


def paid(n: int):
    return types.ReactionCount(reaction=types.ReactionPaid(), count=n)


def message(mid: int, text: str = "", *, ts: int = 1_788_000_000, sender=None, reactions=(), reply_to=None,
            forum_topic=False, top_id=None, media=None, post_author=None, cid: int = 1):
    reply = None
    if reply_to is not None or forum_topic:
        reply = types.MessageReplyHeader(reply_to_msg_id=reply_to, forum_topic=forum_topic or None, reply_to_top_id=top_id)
    m = types.Message(
        id=mid, peer_id=types.PeerChannel(cid), date=datetime.fromtimestamp(ts, UTC), message=text,
        from_id=types.PeerUser(sender.id) if sender else None, reply_to=reply, media=media, post_author=post_author,
        reactions=types.MessageReactions(results=list(reactions)) if reactions else None,
    )
    m._sender = sender
    return m


def topic_created(mid: int, title: str, *, ts: int = 1_788_000_000, cid: int = 1):
    return types.MessageService(id=mid, peer_id=types.PeerChannel(cid), date=datetime.fromtimestamp(ts, UTC),
                                action=types.MessageActionTopicCreate(title=title, icon_color=0))


def topic_edited(mid: int, topic_id: int, title: str, *, ts: int = 1_788_000_000, cid: int = 1):
    return types.MessageService(id=mid, peer_id=types.PeerChannel(cid), date=datetime.fromtimestamp(ts, UTC),
                                reply_to=types.MessageReplyHeader(reply_to_msg_id=topic_id, forum_topic=True),
                                action=types.MessageActionTopicEdit(title=title))


@dataclass
class Dialog:
    entity: object

    @property
    def id(self):
        return utils.get_peer_id(self.entity)

    @property
    def name(self):
        return utils.get_display_name(self.entity)

    @property
    def is_group(self):
        return isinstance(self.entity, types.Chat) or getattr(self.entity, "megagroup", False)

    @property
    def is_channel(self):
        return isinstance(self.entity, types.Channel)


@dataclass
class FakeWorld:
    """服务端状态：消息、账号、有效 session；errors 按方法名排队注入异常。"""
    me: types.User = field(default_factory=lambda: user(42, "站长"))
    phone: str = "+8613800000000"
    code: str = "12345"
    password: str | None = None
    entities: dict[int, object] = field(default_factory=dict)
    history: dict[int, dict[int, object]] = field(default_factory=dict)
    valid_sessions: set[str] = field(default_factory=set)
    errors: dict[str, list[Exception]] = field(default_factory=dict)
    sent: list[tuple] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    clients: list = field(default_factory=list)
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    def add_chat(self, entity, msgs=()):
        cid = utils.get_peer_id(entity)
        self.entities[cid] = entity
        self.history[cid] = {m.id: m for m in msgs}
        return cid

    def fail(self, method: str, *excs: Exception):
        self.errors.setdefault(method, []).extend(excs)

    def factory(self, session: str) -> FakeTelegramClient:
        c = FakeTelegramClient(self, session)
        self.clients.append(c)
        return c


class _Session:
    def __init__(self, client):
        self._c = client

    def save(self) -> str:
        return self._c.session_str


class FakeTelegramClient:
    def __init__(self, world: FakeWorld, session: str):
        self.world, self.session_str = world, session
        self.session = _Session(self)
        self.connected = False
        self._code_hash = None
        self._awaiting_password = False

    def _hit(self, method: str):
        self.world.calls.append(method)
        queue = self.world.errors.get(method)
        if queue:
            raise queue.pop(0)

    # ---- 连接与登录 ----
    async def connect(self):
        self._hit("connect")
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    async def is_user_authorized(self):
        self._hit("is_user_authorized")
        return self.session_str in self.world.valid_sessions

    async def get_me(self):
        self._hit("get_me")
        return self.world.me

    async def send_code_request(self, phone):
        self._hit("send_code_request")
        self._code_hash = "hash-" + phone
        return types.auth.SentCode(type=types.auth.SentCodeTypeApp(5), phone_code_hash=self._code_hash)

    async def sign_in(self, phone=None, code=None, *, password=None, phone_code_hash=None):
        self._hit("sign_in")
        if password is not None:
            if not self._awaiting_password:
                raise RuntimeError("没有在等两步验证密码")
            if password != self.world.password:
                raise PasswordHashInvalidError(request=None)
        else:
            if phone_code_hash != self._code_hash or str(code) != self.world.code:
                raise PhoneCodeInvalidError(request=None)
            if self.world.password is not None:
                self._awaiting_password = True
                raise SessionPasswordNeededError(request=None)
        self.session_str = f"session-{next(self.world._seq)}"
        self.world.valid_sessions.add(self.session_str)
        return self.world.me

    async def log_out(self):
        self._hit("log_out")
        self.world.valid_sessions.discard(self.session_str)
        self.connected = False
        return True

    # ---- 数据 ----
    async def iter_dialogs(self):
        self._hit("iter_dialogs")
        for e in self.world.entities.values():
            yield Dialog(e)

    def _cid(self, peer) -> int:
        return utils.get_peer_id(peer)

    async def get_messages(self, peer, limit=None, *, ids=None, min_id=0, reverse=False):
        self._hit("get_messages")
        hist = self.world.history.get(self._cid(peer))
        if hist is None:
            from telethon.errors import ChannelPrivateError
            raise ChannelPrivateError(request=None)
        if ids is not None:
            return [hist.get(i) for i in ids]
        assert reverse, "项目只用升序分页"
        found = sorted(i for i in hist if i > min_id)[: limit or 100]
        return [hist[i] for i in found]

    async def send_message(self, entity, text, *, parse_mode=None, link_preview=True):
        self._hit("send_message")
        self.world.sent.append((entity, text, parse_mode, link_preview))
