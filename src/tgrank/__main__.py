"""命令行入口：`python -m tgrank serve`（默认）或 `python -m tgrank login`。"""
from __future__ import annotations

import asyncio
import getpass
import os
import sys
from collections.abc import Callable

from .config import ConfigError, Env
from .crypto import BadSecret, SecretBox
from .db import connect

MAX_TRIES = 3


def _load_env() -> Env:
    try:
        return Env.from_environ(os.environ)
    except ConfigError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        raise SystemExit(2) from None


def serve() -> None:
    import uvicorn

    from .app import create_app
    env = _load_env()
    # 单 worker：同一 Telegram session 绝不能多进程并发；代理头由应用层按 FORWARDED_ALLOW_IPS 处理
    uvicorn.run(create_app(env), host="0.0.0.0", port=env.port, workers=1, proxy_headers=False,
                log_level="info", access_log=False)


def _has_valid_session(env: Env) -> bool:
    with connect(env.db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'tg_session'").fetchone()
    if row is None:
        return False
    try:
        SecretBox(env.app_secret).decrypt(row[0])
    except BadSecret:
        return False  # 解不开的旧 session 等于没有，可以覆盖
    return True


async def cli_login(env: Env, *, ask: Callable[[str], str], ask_secret: Callable[[str], str],
                    client_factory: Callable | None = None) -> int:
    """网页向导的备用方案。只在没有有效 session 时写入，且从不连接已有 session，
    因此即使主服务正在运行也不会出现同一 session 被两个进程同时使用。"""
    from .app import init_db
    from .tg.manager import TgLoginError, TgManager

    if not env.telegram_configured:
        print("还没有配置 TG_API_ID / TG_API_HASH，请先在 .env 中填写。")
        return 2
    init_db(env)
    if _has_valid_session(env):
        print("已存在有效的 Telegram 登录状态，CLI 不会覆盖它。\n"
              "如需换号：在网页「Telegram」页退出登录后再运行本命令；日常请直接使用网页向导。")
        return 1

    mgr = TgManager(env, client_factory=client_factory)
    try:
        await mgr.login_phone(ask("手机号（带国家区号，如 +8613800000000）："))
        step = None
        for _ in range(MAX_TRIES):
            try:
                step = await mgr.login_code(ask("验证码："))
                break
            except TgLoginError as e:
                print(e)
        if step == "password":
            for _ in range(MAX_TRIES):
                try:
                    await mgr.login_password(ask_secret("两步验证密码："))
                    step = "done"
                    break
                except TgLoginError as e:
                    print(e)
        if step != "done":
            print("登录未完成。")
            return 1
    except TgLoginError as e:
        print(e)
        return 1
    finally:
        await mgr.stop()
    print(f"登录成功：{mgr.me['name']}。\n请执行 docker compose restart app 让服务加载新的登录状态。")
    return 0


def main(argv: list[str]) -> None:
    command = argv[1] if len(argv) > 1 else "serve"
    if command == "serve":
        serve()
    elif command == "login":
        raise SystemExit(asyncio.run(cli_login(_load_env(), ask=input, ask_secret=getpass.getpass)))
    else:
        print("用法：python -m tgrank [serve|login]", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv)
