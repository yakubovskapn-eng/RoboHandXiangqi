import copy
import random
import pytest

from xiangqi_robot import (
    Board,
    Move,
    MoveDetectionError,
    detect_move,
    detect_move_from_pieces,
    parse_square,
    pseudo_legal_moves,
)

H2, E2, H9 = parse_square("h2"), parse_square("e2"), parse_square("h9")


def test_quiet_move_detected_from_colors():
    board = Board.start()
    after = board.apply(Move("C", H2, E2))
    move = detect_move(board, after.colors())
    assert move.uci == "h2e2"
    assert move.piece == "C"
    assert not move.is_capture


def test_capture_detected_from_colors():
    board = Board.start()
    after = board.apply(Move("C", H2, H9, captured="n"))
    move = detect_move(board, after.colors())
    assert move.uci == "h2h9"
    assert move.is_capture
    assert move.captured == "n"


def test_black_move_after_red():
    board = Board.start()
    board = board.apply(Move("C", H2, E2))
    black = Move("n", parse_square("h9"), parse_square("g7"))
    move = detect_move(board, board.apply(black).colors())
    assert move.uci == "h9g7"


def test_no_change_is_error():
    board = Board.start()
    with pytest.raises(MoveDetectionError, match="не змінилася"):
        detect_move(board, board.colors())


def test_occupancy_loss_only_is_ambiguous():
    board = Board.start()
    after = board.colors()
    r, c = H2
    after[r][c] = 0
    with pytest.raises(MoveDetectionError, match="Потрібна карта кольорів"):
        detect_move(board, after)


def test_too_many_changes_is_error():
    board = Board.start()
    after = board.apply(Move("C", H2, E2)).colors()
    r, c = parse_square("a0")
    after[r][c] = 0
    with pytest.raises(MoveDetectionError, match="Забагато змін"):
        detect_move(board, after)


def test_wrong_side_is_error():
    board = Board.start()
    black = Move("c", parse_square("h7"), parse_square("e7"))
    after = Board(board.grid, "b").apply(black).colors()
    with pytest.raises(MoveDetectionError, match="черга"):
        detect_move(board, after)


def test_illegal_move_rejected_but_allowed_without_rule_check():
    board = Board.start()
    rook_jump = Move("R", parse_square("a0"), parse_square("a5"))
    after = board.apply(rook_jump).colors()
    with pytest.raises(MoveDetectionError, match="суперечить правилам"):
        detect_move(board, after)
    assert detect_move(board, after, check_rules=False).uci == "a0a5"


def test_full_piece_grid_consistency():
    board = Board.start()
    good = board.apply(Move("C", H2, E2))
    assert detect_move_from_pieces(board, good).uci == "h2e2"

    misread = Board(good.grid, good.side_to_move)
    misread.grid[E2[0]][E2[1]] = "R"
    with pytest.raises(MoveDetectionError, match="помилка класифікації"):
        detect_move_from_pieces(board, misread)


@pytest.mark.parametrize("seed", range(5))
def test_random_games_roundtrip(seed):
    """
    Випадкові партії
    """
    rng = random.Random(seed)
    board = Board.start()
    checked = 0
    for _ in range(120):
        moves = list(pseudo_legal_moves(board))
        if not moves:
            break
        frm, to = rng.choice(moves)
        real = Move(board.piece_at(frm), frm, to, captured=board.piece_at(to))
        after = board.apply(real)
        found = detect_move(board, copy.deepcopy(after.colors()))
        assert found == real
        assert detect_move_from_pieces(board, after) == real
        checked += 1
        if real.captured in ("k", "K"):
            break
        board = after
    assert checked > 20
