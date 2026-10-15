"""用 APP_SECRET 派生密钥加密 Telegram session。

APP_SECRET 是高熵随机串，用 HKDF 派生即可（PBKDF2 这类慢哈希是给低熵口令用的）。
不同用途用不同 info 派生出互不相关的子密钥。
"""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SESSION_PURPOSE = b"tgrank/telegram-session/v1"


class BadSecret(ValueError):
    """密文无法用当前 APP_SECRET 解开：多半是迁移时没带原来的 .env。"""


def derive_key(app_secret: str, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(app_secret.encode())


class SecretBox:
    def __init__(self, app_secret: str):
        self._fernet = Fernet(base64.urlsafe_b64encode(derive_key(app_secret, SESSION_PURPOSE)))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError):
            raise BadSecret("无法解密已保存的 Telegram 登录状态，APP_SECRET 可能已更改") from None
