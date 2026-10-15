import sqlite3
from datetime import datetime, timedelta

from tgrank import store
from tgrank.backup import make_backup
from tgrank.records import ChatInfo


def test_backup_is_consistent_copy(tmp_path, conn):
    store.upsert_chat(conn, ChatInfo(-1, "群", "private_supergroup"), sync_enabled=False)
    path = make_backup(tmp_path / "test.db", tmp_path / "backups", datetime(2026, 10, 15, 3, 30))
    assert path.name == "tgrank-20261015-033000.db"
    with sqlite3.connect(path) as b:
        assert b.execute("SELECT title FROM chats").fetchone()[0] == "群"
        assert b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_keeps_newest_seven(tmp_path, conn):
    start = datetime(2026, 10, 1, 3, 30)
    for d in range(10):
        make_backup(tmp_path / "test.db", tmp_path / "backups", start + timedelta(days=d))
    names = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(names) == 7 and names[0] == "tgrank-20261004-033000.db"


def test_ignores_unrelated_files(tmp_path, conn):
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "手动备份.db").write_text("x")
    for d in range(8):
        make_backup(tmp_path / "test.db", tmp_path / "backups", datetime(2026, 10, 1 + d))
    assert (tmp_path / "backups" / "手动备份.db").exists()
