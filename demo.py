"""
Демо: визначення ходу за двома станами дошки
"""
from xiangqi_robot import Board, Move, MoveDetectionError, detect_move, parse_square


def show(title, board):
    print(f"\n{title}\n{board}")


def main():
    board = Board.start()
    show("Початкова позиція (до ходу):", board)

    real = Move("C", parse_square("h2"), parse_square("e2"))
    after = board.apply(real)
    show("Після ходу (те, що бачить зір, лише кольори):", after)
    move = detect_move(board, after.colors())
    print(f"\nРозпізнано: {move}  (UCI: {move.uci}, взяття: {move.is_capture})")
    board = after

    after = board.apply(Move("n", parse_square("h9"), parse_square("g7")))
    move = detect_move(board, after.colors())
    print(f"Розпізнано: {move}  (UCI: {move.uci})")
    board = after

    capture = Move("C", parse_square("e2"), parse_square("e6"))
    after = board.apply(capture)
    move = detect_move(board, after.colors())
    print(f"Розпізнано: {move}  (UCI: {move.uci}, взяття: {move.is_capture})")

    broken = after.colors()
    broken[0][0] = 0
    try:
        detect_move(board, broken)
    except MoveDetectionError as err:
        print(f"\nПомилка (очікувана): {err}")

    print(f"\nFEN для рушія: {after.to_fen()}")


if __name__ == "__main__":
    main()
