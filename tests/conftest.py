import pytest

from tgrank.db import connect, migrate


@pytest.fixture
def conn(tmp_path):
    with connect(tmp_path / "test.db") as c:
        migrate(c)
        yield c


from pathlib import Path

from fastapi.testclient import TestClient

from tgrank.app import create_app
from tgrank.config import Env

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery"


@pytest.fixture
def env(tmp_path):
    return Env.from_environ({
        "ADMIN_PASSWORD": PASSWORD, "APP_SECRET": "k" * 40, "TZ": "Asia/Shanghai",
        "DATA_DIR": str(tmp_path / "data"),
    })


@pytest.fixture
def client(env):
    with TestClient(create_app(env), base_url="https://testserver") as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def seeded(admin, env):
    """直接往库里放一个普通群和一个话题群。"""
    from tgrank import store
    from tgrank.db import connect
    from tgrank.desktop import DesktopExport
    from tgrank.records import MessageRecord, TopicRecord

    with connect(env.db_path) as c:
        for name in ("desktop_basic.json", "desktop_forum.json"):
            with open(FIXTURES / name, "rb") as fp:
                exp = DesktopExport(fp, env.tz)
                store.upsert_chat(c, exp.info, sync_enabled=False)
                items = list(exp.records())
                store.import_messages(c, exp.info.chat_id, [i for i in items if isinstance(i, MessageRecord)])
                store.upsert_topics(c, exp.info.chat_id, [i for i in items if isinstance(i, TopicRecord)], overwrite=True)
                if exp.is_forum:
                    store.mark_forum(c, exp.info.chat_id, first_topic_id=exp.first_topic_id)
    return admin


from fakes import FakeWorld


@pytest.fixture
def world():
    return FakeWorld()


@pytest.fixture
def tg_env(tmp_path):
    from tgrank.app import init_db
    e = Env.from_environ({
        "ADMIN_PASSWORD": PASSWORD, "APP_SECRET": "k" * 40, "TZ": "Asia/Shanghai",
        "DATA_DIR": str(tmp_path / "tgdata"), "TG_API_ID": "1", "TG_API_HASH": "h",
    })
    init_db(e)
    return e


class NoSleep:
    """记录等待时长而不真的睡。"""
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


@pytest.fixture
def nosleep():
    return NoSleep()


@pytest.fixture
async def mgr(tg_env, world, nosleep):
    from tgrank.tg.manager import TgManager
    m = TgManager(tg_env, client_factory=world.factory, sleep=nosleep)
    await m.start()
    yield m
    await m.stop()


@pytest.fixture
async def authed(mgr, world):
    await mgr.login_phone(world.phone)
    assert await mgr.login_code(world.code) == "done"
    return mgr
