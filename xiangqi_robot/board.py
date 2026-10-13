"""
Дошки сянці
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

ROWS, COLS = 10, 9
EMPTY = "."


NO_PIECE, RED, BLACK = 0, 1, 2

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

Square = Tuple[int, int]
FILES = "abcdefghi"


def color_of(piece: str) -> int:
    """
    Колір фігури: великі літери червоні, малі чорні
    """
    if piece == EMPTY:
        return NO_PIECE
    return RED if piece.isupper() else BLACK


def square_name(sq: Square) -> str:
    r, c = sq
    return f"{FILES[c]}{9 - r}"


def parse_square(name: str) -> Square:
    if len(name) != 2 or name[0] not in FILES or not name[1].isdigit():
        raise ValueError(f"Невірна назва клітинки: {name!r}")
    return 9 - int(name[1]), FILES.index(name[0])


@dataclass(frozen=True)
class Move:
    piece: str
    from_sq: Square
    to_sq: Square
    captured: str = EMPTY

    @property
    def is_capture(self) -> bool:
        return self.captured != EMPTY

    @property
    def uci(self) -> str:
        return square_name(self.from_sq) + square_name(self.to_sq)

    def __str__(self) -> str:
        sign = "x" if self.is_capture else "-"
        return f"{self.piece} {square_name(self.from_sq)}{sign}{square_name(self.to_sq)}"


class Board:
    """
    Позиція: сітка 10x9 літер фігур +чия черга ('w' червоні, 'b' чорні)
    """

    def __init__(self, grid: List[List[str]], side_to_move: str = "w"):
        if len(grid) != ROWS or any(len(row) != COLS for row in grid):
            raise ValueError("Дошка має бути 10 рядів x 9 стовпців")
        if side_to_move not in ("w", "b"):
            raise ValueError("side_to_move має бути 'w' або 'b'")
        self.grid = [list(row) for row in grid]
        self.side_to_move = side_to_move

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        parts = fen.split()
        ranks = parts[0].split("/")
        if len(ranks) != ROWS:
            raise ValueError(f"FEN має містити {ROWS} рядів, а не {len(ranks)}")
        grid = []
        for rank in ranks:
            row: List[str] = []
            for ch in rank:
                if ch.isdigit():
                    row.extend([EMPTY] * int(ch))
                elif ch in "rnbakcpRNBAKCP":
                    row.append(ch)
                else:
                    raise ValueError(f"Невідомий символ у FEN: {ch!r}")
            if len(row) != COLS:
                raise ValueError(f"Ряд {rank!r} має {len(row)} клітинок замість {COLS}")
            grid.append(row)
        side = parts[1] if len(parts) > 1 else "w"
        return cls(grid, side)

    @classmethod
    def start(cls) -> "Board":
        return cls.from_fen(START_FEN)

    def to_fen(self) -> str:
        ranks = []
        for row in self.grid:
            out, empty = "", 0
            for ch in row:
                if ch == EMPTY:
                    empty += 1
                else:
                    if empty:
                        out += str(empty)
                        empty = 0
                    out += ch
            if empty:
                out += str(empty)
            ranks.append(out)
        return "/".join(ranks) + f" {self.side_to_move} - - 0 1"

    def piece_at(self, sq: Square) -> str:
        return self.grid[sq[0]][sq[1]]

    def copy(self) -> "Board":
        return Board(self.grid, self.side_to_move)

    def colors(self) -> List[List[int]]:
        """
        Карта кольорів (0 порожньо, 1 червоні, 2 чорні)
        """
        return [[color_of(ch) for ch in row] for row in self.grid]

    def side_color(self) -> int:
        return RED if self.side_to_move == "w" else BLACK

    def apply(self, move: Move) -> "Board":
        """
        Нова позиція після ходу (без перевірки правил)
        """
        new = self.copy()
        (r1, c1), (r2, c2) = move.from_sq, move.to_sq
        new.grid[r2][c2] = new.grid[r1][c1]
        new.grid[r1][c1] = EMPTY
        new.side_to_move = "b" if self.side_to_move == "w" else "w"
        return new

    def __str__(self) -> str:
        lines = []
        for r, row in enumerate(self.grid):
            lines.append(f"{9 - r}  " + " ".join(row))
        lines.append("   " + " ".join(FILES))
        return "\n".join(lines)
