from tgrank import auth
from tgrank.auth import LoginLimiter


def test_ip_locked_after_five_failures():
    lim = LoginLimiter()
    for _ in range(5):
        assert lim.retry_after("1.1.1.1", now=100) is None
        lim.record_failure("1.1.1.1", now=100)
    assert lim.retry_after("1.1.1.1", now=101) == 899
    assert lim.retry_after("2.2.2.2", now=101) is None
    assert lim.retry_after("1.1.1.1", now=100 + 900) is None


def test_failures_outside_window_are_forgotten():
    lim = LoginLimiter()
    for t in range(4):
        lim.record_failure("ip", now=t)
    lim.record_failure("ip", now=1000)
    assert lim.retry_after("ip", now=1000) is None


def test_success_clears_ip_counter():
    lim = LoginLimiter()
    for _ in range(4):
        lim.record_failure("ip", now=0)
    lim.record_success("ip")
    lim.record_failure("ip", now=1)
    assert lim.retry_after("ip", now=1) is None


def test_global_limit_blocks_even_with_rotating_ips():
    lim = LoginLimiter()
    for i in range(30):
        lim.record_failure(f"10.0.0.{i}", now=0)
    assert lim.retry_after("99.99.99.99", now=1) == 899


def test_password_check_constant_time_semantics():
    assert auth.password_ok("secret pw", "secret pw")
    assert not auth.password_ok("secret pw", "secret")
    assert not auth.password_ok("secret pw", "")


def test_session_lifecycle(conn):
    token = auth.create_session(conn, now=0)
    assert len(token) >= 40
    assert auth.session_valid(conn, token, now=10)
    assert not auth.session_valid(conn, token, now=auth.SESSION_TTL + 1)
    assert not auth.session_valid(conn, "forged", now=10)
    assert not auth.session_valid(conn, None, now=10)
    token2 = auth.create_session(conn, now=0)
    auth.delete_session(conn, token2)
    assert not auth.session_valid(conn, token2, now=1)


def test_tokens_stored_hashed(conn):
    token = auth.create_session(conn, now=0)
    stored = conn.execute("SELECT token_hash FROM admin_sessions").fetchone()[0]
    assert token not in stored
