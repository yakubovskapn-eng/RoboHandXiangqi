"""
Мінімальний UCI-рушій на Python для тестів (щоб тести працювали без Pikafish,
на будь-якій ОС і в CI). Грає слабко: бере фігуру, якщо може, інакше перший хід.

Розуміє: uci, isready, setoption, ucinewgame, position fen ... moves ...,
go perft 1, go depth N / go movetime N, quit.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xiangqi_robot.board import START_FEN, Board  # noqa: E402
from xiangqi_robot.rules import pseudo_legal_moves  # noqa: E402


def legal_moves(board):
    result = []
    for frm, to in pseudo_legal_moves(board):
        move = board.move_from_uci(_uci(frm, to))
        after = board.apply(move)
        # Хід нелегальний, якщо суперник після нього може взяти нашого генерала
        # (сюди ж входить «літаючий генерал»: у rules.py генерал б'є генерала по вертикалі)
        king = "K" if board.side_to_move == "w" else "k"
        if not any(after.piece_at(t) == king for _, t in pseudo_legal_moves(after)):
            result.append(move)
    return result


def _uci(frm, to):
    from xiangqi_robot.board import square_name
    return square_name(frm) + square_name(to)


def main():
    board = Board.from_fen(START_FEN)
    for raw in sys.stdin:
        tokens = raw.split()
        if not tokens:
            continue
        cmd = tokens[0]
        if cmd == "uci":
            print("id name FakeEngine")
            print("uciok", flush=True)
        elif cmd == "isready":
            print("readyok", flush=True)
        elif cmd == "position":
            if tokens[1] == "startpos":
                fen, rest = START_FEN, tokens[2:]
            else:
                end = tokens.index("moves") if "moves" in tokens else len(tokens)
                fen, rest = " ".join(tokens[2:end]), tokens[end:]
            board = Board.from_fen(fen)
            for uci in rest[1:]:
                board = board.apply(board.move_from_uci(uci))
        elif cmd == "go" and len(tokens) > 1 and tokens[1] == "perft":
            moves = legal_moves(board)
            for m in moves:
                print(f"{m.uci}: 1")
            print(f"\nNodes searched: {len(moves)}\n", flush=True)
        elif cmd == "go":
            moves = legal_moves(board)
            if not moves:
                print("bestmove (none)", flush=True)
            else:
                captures = [m for m in moves if m.is_capture]
                best = (captures or moves)[0]
                print("info depth 1 score cp 0 pv " + best.uci)
                print(f"bestmove {best.uci}", flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()
