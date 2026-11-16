"""
Найпростіший тест руху БЕЗ опитування позиції: лише MovL і пауза sleep.

Мета: з'ясувати, чи затримки перед стартом руху з'являються, коли ми НЕ питаємо контролер про позу.
Скрипт надсилає «вгору, вниз, вгору, вниз...» над однією клітинкою й після кожної команди просто чекає --pause секунд.
Дивіться на руку (краще зніміть відео з таймером) і порівняйте з часом у виводі:
  - якщо рука стартує одразу після кожної команди, затримку створювало опитування GetPose;
  - якщо затримка (~9 с) лишається, вона всередині контролера або прошивки.

  python tools/robot_raw.py e4 --live --speed 40 --pause 6 --repeat 4
Інші прапорці як у robot_test.py. Без --live лише показує, що зробив би.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xiangqi_robot import parse_square  # noqa: E402
from xiangqi_robot.arm import DobotMG400, RobotCalibration  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("square", help="клітинка, над якою рухаємось, наприклад e4")
    p.add_argument("--calib", default="robot_calib.json")
    p.add_argument("--live", action="store_true")
    p.add_argument("--ip", default="192.168.1.6")
    p.add_argument("--speed", type=int, default=10)
    p.add_argument("--pause", type=float, default=6.0, help="скільки секунд чекати після кожної команди")
    p.add_argument("--repeat", type=int, default=4, help="скільки разів «вгору-вниз»")
    args = p.parse_args()

    cal = RobotCalibration.load(args.calib)
    x, y = cal.square_xy(parse_square(args.square))
    plan = [("вгору", cal.z_safe), ("вниз", cal.z_board)] * args.repeat
    print(f"{args.square}: x={x:.1f} y={y:.1f}, z_safe={cal.z_safe}, z_board={cal.z_board}; "
          f"{len(plan)} команд, пауза {args.pause:.0f} с після кожної")
    if not args.live:
        print("Режим показу: рука НЕ рухається (додайте --live).")
        return
    input("УВАГА: рука рухатиметься. Зона вільна? Enter, щоб продовжити, Ctrl+C щоб скасувати. ")
    arm = DobotMG400(args.ip, speed_percent=args.speed, ready_timeout_s=0)
    try:
        t0 = time.time()
        for i, (name, z) in enumerate(plan, 1):
            print(f"[{time.time() - t0:6.1f} с] команда {i}/{len(plan)}: {name} (z={z})")
            arm.move_to(x, y, z, cal.r)
            time.sleep(args.pause)
        print(f"[{time.time() - t0:6.1f} с] готово")
    finally:
        arm.close()


if __name__ == "__main__":
    main()
