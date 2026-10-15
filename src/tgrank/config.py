"""部署期参数：只从环境变量（.env）读取，启动时校验，运行中不变。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_SECRET_LEN = 32


class ConfigError(ValueError):
    """.env 配置不合法；启动时直接报错退出，避免带病运行。"""


@dataclass(frozen=True)
class Env:
    admin_password: str
    app_secret: str
    api_id: int | None
    api_hash: str | None
    tz: ZoneInfo
    port: int
    data_dir: Path
    proxy: dict | None
    forwarded_allow_ips: str = ""   # 信任哪些反向代理的 X-Forwarded-*；空 = 不信任

    @property
    def telegram_configured(self) -> bool:
        return self.api_id is not None and bool(self.api_hash)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tgrank.db"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Env:
        get = lambda key: (environ.get(key) or "").strip()  # noqa: E731

        password = get("ADMIN_PASSWORD")
        if not password:
            raise ConfigError("缺少 ADMIN_PASSWORD：网页管理员密码必须设置")
        secret = get("APP_SECRET")
        if len(secret) < MIN_SECRET_LEN:
            raise ConfigError(f"APP_SECRET 至少 {MIN_SECRET_LEN} 个字符，可用 `openssl rand -hex 32` 生成")

        raw_id = get("TG_API_ID")
        try:
            api_id = int(raw_id) if raw_id else None
        except ValueError:
            raise ConfigError("TG_API_ID 必须是数字") from None

        try:
            tz = ZoneInfo(get("TZ") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError(f"无法识别的时区 TZ={get('TZ')}，示例：Asia/Shanghai") from None

        try:
            port = int(get("PORT") or 8000)
        except ValueError:
            raise ConfigError("PORT 必须是数字") from None

        return cls(
            admin_password=password,
            app_secret=secret,
            api_id=api_id,
            api_hash=get("TG_API_HASH") or None,
            tz=tz,
            port=port,
            data_dir=Path(get("DATA_DIR") or "data"),
            proxy=parse_proxy(get("TG_PROXY")) if get("TG_PROXY") else None,
            forwarded_allow_ips=get("FORWARDED_ALLOW_IPS"),
        )


def parse_proxy(raw: str) -> dict:
    """把 `socks5://user:pass@host:port` 转成 Telethon 需要的 proxy 字典。"""
    parts = urlsplit(raw)
    if parts.scheme not in ("socks5", "socks4", "http") or not parts.hostname:
        raise ConfigError(f"TG_PROXY 格式应为 socks5://[用户:密码@]主机:端口 或 http://主机:端口，收到 {raw!r}")
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        raise ConfigError(f"TG_PROXY 缺少端口：{raw!r}")

    proxy = {"proxy_type": parts.scheme, "addr": parts.hostname, "port": port}
    if parts.username:
        proxy["username"] = unquote(parts.username)
        proxy["password"] = unquote(parts.password or "")
    proxy["rdns"] = True  # 让代理解析域名，避免本地 DNS 被污染
    return proxy
