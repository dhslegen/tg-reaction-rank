"""管理员登录：密码比对、服务端会话、双层登录限流。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections import deque

SESSION_TTL = 30 * 86400
COOKIE_NAME = "tgrank_session"


def password_ok(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())


class LoginLimiter:
    """同一 IP 15 分钟内失败 5 次锁 15 分钟；全局 15 分钟内失败 30 次全局锁 15 分钟。

    全局这层是为了兜住伪造 X-Forwarded-For 轮换 IP 的暴力破解。内存实现，重启清零可以接受。
    """

    def __init__(self, per_ip: int = 5, global_max: int = 30, window: int = 900, lockout: int = 900):
        self.per_ip, self.global_max, self.window, self.lockout = per_ip, global_max, window, lockout
        self._ip: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    def _trim(self, q: deque[float], now: float) -> None:
        while q and q[0] <= now - self.window:
            q.popleft()

    def _remaining(self, q: deque[float], limit: int, now: float) -> int | None:
        self._trim(q, now)
        if len(q) >= limit:
            left = int(q[-1] + self.lockout - now)
            return left if left > 0 else None
        return None

    def retry_after(self, ip: str, now: float) -> int | None:
        waits = [w for w in (
            self._remaining(self._all, self.global_max, now),
            self._remaining(self._ip.get(ip, deque()), self.per_ip, now),
        ) if w]
        return max(waits) if waits else None

    def record_failure(self, ip: str, now: float) -> None:
        self._ip.setdefault(ip, deque()).append(now)
        self._all.append(now)
        if len(self._ip) > 10_000:  # 防止伪造海量 IP 撑爆内存
            self._ip.clear()

    def record_success(self, ip: str) -> None:
        self._ip.pop(ip, None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, now: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))
    conn.execute("INSERT INTO admin_sessions(token_hash, expires_at) VALUES (?, ?)", (_hash(token), now + SESSION_TTL))
    return token


def session_valid(conn: sqlite3.Connection, token: str | None, now: int) -> bool:
    if not token:
        return False
    row = conn.execute("SELECT expires_at FROM admin_sessions WHERE token_hash = ?", (_hash(token),)).fetchone()
    return row is not None and row[0] > now


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_hash(token),))
