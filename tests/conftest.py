import pytest

from tgrank.db import connect, migrate


@pytest.fixture
def conn(tmp_path):
    with connect(tmp_path / "test.db") as c:
        migrate(c)
        yield c
