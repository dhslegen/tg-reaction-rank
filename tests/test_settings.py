import pytest
from pydantic import ValidationError

from tgrank.settings import PushSettings, Settings, load_settings, save_settings


def test_defaults_when_nothing_saved(conn):
    s = load_settings(conn)
    assert (s.sync.new_interval_min, s.sync.refresh_interval_min, s.sync.refresh_days) == (10, 60, 7)
    assert (s.sync.calibrate_weekday, s.sync.calibrate_time) == (6, "04:00")
    assert (s.push.enabled, s.push.frequency, s.push.weekday, s.push.time, s.push.target) == (True, "weekly", 0, "09:00", "me")


def test_roundtrip(conn):
    s = Settings()
    s = s.model_copy(update={"push": PushSettings(frequency="monthly", monthday=15, target="-1001234")})
    save_settings(conn, s)
    assert load_settings(conn) == s


def test_effective_range_follows_frequency():
    assert PushSettings().effective_range_days == 7
    assert PushSettings(frequency="monthly").effective_range_days == 30
    assert PushSettings(frequency="monthly", range_days=14).effective_range_days == 14


@pytest.mark.parametrize("bad", [
    {"sync": {"new_interval_min": 1}},
    {"sync": {"refresh_days": 0}},
    {"sync": {"calibrate_time": "25:00"}},
    {"push": {"time": "9am"}},
    {"push": {"target": "@somebody"}},
    {"push": {"monthday": 31}},
])
def test_validation(bad):
    with pytest.raises(ValidationError):
        Settings.model_validate(bad)


def test_unknown_saved_keys_ignored(conn):
    conn.execute("INSERT INTO meta(key, value) VALUES ('settings', '{\"sync\": {\"refresh_days\": 3, \"legacy\": 1}}')")
    assert load_settings(conn).sync.refresh_days == 3
