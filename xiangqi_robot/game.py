"""
Партія людина проти робота: стан дошки + історія ходів + рушій

Цикл гри (див. play.py):

    game = XiangqiGame(engine, robot_color=BLACK)
    while not game.is_over:
        if game.robot_to_move:
            move = game.plan_robot_move()          # рушій вирішує
            arm.execute(move)                       # рука переставляє фігуру
            game.confirm_robot_move(move, camera.read_colors())  # камера перевіряє
        else:
            wait_for_human()
            game.human_move(camera.read_colors())  # detect_move + перевірка рушієм

Перевірка ходу людини двоступенева:
  1) detect_move (move_detection.py) - зміни на дошці схожі на один хід,
     правильний колір, фігура так ходить (rules.py);
  2) рушій (go perft 1) - хід повністю легальний: не залишає свого генерала
     під шахом, не відкриває «літаючого генерала» тощо. Цього rules.py не перевіряє.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from .board import BLACK, RED, START_FEN, Board, Move, Square, square_name
from .engine import UCIEngine
from .move_detection import MoveDetectionError, detect_move, diff_colors


class GameOver(Exception):
    """
    Партія закінчилась: у сторони, що ходить, немає легальних ходів
    """

    def __init__(self, winner: int):
        self.winner = winner
        super().__init__(f"Партію завершено, перемогли {side_name(winner)}")


class RobotMoveMismatch(MoveDetectionError):
    """
    Після ходу руки камера бачить не ту позицію, яку очікували
    """

    def __init__(self, move: Move, wrong: List[Square]):
        self.move = move
        self.wrong_squares = wrong
        names = ", ".join(square_name(sq) for sq in wrong)
        super().__init__(f"Рука мала зробити {move.uci}, але не збігаються клітинки: {names}")


def side_name(color: int) -> str:
    return "червоні" if color == RED else "чорні"


class XiangqiGame:
    def __init__(
        self,
        engine: UCIEngine,
        robot_color: int = BLACK,
        start_fen: str = START_FEN,
        movetime_ms: Optional[int] = 1000,
        depth: Optional[int] = None,
    ):
        """
        robot_color - яким кольором грає рука (у сянці першими ходять червоні)
        movetime_ms / depth - сила гри, див. UCIEngine.best_move
        """
        if robot_color not in (RED, BLACK):
            raise ValueError("robot_color має бути RED або BLACK")
        self.engine = engine
        self.robot_color = robot_color
        self.start_fen = start_fen
        self.movetime_ms = movetime_ms
        self.depth = depth

        self.board = Board.from_fen(start_fen)
        self.history: List[str] = []  # UCI-ходи від start_fen, передаються рушію
        self.moves: List[Move] = []   # ті самі ходи з інформацією про фігури
        self.winner: Optional[int] = None
        self._legal: Optional[List[str]] = None

        engine.new_game()
        self._update_game_over()

    # ---------- стан ----------

    @property
    def side_to_move(self) -> int:
        return self.board.side_color()

    @property
    def robot_to_move(self) -> bool:
        return self.side_to_move == self.robot_color

    @property
    def is_over(self) -> bool:
        return self.winner is not None

    def legal_moves(self) -> List[str]:
        if self._legal is None:
            self._legal = self.engine.legal_moves(self.history, fen=self.start_fen)
        return self._legal

    def _update_game_over(self) -> None:
        # У сянці немає нічиєї через пат: хто не може ходити, той програв
        if not self.legal_moves():
            self.winner = RED if self.side_to_move == BLACK else BLACK

    def _push(self, move: Move) -> None:
        self.board = self.board.apply(move)
        self.history.append(move.uci)
        self.moves.append(move)
        self._legal = None
        self._update_game_over()

    def _require(self, robot: bool) -> None:
        if self.is_over:
            raise GameOver(self.winner)  # type: ignore[arg-type]
        if robot != self.robot_to_move:
            who = "руки" if self.robot_to_move else "людини"
            raise RuntimeError(f"Зараз черга {who}")

    # ---------- хід людини ----------

    def human_move(self, after_colors: Sequence[Sequence[int]]) -> Move:
        """
        Карта кольорів з камери (10x9: 0 порожньо, 1 червоні, 2 чорні) -> хід людини.
        Кидає MoveDetectionError, якщо хід не розпізнано або він нелегальний;
        стан партії тоді не змінюється, можна попросити людину виправити і зняти кадр ще раз.
        """
        self._require(robot=False)
        move = detect_move(self.board, after_colors)
        return self._accept_human(move)

    def human_move_uci(self, uci: str) -> Move:
        """
        Те саме, але хід введено текстом (ручний режим без камери, налагодження)
        """
        self._require(robot=False)
        try:
            move = self.board.move_from_uci(uci)
        except ValueError as err:
            raise MoveDetectionError(str(err)) from err
        if move.piece.isupper() != (self.side_to_move == RED):
            raise MoveDetectionError(f"Зараз ходять {side_name(self.side_to_move)}")
        return self._accept_human(move)

    def _accept_human(self, move: Move) -> Move:
        if move.uci not in self.legal_moves():
            raise MoveDetectionError(
                f"Хід {move.uci} нелегальний: генерал залишається під шахом "
                "або фігура так не ходить"
            )
        self._push(move)
        return move

    # ---------- хід руки ----------

    def plan_robot_move(self) -> Move:
        """
        Питає рушій, який хід зробити. Стан партії ще НЕ змінюється:
        спочатку рука виконує хід, потім confirm_robot_move.
        """
        self._require(robot=True)
        uci = self.engine.best_move(
            self.history, fen=self.start_fen, movetime_ms=self.movetime_ms, depth=self.depth
        )
        if uci is None:  # не має статися: кінець гри ловиться раніше
            self._update_game_over()
            raise GameOver(self.winner if self.winner is not None else 3 - self.robot_color)
        if uci not in self.legal_moves():
            raise RuntimeError(f"Рушій запропонував нелегальний хід {uci}")
        return self.board.move_from_uci(uci)

    def expected_colors_after(self, move: Move) -> List[List[int]]:
        """
        Яку карту кольорів має побачити камера після виконання ходу
        """
        return self.board.apply(move).colors()

    def confirm_robot_move(
        self, move: Move, after_colors: Optional[Sequence[Sequence[int]]] = None
    ) -> None:
        """
        Зарахувати хід руки. Якщо передано кадр камери, спершу звіряє його з очікуваним;
        при розбіжності кидає RobotMoveMismatch (у ньому список клітинок, які треба поправити).
        """
        self._require(robot=True)
        if after_colors is not None:
            wrong = [sq for sq, _, _ in diff_colors(self.expected_colors_after(move), after_colors)]
            if wrong:
                raise RobotMoveMismatch(move, wrong)
        self._push(move)

    # ---------- інше ----------

    def undo(self) -> Move:
        """
        Скасувати останній хід (наприклад, якщо розпізнали неправильно)
        """
        if not self.moves:
            raise RuntimeError("Немає ходів для скасування")
        last = self.moves.pop()
        self.history.pop()
        board = Board.from_fen(self.start_fen)
        for m in self.moves:
            board = board.apply(m)
        self.board = board
        self.winner = None
        self._legal = None
        self._update_game_over()
        return last
