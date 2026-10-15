import pytest

from conftest import PASSWORD

BASIC = -1001234567890
FORUM = -1002222222222


def test_healthz_ok_without_telegram(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/chats"), ("get", "/api/boards"), ("get", "/api/settings"),
    ("get", f"/api/chats/{BASIC}/ranking"), ("get", "/api/auth/me"),
])
def test_api_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_login_sets_strict_httponly_cookie(client):
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert client.get("/api/auth/me").json() == {"ok": True}


def test_wrong_password_then_rate_limited(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429 and r.json()["retry_after"] > 0


def test_logout_invalidates_session(admin):
    assert admin.post("/api/auth/logout", json={}).status_code == 200
    assert admin.get("/api/auth/me").status_code == 401


def test_unsafe_methods_require_json(admin):
    r = admin.post("/api/boards", content="name=x", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_chats_list(seeded):
    chats = {c["chat_id"]: c for c in seeded.get("/api/chats").json()}
    assert chats[BASIC]["title"] == "周末吃饭群"
    assert chats[BASIC]["messages"] == 5 and chats[BASIC]["reacted"] == 4
    assert chats[FORUM]["is_forum"] is True and chats[BASIC]["source"] == "import"


def test_ranking_default_board(seeded):
    board = seeded.get("/api/boards").json()[0]["id"]
    r = seeded.get(f"/api/chats/{BASIC}/ranking", params={"board": board}).json()
    assert [i["msg_id"] for i in r["items"]] == [3, 2, 4, 6]
    assert r["total"] == 4 and r["link_base"] == "https://t.me/c/1234567890/"


def test_ranking_filters(seeded):
    board = seeded.get("/api/boards").json()[0]["id"]
    r = seeded.get(f"/api/chats/{FORUM}/ranking", params={"board": board, "topic": 10}).json()
    assert [i["msg_id"] for i in r["items"]] == [12, 11]
    r = seeded.get(f"/api/chats/{FORUM}/ranking", params={"board": board, "q": "万历"}).json()
    assert [i["msg_id"] for i in r["items"]] == [21]
    r = seeded.get(f"/api/chats/{FORUM}/ranking", params={"board": board, "range": "custom", "from": "2026-09-02", "to": "2026-09-02"}).json()
    assert [i["msg_id"] for i in r["items"]] == [21]


def test_ranking_bad_params(seeded):
    assert seeded.get(f"/api/chats/{BASIC}/ranking", params={"board": 999}).status_code == 404
    assert seeded.get(f"/api/chats/{BASIC}/ranking", params={"board": 1, "range": "forever"}).status_code == 422
    assert seeded.get(f"/api/chats/{BASIC}/ranking", params={"board": 1, "limit": 500}).status_code == 422


def test_topics_and_emojis(seeded):
    topics = seeded.get(f"/api/chats/{FORUM}/topics").json()
    assert {t["topic_id"]: t["title"] for t in topics} == {1: "General", 10: "科幻", 20: "中国历史"}
    emojis = seeded.get(f"/api/chats/{BASIC}/emojis").json()
    assert emojis[0]["label"] == "😂"


def test_board_crud(admin):
    r = admin.post("/api/boards", json={"name": "最好笑", "default_weight": 0, "weights": {"😂": 1}})
    assert r.status_code == 201
    bid = r.json()["id"]
    assert admin.post("/api/boards", json={"name": "最好笑"}).status_code == 409
    assert admin.put(f"/api/boards/{bid}", json={"name": "好笑", "weights": {"🤣": 2}}).status_code == 200
    assert admin.get("/api/boards").json()[1]["weights"] == {"🤣": 2}
    assert admin.delete(f"/api/boards/{bid}").status_code == 204
    builtin = admin.get("/api/boards").json()[0]["id"]
    assert admin.delete(f"/api/boards/{builtin}").status_code == 409
    assert admin.post("/api/boards", json={"name": "x", "weights": {"👍": 1000}}).status_code == 422


def test_settings_roundtrip(admin):
    s = admin.get("/api/settings").json()
    s["sync"]["refresh_days"] = 3
    assert admin.put("/api/settings", json=s).status_code == 200
    assert admin.get("/api/settings").json()["sync"]["refresh_days"] == 3
    s["push"]["time"] = "bad"
    assert admin.put("/api/settings", json=s).status_code == 422


def test_chat_patch_and_delete(seeded):
    assert seeded.delete(f"/api/chats/{BASIC}").status_code == 204
    assert BASIC not in [c["chat_id"] for c in seeded.get("/api/chats").json()]
    assert seeded.delete(f"/api/chats/{BASIC}").status_code == 404


def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
