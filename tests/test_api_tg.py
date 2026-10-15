import time

import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD
from fakes import channel, emoji, message
from tgrank.app import create_app


@pytest.fixture
def tg_client(tg_env, world, nosleep):
    world.add_chat(channel(1000000001, "周末吃饭群"), [message(i, f"m{i}", reactions=[emoji("👍", i)]) for i in range(1, 6)])
    world.add_chat(channel(1000000002, "频道", megagroup=False), [])
    app = create_app(tg_env, client_factory=world.factory, sleep=nosleep)
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
        yield c


def login_tg(c, world):
    assert c.post("/api/tg/login/phone", json={"phone": world.phone}).status_code == 200
    assert c.post("/api/tg/login/code", json={"code": world.code}).json() == {"next": "done"}


def wait_until(fn, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError("等待超时")


def test_status_and_login_flow(tg_client, world):
    assert tg_client.get("/api/tg/status").json()["state"] == "logged_out"
    world.password = "pw"
    tg_client.post("/api/tg/login/phone", json={"phone": world.phone})
    assert tg_client.post("/api/tg/login/code", json={"code": world.code}).json() == {"next": "password"}
    assert tg_client.get("/api/tg/status").json()["login_step"] == "password"
    r = tg_client.post("/api/tg/login/password", json={"password": "bad"})
    assert r.status_code == 400 and "两步验证" in r.json()["detail"]
    assert tg_client.post("/api/tg/login/password", json={"password": "pw"}).status_code == 200
    assert tg_client.get("/api/tg/status").json()["state"] == "authorized"


def test_dialogs_require_telegram_login(tg_client):
    r = tg_client.get("/api/tg/dialogs")
    assert r.status_code == 409


def test_add_chat_backfills_in_background(tg_client, world):
    login_tg(tg_client, world)
    dialogs = tg_client.get("/api/tg/dialogs").json()
    assert {d["title"]: d["kind_label"] for d in dialogs} == {"周末吃饭群": "群", "频道": "频道"}
    cid = next(d["chat_id"] for d in dialogs if d["title"] == "周末吃饭群")
    assert tg_client.post("/api/chats", json={"chat_id": cid}).status_code == 201
    wait_until(lambda: tg_client.get("/api/chats").json()[0]["history_complete"])
    chat = tg_client.get("/api/chats").json()[0]
    assert chat["messages"] == 5 and chat["source"] == "api"
    assert next(d for d in tg_client.get("/api/tg/dialogs").json() if d["chat_id"] == cid)["added"] is True


def test_add_unknown_chat_404(tg_client, world):
    login_tg(tg_client, world)
    assert tg_client.post("/api/chats", json={"chat_id": -1009999}).status_code == 404


def test_sync_now(tg_client, world):
    login_tg(tg_client, world)
    cid = -1001000000001
    tg_client.post("/api/chats", json={"chat_id": cid})
    wait_until(lambda: tg_client.get("/api/chats").json()[0]["history_complete"])
    world.history[cid][6] = message(6, "新消息", reactions=[emoji("🔥", 1)])
    assert tg_client.post(f"/api/chats/{cid}/sync", json={}).json()["queued"] is True
    wait_until(lambda: tg_client.get("/api/chats").json()[0]["messages"] == 6)


def test_sync_now_rejects_import_only_chat(seeded):
    r = seeded.post("/api/chats/-1001234567890/sync", json={})
    assert r.status_code == 409


def test_toggle_sync(tg_client, world):
    login_tg(tg_client, world)
    cid = -1001000000001
    tg_client.post("/api/chats", json={"chat_id": cid})
    assert tg_client.patch(f"/api/chats/{cid}", json={"sync_enabled": False}).json()["sync_enabled"] is False
    assert tg_client.patch(f"/api/chats/{cid}", json={"sync_enabled": True}).json()["sync_enabled"] is True


def test_logout(tg_client, world):
    login_tg(tg_client, world)
    assert tg_client.post("/api/tg/logout", json={}).status_code == 200
    assert tg_client.get("/api/tg/status").json()["state"] == "logged_out"


def test_paused_api_chat_still_reported_as_api(tg_client, world):
    login_tg(tg_client, world)
    cid = -1001000000001
    tg_client.post("/api/chats", json={"chat_id": cid})
    wait_until(lambda: tg_client.get("/api/chats").json()[0]["history_complete"])
    tg_client.patch(f"/api/chats/{cid}", json={"sync_enabled": False})
    assert tg_client.get("/api/chats").json()[0]["source"] == "api"
