"""Telegram 客户端的唯一出口：生命周期、网页登录向导、互斥锁、FloodWait 与会话失效处理。

同一 session 绝不能在两个进程里同时连接（会 AUTH_KEY_DUPLICATED 被作废），所以整个进程只有
一个主客户端；所有请求经 call() 串行发出，每次只占一次请求的时间。
"""
from __future__ import annotations

import asyncio
import enum
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from telethon import errors, utils

from ..config import Env
from ..crypto import BadSecret, SecretBox
from ..db import connect, transaction
from ..records import ChatInfo
from .mapping import chat_info

log = logging.getLogger(__name__)

SESSION_KEY = "tg_session"
MAX_FLOOD_WAIT = 3600          # 超过 1 小时的限流本轮放弃，交给下次调度
PENDING_TTL = 600              # 登录向导：发验证码后 10 分钟内有效
NETWORK_RETRIES = 5
AUTH_ERRORS = (errors.UnauthorizedError, errors.AuthKeyDuplicatedError, errors.AuthKeyInvalidError)
RELOGIN_HINT = "Telegram 登录已失效（可能在其它设备上被登出，或同一 session 被多处同时使用），请重新登录"


class TgState(str, enum.Enum):
    UNCONFIGURED = "unconfigured"           # .env 没填 TG_API_ID / TG_API_HASH
    LOGGED_OUT = "logged_out"
    AUTHORIZED = "authorized"
    RELOGIN_REQUIRED = "relogin_required"
    OFFLINE = "offline"                     # 有 session，但暂时连不上


class TgUnavailable(RuntimeError):
    """当前无法向 Telegram 发请求；调度任务遇到它直接跳过即可。"""


class TgLoginError(ValueError):
    """登录向导中给用户看的错误。"""


@dataclass
class _Pending:
    client: Any
    phone: str
    code_hash: str
    created: float
    awaiting_password: bool = False


def real_client_factory(env: Env) -> Callable[[str], Any]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    def make(session: str):
        # 必须在事件循环内调用：Telethon 客户端会绑定到创建时的循环
        return TelegramClient(
            StringSession(session), env.api_id, env.api_hash, proxy=env.proxy,
            flood_sleep_threshold=60, receive_updates=False,
            device_model="tg-reaction-rank", app_version="0.1",
        )
    return make


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    p = phone if phone.startswith("+") else f"+{phone}"
    return p[:3] + "****" + p[-4:] if len(p) > 7 else p


def _login_message(e: Exception) -> str:
    match e:
        case errors.PhoneNumberInvalidError():
            return "手机号格式不对，请带国家区号，例如 +8613800000000"
        case errors.PhoneNumberBannedError():
            return "这个手机号已被 Telegram 封禁"
        case errors.PhoneCodeInvalidError():
            return "验证码不正确"
        case errors.PhoneCodeExpiredError():
            return "验证码已过期，请重新获取"
        case errors.PasswordHashInvalidError():
            return "两步验证密码不正确"
        case errors.FloodWaitError():
            return f"操作太频繁，Telegram 要求等待 {e.seconds} 秒后再试"
        case errors.ApiIdInvalidError():
            return "TG_API_ID / TG_API_HASH 无效，请检查 .env"
        case ConnectionError() | OSError() | asyncio.TimeoutError():
            return "无法连接 Telegram，请检查网络或 TG_PROXY 设置"
        case errors.RPCError():
            return f"Telegram 返回错误：{e}"
    return f"登录失败：{e}"


