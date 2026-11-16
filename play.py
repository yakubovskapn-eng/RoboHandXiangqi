"""
Гра людина проти робота.

Запуск:
    python play.py                       # ручний режим: ходи людини вводяться текстом (h2e2)
    python play.py --robot red --depth 4 # рука грає червоними, послаблений рушій
    python play.py --camera              # хід людини читається з камери (потрібні corners.json і calibration.json)
    python play.py --arm dry             # показати, що робитиме рука, без руху (потрібен robot_calib.json)
    python play.py --arm live --speed 10 # справжній рух MG400 (спершу перевірте tools/robot_test.py)

Точки підключення інших модулів:
    read_colors()    - камера (xiangqi_robot/camera.py): карта 10x9 (0 порожньо, 1 червоні, 2 чорні)
    execute_move()   - рука Dobot MG400: фізично виконує хід (див. xiangqi_robot/arm.py)
"""
import argparse
import sys
from pathlib import Path

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
from xiangqi_robot.arm import DobotMG400, DryRunArm, Mover, RobotCalibration

MOVER = None  # заповнюється в main(), якщо задано --arm dry/live


CAMERA = None  # заповнюється в main(), якщо задано --camera


def read_colors():
    """Знімає дошку камерою й повертає карту 10x9 (0 порожньо, 1 червоні, 2 чорні)."""
    return CAMERA.read_colors()


def execute_move(move):
    """
    Рука Dobot MG400 фізично виконує хід. Якщо це взяття, Mover спершу прибирає побиту фігуру.
    Без --arm лише друкує, що мала б зробити рука (як раніше).
    """
    print(f"   [рука] {move}  ({'взяття, спершу прибрати фігуру' if move.is_capture else 'тихий хід'})")
    if MOVER is not None:
        MOVER.play(move)


def human_turn(game, use_camera):
    while True:
        if use_camera:
            from xiangqi_robot.camera import wait_stable
            print("Чекаю ваш хід (камера стежить сама, Enter не потрібен)...")
            return wait_stable(read_colors, game.human_move, MoveDetectionError, ignore=game.board.colors(),
                               on_error=lambda e: print(f"   {e}. Поправте фігури, камера дивиться далі..."))
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
    execute_move(move)          # рука ходить один раз; при розбіжності повторюється лише перевірка камерою
    if not use_camera:
        game.confirm_robot_move(move)
        return move
    from xiangqi_robot.camera import wait_stable
    while True:
        try:   # камера дивиться, доки позиція не стане такою, як після ходу руки (до 15 с)
            wait_stable(read_colors, lambda colors: game.confirm_robot_move(move, colors), RobotMoveMismatch,
                        timeout=15, on_error=lambda e: None)
            return move
        except RobotMoveMismatch as err:
            print(f"   {err}")
            input("   Поправте фігури вручну і натисніть Enter, камера перевірить ще раз...")


def main():
    p = argparse.ArgumentParser(description="Сянці: людина проти Dobot MG400")
    p.add_argument("--robot", choices=["red", "black"], default="black", help="колір руки")
    p.add_argument("--depth", type=int, help="глибина пошуку (3-6 слабше, для людини)")
    p.add_argument("--movetime", type=int, default=1000, help="час на хід у мс, якщо не задано --depth")
    p.add_argument("--camera", action="store_true", help="читати хід людини з камери")
    p.add_argument("--camera-config", default="camera_settings.json", help="камера, розмір кадру й експозиція")
    p.add_argument("--corners", default="corners.json", help="кути дошки на кадрі (camera_test.py corners)")
    p.add_argument("--vision-calib", default="calibration.json", help="пороги розпізнавання (camera_test.py check)")
    p.add_argument("--engine", help="шлях до рушія (інакше engines/ або PIKAFISH_PATH)")
    p.add_argument("--arm", choices=["off", "dry", "live"], default="off",
                   help="off: рука не підключена; dry: лише показати рухи; live: справжня MG400")
    p.add_argument("--calib", default="robot_calib.json", help="координати дошки в системі робота")
    p.add_argument("--ip", default="192.168.1.6", help="IP контролера MG400")
    p.add_argument("--speed", type=int, default=10, help="швидкість руки, %% (для початку 10)")
    p.add_argument("--suction-do", type=int, default=1, help="номер виходу присоски")
    p.add_argument("--tool-do", action="store_true", help="присоска на виході інструмента (ToolDO)")
    args = p.parse_args()

    global MOVER, CAMERA
    if args.camera:
        from xiangqi_robot.camera import BoardCamera, load_settings
        CAMERA = BoardCamera(load_settings(args.camera_config), args.corners, args.vision_calib)
    arm = None
    if args.arm != "off":
        if not Path(args.calib).exists():
            sys.exit(f"Немає файлу {args.calib}. Скопіюйте robot_calib.example.json у {args.calib} "
                     "і впишіть координати з DobotStudio.")
        calib = RobotCalibration.load(args.calib)
        if args.arm == "live":
            input("УВАГА: рука рухатиметься. Зона вільна, рука біля перемикача POWER? "
                  "Enter, щоб продовжити, Ctrl+C щоб скасувати. ")
            arm = DobotMG400(args.ip, suction_do=args.suction_do, speed_percent=args.speed, tool_do=args.tool_do)
        else:
            arm = DryRunArm()
        MOVER = Mover(arm, calib)

    try:
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
    finally:
        if CAMERA is not None:
            CAMERA.close()
        if arm is not None:
            arm.close()  # лише закрити зв'язок; руку НЕ вимикаємо (вимкніть самі в DobotStudio)


if __name__ == "__main__":
    main()
