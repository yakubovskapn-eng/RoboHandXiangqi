"""
Правила руху фігур сянці
"""
from __future__ import annotations
from typing import Iterator, Tuple
from .board import COLS, EMPTY, ROWS, Board, Square, color_of


def _in_board(sq: Square) -> bool:
    return 0 <= sq[0] < ROWS and 0 <= sq[1] < COLS


def _in_palace(sq: Square, red: bool) -> bool:
    r, c = sq
    rows = range(7, 10) if red else range(0, 3)
    return 3 <= c <= 5 and r in rows


def _count_between(board: Board, a: Square, b: Square) -> int:
    """
    Кількість фігур строго між двома клітинками на одній лінії
    """
    (r1, c1), (r2, c2) = a, b
    if r1 == r2:
        step = 1 if c2 > c1 else -1
        return sum(1 for c in range(c1 + step, c2, step) if board.grid[r1][c] != EMPTY)
    if c1 == c2:
        step = 1 if r2 > r1 else -1
        return sum(1 for r in range(r1 + step, r2, step) if board.grid[r][c1] != EMPTY)
    raise ValueError("Клітинки не на одній лінії")


def is_valid_move(board: Board, frm: Square, to: Square) -> bool:
    if not (_in_board(frm) and _in_board(to)) or frm == to:
        return False
    piece = board.piece_at(frm)
    if piece == EMPTY:
        return False
    target = board.piece_at(to)
    if target != EMPTY and color_of(target) == color_of(piece):
        return False

    red = piece.isupper()
    kind = piece.upper()
    (r1, c1), (r2, c2) = frm, to
    dr, dc = r2 - r1, c2 - c1

    if kind == "K":
        # «Літаючий генерал»: генерал бере генерала по відкритій вертикалі
        if target != EMPTY and target.upper() == "K" and c1 == c2:
            return _count_between(board, frm, to) == 0
        return abs(dr) + abs(dc) == 1 and _in_palace(to, red)

    if kind == "A":
        return abs(dr) == 1 and abs(dc) == 1 and _in_palace(to, red)

    if kind == "B":  # слон: 2 по діагоналі, "око" вільне, не переходить річку
        if abs(dr) != 2 or abs(dc) != 2:
            return False
        if board.grid[r1 + dr // 2][c1 + dc // 2] != EMPTY:
            return False
        return r2 >= 5 if red else r2 <= 4

    if kind == "N":  # кінь: Г-подібний хід, "нога" вільна
        if (abs(dr), abs(dc)) == (2, 1):
            leg = (r1 + dr // 2, c1)
        elif (abs(dr), abs(dc)) == (1, 2):
            leg = (r1, c1 + dc // 2)
        else:
            return False
        return board.piece_at(leg) == EMPTY

    if kind == "R":
        return (dr == 0 or dc == 0) and _count_between(board, frm, to) == 0

    if kind == "C":  # гармата: ходить як тура, б'є через рівно одну фігуру-екран
        if not (dr == 0 or dc == 0):
            return False
        between = _count_between(board, frm, to)
        return between == 0 if target == EMPTY else between == 1

    if kind == "P":  # пішак: вперед; після річки ще й убік
        forward = -1 if red else 1
        crossed = r1 <= 4 if red else r1 >= 5
        if dr == forward and dc == 0:
            return True
        return crossed and dr == 0 and abs(dc) == 1

    return False


def pseudo_legal_moves(board: Board) -> Iterator[Tuple[Square, Square]]:
    """
    Усі ходи сторони
    """
    side = board.side_color()
    for r in range(ROWS):
        for c in range(COLS):
            piece = board.grid[r][c]
            if piece == EMPTY or color_of(piece) != side:
                continue
            for r2 in range(ROWS):
                for c2 in range(COLS):
                    if is_valid_move(board, (r, c), (r2, c2)):
                        yield (r, c), (r2, c2)