class TgManager:
    def __init__(self, env: Env, *, client_factory: Callable[[str], Any] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.env = env
        self._factory = client_factory or real_client_factory(env)
        self._sleep = sleep
        self._box = SecretBox(env.app_secret)
        self._lock = asyncio.Lock()
        self._client = None
        self._session: str | None = None
        self._pending: _Pending | None = None
        self.state = TgState.UNCONFIGURED if not env.telegram_configured else TgState.LOGGED_OUT
        self.me: dict | None = None
        self.last_error: str | None = None
        self.flood_until: float | None = None

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        if not self.env.telegram_configured:
            self.state = TgState.UNCONFIGURED
            return
        with connect(self.env.db_path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (SESSION_KEY,)).fetchone()
        if row is None:
            self.state = TgState.LOGGED_OUT
            return
        try:
            self._session = self._box.decrypt(row[0])
        except BadSecret as e:
            self._fail_relogin(str(e))
            return
        await self._connect_main()

    async def _connect_main(self) -> None:
        if self._client is None:
            self._client = self._factory(self._session)
        try:
            await self._client.connect()
            authorized = await self._client.is_user_authorized()
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            self.state, self.last_error = TgState.OFFLINE, f"无法连接 Telegram：{e}"
            return
        except AUTH_ERRORS:
            authorized = False
        if not authorized:
            self._fail_relogin(RELOGIN_HINT)
            await self._client.disconnect()
            return
        self.me = self._me_view(await self._client.get_me())
        self.state, self.last_error = TgState.AUTHORIZED, None

    async def stop(self) -> None:
        for c in (self._client, self._pending and self._pending.client):
            if c is not None:
                await c.disconnect()

    def _fail_relogin(self, message: str) -> None:
        self.state, self.last_error = TgState.RELOGIN_REQUIRED, message
        log.warning("Telegram 需要重新登录：%s", message)

    @staticmethod
    def _me_view(user) -> dict:
        return {"name": utils.get_display_name(user), "username": getattr(user, "username", None),
                "phone": _mask_phone(getattr(user, "phone", None))}

    def status(self) -> dict:
        return {
            "state": self.state.value, "me": self.me, "last_error": self.last_error,
            "flood_until": self.flood_until, "proxy": bool(self.env.proxy),
            "login_step": ("password" if self._pending.awaiting_password else "code") if self._pending_alive() else None,
        }

    # ---------- 统一请求出口 ----------
    async def call(self, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        if self.state is TgState.OFFLINE:
            await self._connect_main()
        if self.state is not TgState.AUTHORIZED:
            raise TgUnavailable(self.state.value)

        async with self._lock:
            network_failures = 0
            while True:
                try:
                    return await fn(self._client)
                except errors.FloodWaitError as e:
                    if e.seconds > MAX_FLOOD_WAIT:
                        raise
                    wait = e.seconds + random.uniform(1, 5)
                    self.flood_until = time.time() + wait
                    log.info("Telegram 限流，等待 %.0f 秒", wait)
                    await self._sleep(wait)
                    self.flood_until = None
                except AUTH_ERRORS:
                    self._fail_relogin(RELOGIN_HINT)
                    await self._client.disconnect()
                    raise TgUnavailable(self.state.value) from None
                except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                    if network_failures >= NETWORK_RETRIES:
                        self.state, self.last_error = TgState.OFFLINE, f"网络错误：{e}"
                        raise TgUnavailable(self.state.value) from e
                    await self._sleep(min(5 * 2 ** network_failures, 300))
                    network_failures += 1

    # ---------- 登录向导 ----------
    def _pending_alive(self) -> bool:
        return self._pending is not None and time.time() - self._pending.created < PENDING_TTL

    async def login_phone(self, phone: str) -> None:
        if self.state is TgState.UNCONFIGURED:
            raise TgLoginError("还没有配置 TG_API_ID / TG_API_HASH，请在 .env 中填写后重启")
        if self.state is TgState.AUTHORIZED:
            raise TgLoginError("已登录 Telegram；如需换号请先退出登录")
        if self._pending is not None:
            await self._pending.client.disconnect()
            self._pending = None
        client = self._factory("")
        try:
            await client.connect()
            sent = await client.send_code_request(phone.strip())
        except Exception as e:
            await client.disconnect()
            raise TgLoginError(_login_message(e)) from e
        self._pending = _Pending(client, phone.strip(), sent.phone_code_hash, time.time())

    def _require_pending(self) -> _Pending:
        if not self._pending_alive():
            raise TgLoginError("请先填写手机号获取验证码（或验证码已超过 10 分钟，请重新获取）")
        return self._pending

    async def login_code(self, code: str) -> str:
        p = self._require_pending()
        try:
            await p.client.sign_in(p.phone, code.strip(), phone_code_hash=p.code_hash)
        except errors.SessionPasswordNeededError:
            p.awaiting_password = True
            return "password"
        except Exception as e:
            raise TgLoginError(_login_message(e)) from e
        await self._adopt(p.client)
        return "done"

    async def login_password(self, password: str) -> None:
        p = self._require_pending()
        if not p.awaiting_password:
            raise TgLoginError("当前不需要两步验证密码")
        try:
            await p.client.sign_in(password=password)
        except Exception as e:
            raise TgLoginError(_login_message(e)) from e
        await self._adopt(p.client)

    async def _adopt(self, client) -> None:
        """登录成功：保存加密 session，替换主客户端，并用新账号刷新已有群的 access_hash。"""
        self._pending = None
        session = client.session.save()
        with connect(self.env.db_path) as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SESSION_KEY, self._box.encrypt(session)),
            )
        if self._client is not None and self._client is not client:
            await self._client.disconnect()
        self._client, self._session = client, session
        self.me = self._me_view(await client.get_me())
        self.state, self.last_error = TgState.AUTHORIZED, None
        await self._refresh_chat_access()

    async def _refresh_chat_access(self) -> None:
        """access_hash 按账号绑定，换号后旧值全部失效；找不到的群暂停同步而不是让任务反复报错。"""
        reachable = {d.chat_id: d for d in await self.list_dialogs()}
        with connect(self.env.db_path) as conn, transaction(conn):
            for row in conn.execute("SELECT chat_id FROM chats WHERE sync_enabled = 1").fetchall():
                d = reachable.get(row["chat_id"])
                if d is None:
                    conn.execute(
                        "UPDATE chats SET sync_enabled = 0, last_error = ? WHERE chat_id = ?",
                        ("当前 Telegram 账号无法访问这个群，已暂停同步", row["chat_id"]))
                else:
                    conn.execute("UPDATE chats SET access_hash = ?, last_error = NULL WHERE chat_id = ?",
                                 (d.access_hash, d.chat_id))

    async def logout(self) -> None:
        if self._client is not None:
            try:
                async with self._lock:
                    await self._client.log_out()
            except Exception:  # 已失效的 session 登出会报错，本地照样清理
                log.info("Telegram 登出请求失败，继续清理本地 session", exc_info=True)
            await self._client.disconnect()
        with connect(self.env.db_path) as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (SESSION_KEY,))
        self._client = self._session = self.me = None
        self.state, self.last_error = TgState.LOGGED_OUT, None

    # ---------- 数据 ----------
    async def list_dialogs(self) -> list[ChatInfo]:
        """账号加入的群和频道（私聊不列出）。"""
        async def fetch(client):
            return [chat_info(d.entity) async for d in client.iter_dialogs() if d.is_group or d.is_channel]
        return await self.call(fetch)
