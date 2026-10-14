import pytest
from xiangqi_robot import Board, Move, START_FEN, is_valid_move, parse_square, square_name


def sq(name):
    return parse_square(name)


def targets(board, name):
    frm = sq(name)
    return {
        square_name((r, c))
        for r in range(10)
        for c in range(9)
        if is_valid_move(board, frm, (r, c))
    }


def test_fen_roundtrip():
    board = Board.start()
    assert board.to_fen() == START_FEN
    assert Board.from_fen(board.to_fen()).grid == board.grid


def test_start_position_has_32_pieces():
    board = Board.start()
    pieces = [ch for row in board.grid for ch in row if ch != "."]
    assert len(pieces) == 32
    assert sum(ch.isupper() for ch in pieces) == 16


def test_square_names():
    assert square_name((9, 0)) == "a0"
    assert square_name((0, 8)) == "i9"
    assert parse_square("h2") == (7, 7)


def test_bad_fen_rejected():
    with pytest.raises(ValueError):
        Board.from_fen("rnbakabnr/9/9 w")
    with pytest.raises(ValueError):
        Board.from_fen("rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABN w")


def test_start_horse_moves_blocked_by_leg():
    assert targets(Board.start(), "b0") == {"a2", "c2"}


def test_cannon_needs_screen_to_capture():
    board = Board.start()
    assert is_valid_move(board, sq("h2"), sq("h9"))
    assert not is_valid_move(board, sq("h2"), sq("h7"))
    assert is_valid_move(board, sq("h2"), sq("h6"))


def test_soldier_moves_forward_only_before_river():
    assert targets(Board.start(), "a3") == {"a4"}


def test_soldier_sideways_after_river():
    board = Board.from_fen("4k4/9/9/9/4P4/9/9/9/9/4K4 w")
    assert targets(board, "e5") == {"e6", "d5", "f5"}


def test_elephant_cannot_cross_river_or_jump_blocked_eye():
    board = Board.start()
    assert targets(board, "c0") == {"a2", "e2"}
    board = Board.from_fen("4k4/9/9/9/9/9/9/9/3P5/2B1K4 w")
    assert targets(board, "c0") == {"a2"}


def test_general_stays_in_palace_and_flying_general():
    board = Board.from_fen("4k4/9/9/9/9/9/9/9/9/4K4 w")
    assert "e9" in targets(board, "e0")
    assert "d0" in targets(board, "e0")
    assert "d1" not in targets(board, "e0")
    blocked = Board.from_fen("4k4/9/9/9/9/4R4/9/9/9/4K4 w")
    assert "e9" not in targets(blocked, "e0")


def test_apply_flips_side_and_moves_piece():
    board = Board.start()
    move = Move("C", sq("h2"), sq("e2"))
    after = board.apply(move)
    assert after.piece_at(sq("e2")) == "C"
    assert after.piece_at(sq("h2")) == "."
    assert after.side_to_move == "b"
    assert board.piece_at(sq("h2")) == "C" 
