import pytest
from pydantic import ValidationError

from tgrank import boards
from tgrank.boards import BoardError, BoardIn


def test_builtin_board_created_once(conn):
    boards.ensure_builtin(conn)
    boards.ensure_builtin(conn)
    [b] = boards.list_boards(conn)
    assert (b["name"], b["builtin"], b["default_weight"], b["weights"]) == ("综合", True, 1, {})


def test_create_normalizes_emoji_keys(conn):
    bid = boards.create_board(conn, BoardIn(name=" 最好笑 ", default_weight=0, custom_emoji_weight=0,
                                            paid_weight=0, weights={"😂": 1, "❤️": 0.5}))
    b = boards.get_board(conn, bid)
    assert b["name"] == "最好笑" and b["weights"] == {"😂": 1, "❤": 0.5}


def test_duplicate_name_rejected(conn):
    boards.create_board(conn, BoardIn(name="争议"))
    with pytest.raises(BoardError, match="已存在"):
        boards.create_board(conn, BoardIn(name="争议"))


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": "x" * 31}, {"name": "a", "default_weight": 101},
    {"name": "a", "paid_weight": -10.5}, {"name": "a", "weights": {"": 1}},
    {"name": "a", "weights": {"👍": 200}},
])
def test_validation(bad):
    with pytest.raises(ValidationError):
        BoardIn(**bad)


def test_negative_weights_allowed():
    assert BoardIn(name="争议", weights={"👎": -10}).weights == {"👎": -10}


def test_update_replaces_weights(conn):
    bid = boards.create_board(conn, BoardIn(name="a", weights={"👍": 2}))
    boards.update_board(conn, bid, BoardIn(name="b", weights={"🔥": 3}, push_enabled=True))
    b = boards.get_board(conn, bid)
    assert (b["name"], b["weights"], b["push_enabled"]) == ("b", {"🔥": 3}, True)


def test_builtin_only_push_toggle(conn):
    boards.ensure_builtin(conn)
    bid = boards.list_boards(conn)[0]["id"]
    boards.update_board(conn, bid, BoardIn(name="综合", push_enabled=True))
    assert boards.get_board(conn, bid)["push_enabled"] is True
    with pytest.raises(BoardError):
        boards.update_board(conn, bid, BoardIn(name="综合", weights={"👍": 5}))
    with pytest.raises(BoardError):
        boards.delete_board(conn, bid)


def test_delete_and_missing(conn):
    bid = boards.create_board(conn, BoardIn(name="a"))
    boards.delete_board(conn, bid)
    with pytest.raises(boards.BoardNotFound):
        boards.get_board(conn, bid)
