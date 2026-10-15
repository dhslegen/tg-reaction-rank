from dataclasses import replace

import pytest
from telethon.errors import AuthKeyDuplicatedError, AuthKeyUnregisteredError, FloodWaitError

from fakes import channel
from tgrank import store
from tgrank.crypto import SecretBox
from tgrank.db import connect
from tgrank.records import ChatInfo
from tgrank.tg.manager import TgLoginError, TgManager, TgState, TgUnavailable


async def test_unconfigured_without_api_id(tg_env, world):
    m = TgManager(replace(tg_env, api_id=None), client_factory=world.factory)
    await m.start()
    assert m.state is TgState.UNCONFIGURED
    with pytest.raises(TgLoginError, match="TG_API_ID"):
        await m.login_phone("+1")


async def test_logged_out_without_session(mgr):
    assert mgr.state is TgState.LOGGED_OUT
    with pytest.raises(TgUnavailable):
        await mgr.call(lambda c: c.get_me())


async def test_login_with_code_persists_encrypted_session(mgr, world, tg_env):
    await mgr.login_phone(world.phone)
    assert await mgr.login_code(world.code) == "done"
    assert mgr.state is TgState.AUTHORIZED
    assert mgr.status()["me"]["name"] == "站长"
    assert mgr.status()["me"]["phone"].startswith("+86") and "****" in mgr.status()["me"]["phone"]
    with connect(tg_env.db_path) as c:
        stored = c.execute("SELECT value FROM meta WHERE key='tg_session'").fetchone()[0]
    assert "session-" not in stored
    assert SecretBox(tg_env.app_secret).decrypt(stored).startswith("session-")


async def test_login_with_two_step_password(mgr, world):
    world.password = "pw"
    await mgr.login_phone(world.phone)
    assert await mgr.login_code(world.code) == "password"
    with pytest.raises(TgLoginError, match="两步验证密码不正确"):
        await mgr.login_password("wrong")
    await mgr.login_password("pw")
    assert mgr.state is TgState.AUTHORIZED


async def test_wrong_code_is_user_facing_error(mgr, world):
    await mgr.login_phone(world.phone)
    with pytest.raises(TgLoginError, match="验证码不正确"):
        await mgr.login_code("00000")


async def test_code_without_phone_step(mgr):
    with pytest.raises(TgLoginError, match="先填写手机号"):
        await mgr.login_code("1")


async def test_session_survives_restart(authed, tg_env, world):
    m2 = TgManager(tg_env, client_factory=world.factory)
    await m2.start()
    assert m2.state is TgState.AUTHORIZED
    await m2.stop()


async def test_undecryptable_session_reports_relogin(authed, tg_env, world):
    m2 = TgManager(replace(tg_env, app_secret="z" * 40), client_factory=world.factory)
    await m2.start()
    assert m2.state is TgState.RELOGIN_REQUIRED
    assert "APP_SECRET" in m2.status()["last_error"]


async def test_revoked_session_on_start_reports_relogin(authed, tg_env, world):
    world.valid_sessions.clear()
    m2 = TgManager(tg_env, client_factory=world.factory)
    await m2.start()
    assert m2.state is TgState.RELOGIN_REQUIRED


async def test_offline_on_start_then_recovers(authed, tg_env, world, nosleep):
    world.fail("connect", ConnectionError("down"))
    m2 = TgManager(tg_env, client_factory=world.factory, sleep=nosleep)
    await m2.start()
    assert m2.state is TgState.OFFLINE
    assert (await m2.call(lambda c: c.get_me())).first_name == "站长"
    assert m2.state is TgState.AUTHORIZED
    await m2.stop()


@pytest.mark.parametrize("exc", [AuthKeyUnregisteredError(request=None), AuthKeyDuplicatedError(request=None)])
async def test_auth_key_error_marks_unauthorized_and_stops_jobs(authed, world, exc):
    world.fail("get_me", exc)
    with pytest.raises(TgUnavailable):
        await authed.call(lambda c: c.get_me())
    assert authed.state is TgState.RELOGIN_REQUIRED
    with pytest.raises(TgUnavailable):
        await authed.call(lambda c: c.get_me())
    assert world.calls.count("get_me") == 2  # 登录时 1 次 + 出错那 1 次，之后不再打扰 Telegram


async def test_flood_wait_sleeps_then_retries(authed, world, nosleep):
    world.fail("get_me", FloodWaitError(request=None, capture=120))
    assert (await authed.call(lambda c: c.get_me())).first_name == "站长"
    assert 120 < nosleep.calls[0] <= 126
    assert authed.status()["flood_until"] is None


async def test_flood_wait_too_long_gives_up(authed, world):
    world.fail("get_me", FloodWaitError(request=None, capture=7200))
    with pytest.raises(FloodWaitError):
        await authed.call(lambda c: c.get_me())
    assert authed.state is TgState.AUTHORIZED


async def test_network_errors_back_off_then_offline(authed, world, nosleep):
    world.fail("get_me", *[ConnectionError("x")] * 6)
    with pytest.raises(TgUnavailable):
        await authed.call(lambda c: c.get_me())
    assert nosleep.calls == [5, 10, 20, 40, 80]
    assert authed.state is TgState.OFFLINE


async def test_logout_clears_session(authed, tg_env):
    await authed.logout()
    assert authed.state is TgState.LOGGED_OUT
    with connect(tg_env.db_path) as c:
        assert c.execute("SELECT 1 FROM meta WHERE key='tg_session'").fetchone() is None


async def test_login_refused_when_already_authorized(authed, world):
    with pytest.raises(TgLoginError, match="已登录"):
        await authed.login_phone(world.phone)


async def test_list_dialogs_groups_and_channels(authed, world):
    world.add_chat(channel(100, "群A"))
    world.add_chat(channel(200, "频道B", megagroup=False))
    dialogs = await authed.list_dialogs()
    assert [(d.title, d.kind) for d in dialogs] == [("群A", "private_supergroup"), ("频道B", "private_channel")]


async def test_login_refreshes_access_hash_and_pauses_unreachable(mgr, world, tg_env):
    with connect(tg_env.db_path) as c:
        store.upsert_chat(c, ChatInfo(-1000000000100, "旧群", "private_supergroup", access_hash=1), sync_enabled=True)
        store.upsert_chat(c, ChatInfo(-1000000000300, "别人的群", "private_supergroup", access_hash=1), sync_enabled=True)
    world.add_chat(channel(100, "旧群", access_hash=999))
    await mgr.login_phone(world.phone)
    await mgr.login_code(world.code)
    with connect(tg_env.db_path) as c:
        rows = {r["chat_id"]: r for r in c.execute("SELECT * FROM chats")}
    assert rows[-1000000000100]["access_hash"] == 999 and rows[-1000000000100]["sync_enabled"] == 1
    assert rows[-1000000000300]["sync_enabled"] == 0 and "无法访问" in rows[-1000000000300]["last_error"]


def test_state_is_connecting_before_start(tg_env, world):
    assert TgManager(tg_env, client_factory=world.factory).state is TgState.CONNECTING
