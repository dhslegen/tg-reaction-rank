from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tgrank.config import ConfigError, Env, parse_proxy

GOOD = {
    "ADMIN_PASSWORD": "correct horse",
    "APP_SECRET": "x" * 32,
    "TG_API_ID": "12345",
    "TG_API_HASH": "abcdef",
    "TZ": "Asia/Shanghai",
    "DATA_DIR": "/tmp/tgrank-test",
}


def test_reads_all_fields():
    env = Env.from_environ(GOOD)
    assert env.api_id == 12345
    assert env.api_hash == "abcdef"
    assert env.tz == ZoneInfo("Asia/Shanghai")
    assert env.data_dir == Path("/tmp/tgrank-test")
    assert env.telegram_configured


def test_telegram_optional_at_startup():
    env = Env.from_environ({k: v for k, v in GOOD.items() if not k.startswith("TG_")})
    assert not env.telegram_configured


@pytest.mark.parametrize("key,value", [
    ("APP_SECRET", "short"),
    ("APP_SECRET", ""),
    ("ADMIN_PASSWORD", ""),
    ("TG_API_ID", "not-a-number"),
    ("TZ", "Mars/Olympus"),
])
def test_rejects_bad_values(key, value):
    with pytest.raises(ConfigError):
        Env.from_environ({**GOOD, key: value})


def test_tz_defaults_to_utc():
    env = Env.from_environ({k: v for k, v in GOOD.items() if k != "TZ"})
    assert env.tz == ZoneInfo("UTC")


def test_parse_socks5_proxy_with_auth():
    assert parse_proxy("socks5://u:p%40ss@10.0.0.1:1080") == {
        "proxy_type": "socks5", "addr": "10.0.0.1", "port": 1080,
        "username": "u", "password": "p@ss", "rdns": True,
    }


def test_parse_http_proxy_without_auth():
    assert parse_proxy("http://proxy.lan:8080") == {
        "proxy_type": "http", "addr": "proxy.lan", "port": 8080, "rdns": True,
    }


@pytest.mark.parametrize("raw", ["ftp://h:1", "socks5://hostonly", "garbage"])
def test_parse_proxy_rejects_bad(raw):
    with pytest.raises(ConfigError):
        parse_proxy(raw)


def test_empty_proxy_is_none():
    assert Env.from_environ({**GOOD, "TG_PROXY": ""}).proxy is None


def test_forwarded_allow_ips_defaults_to_untrusted():
    assert Env.from_environ(GOOD).forwarded_allow_ips == ""
    assert Env.from_environ({**GOOD, "FORWARDED_ALLOW_IPS": " 172.16.0.0/12 "}).forwarded_allow_ips == "172.16.0.0/12"
