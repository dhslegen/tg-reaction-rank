from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import boards
from ..boards import BoardError, BoardIn, BoardNotFound
from .deps import Admin, Db

router = APIRouter(prefix="/api/boards", tags=["boards"], dependencies=[Admin])


def _guard(fn, *args):
    try:
        return fn(*args)
    except BoardNotFound:
        raise HTTPException(404, "没有这个榜单") from None
    except BoardError as e:
        raise HTTPException(409, str(e)) from None


@router.get("")
def list_boards(conn: Db):
    return boards.list_boards(conn)


@router.post("", status_code=201)
def create_board(body: BoardIn, conn: Db):
    bid = _guard(boards.create_board, conn, body)
    return boards.get_board(conn, bid)


@router.put("/{board_id}")
def update_board(board_id: int, body: BoardIn, conn: Db):
    _guard(boards.update_board, conn, board_id, body)
    return boards.get_board(conn, board_id)


@router.delete("/{board_id}", status_code=204)
def delete_board(board_id: int, conn: Db):
    _guard(boards.delete_board, conn, board_id)
    return Response(status_code=204)
