"""
Тести підключення рушія і циклу партії.

За замовчуванням працюють з фейковим рушієм (tests/fake_engine.py), тож не потребують Pikafish.
test_real_pikafish запускається, лише якщо Pikafish знайдено (engines/ або PIKAFISH_PATH).
"""
import sys
from pathlib import Path

import pytest

from xiangqi_robot import (
    BLACK,
    RED,
    Board,
    EngineError,
    GameOver,
    MoveDetectionError,
    RobotMoveMismatch,
    UCIEngine,
    XiangqiGame,
    find_engine,
    parse_square,
)

FAKE = [sys.executable, str(Path(__file__).with_name("fake_engine.py"))]


@pytest.fixture(scope="module")
def engine():
    with UCIEngine(command=FAKE) as eng:
        yield eng


def test_engine_handshake_and_legal_moves(engine):
    assert engine.name == "FakeEngine"
    moves = engine.legal_moves()
    assert len(moves) == 44  # у початковій позиції сянці 44 ходи
    assert "h2e2" in moves and "b0c2" in moves


def test_best_move_is_legal(engine):
    move = engine.best_move(["h2e2"], depth=1)
    assert move in engine.legal_moves(["h2e2"])


def test_missing_engine_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("PIKAFISH_PATH", raising=False)
    with pytest.raises(EngineError, match="не знайдено"):
        find_engine(tmp_path / "nope")


def test_dead_engine_gives_error():
    with pytest.raises(EngineError):
        UCIEngine(command=[sys.executable, "-c", "print('id name broken')"], timeout=3)


def test_human_then_robot_turn(engine):
    game = XiangqiGame(engine, robot_color=BLACK, depth=1)
    assert not game.robot_to_move

    after = game.board.apply(game.board.move_from_uci("h2e2")).colors()
    human = game.human_move(after)
    assert human.uci == "h2e2"
    assert game.robot_to_move

    robot = game.plan_robot_move()
    assert game.history == ["h2e2"]           # план ще не змінює стан
    game.confirm_robot_move(robot, game.expected_colors_after(robot))
    assert game.history == ["h2e2", robot.uci]
    assert not game.robot_to_move


def test_robot_plays_first_as_red(engine):
    game = XiangqiGame(engine, robot_color=RED, depth=1)
    assert game.robot_to_move
    game.confirm_robot_move(game.plan_robot_move())
    assert not game.robot_to_move


def test_human_move_exposing_flying_general_is_rejected(engine):
    # Червона тура на e1 закриває генералів. За rules.py тура може піти вбік,
    # але тоді генерали «дивляться» один на одного - хід нелегальний.
    fen = "4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1"
    game = XiangqiGame(engine, robot_color=BLACK, start_fen=fen)
    after = game.board.apply(game.board.move_from_uci("e1a1")).colors()
    with pytest.raises(MoveDetectionError, match="нелегальний"):
        game.human_move(after)
    assert game.history == []                  # стан не зіпсовано
    game.human_move_uci("e1e8")                # а вздовж вертикалі можна


def test_robot_mismatch_reports_squares(engine):
    game = XiangqiGame(engine, robot_color=RED, depth=1)
    move = game.plan_robot_move()
    wrong = game.board.colors()                 # рука нічого не зробила
    with pytest.raises(RobotMoveMismatch) as info:
        game.confirm_robot_move(move, wrong)
    assert set(info.value.wrong_squares) == {move.from_sq, move.to_sq}
    assert game.robot_to_move                    # хід не зараховано


def test_checkmate_detected(engine):
    # Чорний генерал d9 під шахом від тури d0, на e9 не можна - «літаючий генерал»
    fen = "3k5/9/9/9/9/9/9/9/9/3RK4 b - - 0 1"
    game = XiangqiGame(engine, robot_color=BLACK, start_fen=fen)
    assert game.is_over and game.winner == RED
    with pytest.raises(GameOver):
        game.plan_robot_move()


def test_wrong_side_and_undo(engine):
    game = XiangqiGame(engine, robot_color=BLACK, depth=1)
    with pytest.raises(MoveDetectionError, match="ходять"):
        game.human_move_uci("h7e7")
    game.human_move_uci("h2e2")
    assert game.undo().uci == "h2e2"
    assert game.board.grid == Board.start().grid and game.history == []


def test_full_game_loop(engine):
    """
    Імітація: «людину» теж грає рушій, камера ідеальна. Партія не ламається.
    """
    game = XiangqiGame(engine, robot_color=BLACK, depth=1)
    for _ in range(60):
        if game.is_over:
            break
        if game.robot_to_move:
            move = game.plan_robot_move()
            game.confirm_robot_move(move, game.expected_colors_after(move))
        else:
            uci = engine.best_move(game.history, depth=1)
            colors = game.board.apply(game.board.move_from_uci(uci)).colors()
            game.human_move(colors)
    assert len(game.history) > 10


def test_real_pikafish():
    try:
        find_engine()
    except EngineError:
        pytest.skip("Pikafish не встановлено (engines/ або PIKAFISH_PATH)")
    with UCIEngine() as eng:
        assert len(eng.legal_moves()) == 44
        game = XiangqiGame(eng, robot_color=BLACK, movetime_ms=200)
        game.human_move_uci("h2e2")
        move = game.plan_robot_move()
        assert move.uci in game.legal_moves()
        assert parse_square(move.uci[:2]) == move.from_sq
