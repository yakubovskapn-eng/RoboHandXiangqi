"""
Визначення ходу за двома станами дошки до і після

Вхід:
  1) карта кольорів 10x9 (0,1,2)
  2) повна сітка фігур (літери), коли класифікатор розпізнає тип фігури.
"""
from __future__ import annotations
from typing import List, Sequence, Tuple
from .board import BLACK, COLS, EMPTY, NO_PIECE, RED, ROWS, Board, Move, Square, color_of, square_name
from .rules import is_valid_move


class MoveDetectionError(ValueError):
    """
    Хід не вдалося визначити хибне розпізнавання, рука в кадрі, кілька змін
    """


Change = Tuple[Square, int, int]#клітинка, колір до, після


def _check_shape(grid: Sequence[Sequence], name: str) -> None:
    if len(grid) != ROWS or any(len(row) != COLS for row in grid):
        raise MoveDetectionError(f"{name}: очікується {ROWS}x{COLS}")


def diff_colors(before: Sequence[Sequence[int]], after: Sequence[Sequence[int]]) -> List[Change]:
    """
    Список клітинок, на яких колір змінився
    """
    _check_shape(before, "before")
    _check_shape(after, "after")
    return [
        ((r, c), before[r][c], after[r][c])
        for r in range(ROWS)
        for c in range(COLS)
        if before[r][c] != after[r][c]
    ]


def detect_squares(
    before: Sequence[Sequence[int]], after: Sequence[Sequence[int]]
) -> Tuple[Square, Square, bool]:
    """
    Знаходить (звідки, куди, чи було взяття) за двома картами кольорів
    """
    changes = diff_colors(before, after)

    if not changes:
        raise MoveDetectionError("Дошка не змінилася: ходу немає")

    if len(changes) == 1:
        sq, was, now = changes[0]
        if now == NO_PIECE:
            raise MoveDetectionError(
                f"Змінилася лише клітинка {square_name(sq)}, фігура зникла. "
                "Це може бути взяття, але без кольору фігур його не відрізнити від "
                "знятої з дошки фігури. Потрібна карта кольорів."
            )
        raise MoveDetectionError(
            f"Змінилася лише клітинка {square_name(sq)}: з'явилась нова фігура"
        )

    if len(changes) > 2:
        names = ", ".join(square_name(sq) for sq, _, _ in changes)
        raise MoveDetectionError(
            f"Забагато змін ({len(changes)}): {names}. Рука в кадрі, збій освітлення або кілька ходів"
        )

    sources = [ch for ch in changes if ch[1] != NO_PIECE and ch[2] == NO_PIECE]
    targets = [ch for ch in changes if ch[2] != NO_PIECE and ch[1] != ch[2]]
    if len(sources) != 1 or len(targets) != 1:
        raise MoveDetectionError("Зміни не схожі на один хід (одна клітинка звільнилась, одна зайнялась)")

    (frm, mover, _), (to, was_there, now_there) = sources[0], targets[0]
    if now_there != mover:
        raise MoveDetectionError(
            f"Колір фігури на {square_name(to)} не збігається з кольором фігури, що пішла"
        )
    return frm, to, was_there != NO_PIECE


def detect_move(board: Board, after_colors: Sequence[Sequence[int]], check_rules: bool = True) -> Move:
    """
    Хід, що перевів 'board' у стан 'after_colors'

    check_rules=True додатково перевіряє, що фігура так може піти за правилами,
    і що ходить правильна сторона
    """
    before_colors = board.colors()
    frm, to, is_capture = detect_squares(before_colors, after_colors)

    mover = before_colors[frm[0]][frm[1]]
    if mover != board.side_color():
        who = "червоних" if board.side_color() == RED else "чорних"
        raise MoveDetectionError(f"Зараз черга {who}, а пішла фігура іншого кольору")

    if check_rules and not is_valid_move(board, frm, to):
        piece = board.piece_at(frm)
        raise MoveDetectionError(
            f"Хід {square_name(frm)}{square_name(to)} фігурою {piece} суперечить правилам"
        )

    return Move(piece=board.piece_at(frm), from_sq=frm, to_sq=to, captured=board.piece_at(to))


def detect_move_from_pieces(before: Board, after: Board, check_rules: bool = True) -> Move:
    """
    Те саме, але cv повернув повну сітку фігур (типи розпізнано).\

    Додатково перевіряється, що на клітинці призначення стоїть саме та фігура, яка пішла.
    """
    move = detect_move(before, after.colors(), check_rules=check_rules)
    arrived = after.piece_at(move.to_sq)
    if arrived != move.piece:
        raise MoveDetectionError(
            f"На {square_name(move.to_sq)} розпізнано {arrived}, а пішла {move.piece}: помилка класифікації"
        )
    return move
