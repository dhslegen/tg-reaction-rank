"""SQLite 连接与迁移。

每个工作单元新开一个连接（sqlite 连接很便宜），不跨线程共享；WAL 让读写互不阻塞，
busy_timeout 让偶发的写写冲突排队而不是直接报错。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


@contextmanager
def connect(path: Path):
    """打开自动提交模式的连接；需要原子写入时配合 transaction() 使用。"""
    # FastAPI 的同步依赖和端点可能跑在线程池的不同线程里；每个连接仍只被一个请求顺序使用
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)  # 自己管理事务
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """显式写事务；BEGIN IMMEDIATE 一开始就拿写锁，避免读后升级写时死锁。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> None:
    sql = resources.files("tgrank").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
