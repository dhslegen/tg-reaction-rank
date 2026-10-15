from datetime import datetime

import pytest

from tgrank.context import AppContext
from tgrank.scheduler import Scheduler
from tgrank.settings import PushSettings, Settings, SyncSettings


@pytest.fixture
async def sched(tg_env):
    s = Scheduler(AppContext(env=tg_env))
    s.start(Settings())
    yield s
    s.shutdown()


def job(s, jid):
    return s.aps.get_job(jid)


async def test_default_jobs(sched):
    assert {j.id for j in sched.aps.get_jobs()} == {"fetch_new", "refresh_recent", "calibrate", "push", "backup"}
    assert job(sched, "fetch_new").trigger.interval.total_seconds() == 600
    assert job(sched, "refresh_recent").trigger.interval.total_seconds() == 3600
    assert "day_of_week='sun'" in str(job(sched, "calibrate").trigger) and "hour='4'" in str(job(sched, "calibrate").trigger)
    push = str(job(sched, "push").trigger)
    assert "day_of_week='mon'" in push and "hour='9'" in push
    assert "hour='3'" in str(job(sched, "backup").trigger) and "minute='30'" in str(job(sched, "backup").trigger)
    for j in sched.aps.get_jobs():
        assert j.max_instances == 1 and j.coalesce is True


async def test_timezone_follows_env(sched, tg_env):
    nxt = job(sched, "push").next_run_time
    assert nxt.tzinfo is not None and nxt.utcoffset() == datetime.now(tg_env.tz).utcoffset()


async def test_apply_reschedules_immediately(sched):
    sched.apply(Settings(sync=SyncSettings(new_interval_min=30, calibrate_weekday=2, calibrate_time="01:15"),
                         push=PushSettings(frequency="monthly", monthday=15, time="20:30")))
    assert job(sched, "fetch_new").trigger.interval.total_seconds() == 1800
    assert "day_of_week='wed'" in str(job(sched, "calibrate").trigger)
    push = str(job(sched, "push").trigger)
    assert "day='15'" in push and "hour='20'" in push and "minute='30'" in push


async def test_push_disabled_removes_job_and_reenable_restores(sched):
    sched.apply(Settings(push=PushSettings(enabled=False)))
    assert job(sched, "push") is None
    sched.apply(Settings())
    assert job(sched, "push") is not None


async def test_run_now_moves_next_run(sched):
    before = job(sched, "refresh_recent").next_run_time
    sched.run_now("refresh_recent")
    assert job(sched, "refresh_recent").next_run_time < before


async def test_view_lists_next_runs(sched):
    view = {v["id"]: v for v in sched.view()}
    assert view["push"]["label"] == "精华推送" and view["push"]["next_run"] is not None
