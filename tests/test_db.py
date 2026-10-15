from tgrank.db import SCHEMA_VERSION, connect, migrate


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    with connect(path) as conn:
        migrate(conn)
        migrate(conn)
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert int(version) == SCHEMA_VERSION


def test_connection_pragmas(tmp_path):
    with connect(tmp_path / "t.db") as conn:
        migrate(conn)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_deleting_chat_cascades(tmp_path):
    with connect(tmp_path / "t.db") as conn:
        migrate(conn)
        conn.execute("INSERT INTO chats(chat_id,title,kind,created_at) VALUES (-1001,'g','private_supergroup',0)")
        conn.execute("INSERT INTO messages(chat_id,msg_id,date) VALUES (-1001,1,0)")
        conn.execute("INSERT INTO reactions(chat_id,msg_id,kind,key,count) VALUES (-1001,1,'emoji','👍',2)")
        conn.execute("DELETE FROM chats WHERE chat_id=-1001")
        assert conn.execute("SELECT count(*) FROM reactions").fetchone()[0] == 0
