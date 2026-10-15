"""榜单 = 名称 + 表情权重表。内置「综合」全部权重为 1，只能改推送开关。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from .records import normalize_emoji

Weight = Annotated[float, Field(ge=-10, le=100)]
BUILTIN_NAME = "综合"


class BoardError(ValueError):
    pass


class BoardNotFound(LookupError):
    pass


class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    default_weight: Weight = 1
    custom_emoji_weight: Weight = 1
    paid_weight: Weight = 1
    weights: dict[str, Weight] = Field(default_factory=dict, max_length=100)
    push_enabled: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("weights")
    @classmethod
    def _normalize_keys(cls, v: dict[str, float]) -> dict[str, float]:
        out = {}
        for k, w in v.items():
            key = normalize_emoji(k)
            if not key:
                raise ValueError("表情不能为空")
            out[key] = w
        return out


def ensure_builtin(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM boards WHERE builtin = 1").fetchone() is None:
        conn.execute("INSERT INTO boards(name, builtin, position) VALUES (?, 1, 0)", (BUILTIN_NAME,))


def _row_to_board(conn, row) -> dict:
    weights = dict(conn.execute("SELECT emoji, weight FROM board_weights WHERE board_id = ? ORDER BY emoji", (row["id"],)).fetchall())
    return {
        "id": row["id"], "name": row["name"],
        "default_weight": row["default_weight"], "custom_emoji_weight": row["custom_emoji_weight"],
        "paid_weight": row["paid_weight"], "weights": weights,
        "push_enabled": bool(row["push_enabled"]), "builtin": bool(row["builtin"]),
    }


def list_boards(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM boards ORDER BY builtin DESC, position, id").fetchall()
    return [_row_to_board(conn, r) for r in rows]


def get_board(conn, board_id: int) -> dict:
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        raise BoardNotFound(board_id)
    return _row_to_board(conn, row)


def _name_taken(conn, name: str, exclude_id: int | None = None) -> bool:
    return conn.execute("SELECT 1 FROM boards WHERE name = ? AND id IS NOT ?", (name, exclude_id)).fetchone() is not None


def _write_weights(conn, board_id: int, weights: dict[str, float]) -> None:
    conn.execute("DELETE FROM board_weights WHERE board_id = ?", (board_id,))
    conn.executemany("INSERT INTO board_weights(board_id, emoji, weight) VALUES (?, ?, ?)",
                     [(board_id, k, w) for k, w in weights.items()])


def create_board(conn, data: BoardIn) -> int:
    if _name_taken(conn, data.name):
        raise BoardError(f"榜单「{data.name}」已存在")
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM boards").fetchone()[0]
    cur = conn.execute(
        """INSERT INTO boards(name, default_weight, custom_emoji_weight, paid_weight, push_enabled, position)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (data.name, data.default_weight, data.custom_emoji_weight, data.paid_weight, int(data.push_enabled), position),
    )
    _write_weights(conn, cur.lastrowid, data.weights)
    return cur.lastrowid


def update_board(conn, board_id: int, data: BoardIn) -> None:
    current = get_board(conn, board_id)
    if current["builtin"]:
        changed = (data.name, data.default_weight, data.custom_emoji_weight, data.paid_weight, data.weights) != (
            current["name"], current["default_weight"], current["custom_emoji_weight"], current["paid_weight"], current["weights"])
        if changed:
            raise BoardError("内置「综合」榜只能修改推送开关")
        conn.execute("UPDATE boards SET push_enabled = ? WHERE id = ?", (int(data.push_enabled), board_id))
        return
    if _name_taken(conn, data.name, exclude_id=board_id):
        raise BoardError(f"榜单「{data.name}」已存在")
    conn.execute(
        """UPDATE boards SET name = ?, default_weight = ?, custom_emoji_weight = ?, paid_weight = ?, push_enabled = ?
           WHERE id = ?""",
        (data.name, data.default_weight, data.custom_emoji_weight, data.paid_weight, int(data.push_enabled), board_id),
    )
    _write_weights(conn, board_id, data.weights)


def delete_board(conn, board_id: int) -> None:
    if get_board(conn, board_id)["builtin"]:
        raise BoardError("内置「综合」榜不能删除")
    conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
