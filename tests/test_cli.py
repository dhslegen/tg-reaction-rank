import pytest

from tgrank.__main__ import cli_login
from tgrank.db import connect


def answers(*values):
    it = iter(values)
    return lambda prompt="": next(it)


async def test_cli_login_writes_session(tg_env, world, capsys):
    code = await cli_login(tg_env, ask=answers(world.phone, world.code), ask_secret=answers(), client_factory=world.factory)
    assert code == 0
    with connect(tg_env.db_path) as c:
        assert c.execute("SELECT 1 FROM meta WHERE key='tg_session'").fetchone()
    assert "docker compose restart app" in capsys.readouterr().out


async def test_cli_login_with_two_step(tg_env, world):
    world.password = "pw"
    code = await cli_login(tg_env, ask=answers(world.phone, world.code), ask_secret=answers("pw"), client_factory=world.factory)
    assert code == 0


async def test_login_refuses_when_session_exists(tg_env, world, authed, capsys):
    before = len(world.calls)
    code = await cli_login(tg_env, ask=answers(), ask_secret=answers(), client_factory=world.factory)
    assert code == 1
    assert "网页" in capsys.readouterr().out
    assert world.calls[before:] == []  # 没有用已有 session 去连接 Telegram


async def test_cli_login_allowed_when_session_undecryptable(tg_env, world):
    with connect(tg_env.db_path) as c:
        c.execute("INSERT INTO meta(key, value) VALUES ('tg_session', 'garbage')")
    code = await cli_login(tg_env, ask=answers(world.phone, world.code), ask_secret=answers(), client_factory=world.factory)
    assert code == 0


async def test_cli_login_unconfigured(tg_env, world):
    from dataclasses import replace
    assert await cli_login(replace(tg_env, api_id=None), ask=answers(), ask_secret=answers(), client_factory=world.factory) == 2
