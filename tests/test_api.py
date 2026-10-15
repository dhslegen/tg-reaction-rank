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


def _app_client(env, **overrides):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from tgrank.app import create_app
    return TestClient(create_app(replace(env, **overrides)), base_url="https://testserver")


def _lock_out(c, xff):
    for _ in range(5):
        c.post("/api/auth/login", json={"password": "nope"}, headers={"x-forwarded-for": xff})


def test_trusted_proxy_buckets_by_forwarded_for(env):
    with _app_client(env, forwarded_allow_ips="testclient") as c:
        _lock_out(c, "203.0.113.9")
        r = c.post("/api/auth/login", json={"password": PASSWORD}, headers={"x-forwarded-for": "198.51.100.7"})
        assert r.status_code == 200  # 攻击者被锁不影响站长


def test_untrusted_proxy_header_ignored(env):
    with _app_client(env) as c:
        _lock_out(c, "203.0.113.9")
        r = c.post("/api/auth/login", json={"password": PASSWORD}, headers={"x-forwarded-for": "198.51.100.7"})
        assert r.status_code == 429  # 未信任代理时伪造的头不能用来换桶


def test_schedule_view_follows_settings(admin):
    jobs = {j["id"]: j for j in admin.get("/api/schedule").json()["jobs"]}
    assert jobs["push"]["next_run"] is not None
    s = admin.get("/api/settings").json()
    s["push"]["enabled"] = False
    admin.put("/api/settings", json=s)
    jobs = {j["id"]: j for j in admin.get("/api/schedule").json()["jobs"]}
    assert jobs["push"]["next_run"] is None


def test_push_test_reports_failure_when_telegram_missing(seeded, env):
    import time

    from tgrank import store
    from tgrank.db import connect
    from tgrank.records import MessageRecord, ReactionRecord
    s = seeded.get("/api/settings").json()
    s["push"]["range_days"] = 3   # 今天之前的 3 个完整自然日
    seeded.put("/api/settings", json=s)
    with connect(env.db_path) as c:  # 放一条 2 天前的消息，保证有内容可推
        store.import_messages(c, BASIC, [MessageRecord(99, int(time.time()) - 2 * 86400, "u", "新", None, None, None,
                                                       (ReactionRecord("emoji", "👍", 1),))])
    r = seeded.post("/api/push/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == 0 and body["last_push"]["ok"] is False
    assert seeded.get("/api/schedule").json()["last_push"]["ok"] is False
