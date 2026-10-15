import pytest

from tgrank.crypto import BadSecret, SecretBox, derive_key

SECRET = "s" * 32


def test_roundtrip():
    box = SecretBox(SECRET)
    token = box.encrypt("1BVtsOK8Bu...session")
    assert token != "1BVtsOK8Bu...session" and "session" not in token
    assert box.decrypt(token) == "1BVtsOK8Bu...session"


def test_wrong_secret_raises_bad_secret():
    token = SecretBox(SECRET).encrypt("x")
    with pytest.raises(BadSecret):
        SecretBox("t" * 32).decrypt(token)


def test_garbage_raises_bad_secret():
    with pytest.raises(BadSecret):
        SecretBox(SECRET).decrypt("not-a-token")


def test_keys_differ_per_purpose():
    assert derive_key(SECRET, b"a") != derive_key(SECRET, b"b")
    assert len(derive_key(SECRET, b"a")) == 32
