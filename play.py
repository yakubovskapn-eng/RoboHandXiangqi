"""
Гра людина проти робота.

Запуск:
    python play.py                       # ручний режим: ходи людини вводяться текстом (h2e2)
    python play.py --robot red --depth 4 # рука грає червоними, послаблений рушій
    python play.py --camera              # хід людини читається з камери (коли буде готовий модуль)

Точки підключення інших модулів:
    read_colors()    - камера (cv2): повертає карту 10x9 (0 порожньо, 1 червоні, 2 чорні)
    execute_move()   - рука Dobot MG400: фізично виконує хід
"""
import argparse
import sys

from xiangqi_robot import (
    BLACK,
    RED,
    EngineError,
    GameOver,
    MoveDetectionError,
    RobotMoveMismatch,
    UCIEngine,
    XiangqiGame,
    side_name,
)


def read_colors():
    """
    TODO: підключити модуль камери (cv2), коли його буде закомічено.
    Має повернути список 10 рядів по 9 чисел; ряд 0 - бік чорних (9-та горизонталь).
    """
    raise NotImplementedError("Модуль камери ще не підключено, запускайте без --camera")


def execute_move(move):
    """
    TODO: підключити керування Dobot MG400.
    Якщо move.is_capture - спершу прибрати фігуру з move.to_sq, потім перенести move.from_sq -> move.to_sq.
    """
    print(f"   [рука] {move}  ({'взяття, спершу прибрати фігуру' if move.is_capture else 'тихий хід'})")


def human_turn(game, use_camera):
    while True:
        if use_camera:
            input("Зробіть хід і натисніть Enter...")
            try:
                return game.human_move(read_colors())
            except MoveDetectionError as err:
                print(f"   Не вдалося розпізнати хід: {err}\n   Поправте фігури й спробуйте ще раз.")
        else:
            text = input("Ваш хід (наприклад h2e2; undo - скасувати; quit - вийти): ").strip()
            if text == "quit":
                sys.exit(0)
            if text == "undo":
                # скасувати хід руки і свій попередній
                for _ in range(2 if len(game.history) >= 2 else len(game.history)):
                    game.undo()
                print(game.board)
                continue
            try:
                return game.human_move_uci(text)
            except MoveDetectionError as err:
                print(f"   {err}")


def robot_turn(game, use_camera):
    move = game.plan_robot_move()
    print(f"Рука ходить: {move.uci}")
    while True:
        execute_move(move)
        try:
            game.confirm_robot_move(move, read_colors() if use_camera else None)
            return move
        except RobotMoveMismatch as err:
            print(f"   {err}")
            input("   Поправте фігури вручну і натисніть Enter для повторної перевірки...")


def main():
    p = argparse.ArgumentParser(description="Сянці: людина проти Dobot MG400")
    p.add_argument("--robot", choices=["red", "black"], default="black", help="колір руки")
    p.add_argument("--depth", type=int, help="глибина пошуку (3-6 слабше, для людини)")
    p.add_argument("--movetime", type=int, default=1000, help="час на хід у мс, якщо не задано --depth")
    p.add_argument("--camera", action="store_true", help="читати хід людини з камери")
    p.add_argument("--engine", help="шлях до рушія (інакше engines/ або PIKAFISH_PATH)")
    args = p.parse_args()

    try:
        engine = UCIEngine(path=args.engine)
    except EngineError as err:
        print(err)
        sys.exit(1)

    with engine:
        print(f"Рушій: {engine.name}")
        game = XiangqiGame(
            engine,
            robot_color=RED if args.robot == "red" else BLACK,
            movetime_ms=args.movetime,
            depth=args.depth,
        )
        try:
            while not game.is_over:
                print(f"\n{game.board}\nХодять {side_name(game.side_to_move)}")
                if game.robot_to_move:
                    robot_turn(game, args.camera)
                else:
                    human_turn(game, args.camera)
        except GameOver:
            pass
        print(f"\n{game.board}\nКінець партії: перемогли {side_name(game.winner)}")
        print("Ходи:", " ".join(game.history))


if __name__ == "__main__":
    main()
