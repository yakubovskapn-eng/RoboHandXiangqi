"""Перевірки руки по сходинках

python tools/robot_test.py check
python tools/robot_test.py plan h2e2
python tools/robot_test.py plan b7b0 --capture
python tools/robot_test.py goto a9 i9 i0 a0 --live
python tools/robot_test.py goto e4 --live --down
python tools/robot_test.py plan h2e2 --live --hover
python tools/robot_test.py plan h2e2 --live
python tools/robot_test.py park --live
:
- check: перевірити robot_calib.json (числа й досяжність, без руху)
- plan h2e2: показати, що робитиме рука (без руху)
- plan b7b0 --capture: те саме для побиття
- goto a9 i9 i0 a0 --live: рука зависає над кутами (не опускається)
- goto e4 --live --down: рука опускається на клітинку (z_board)
- plan h2e2 --live --hover: весь хід у повітрі, на 1 мм нижче z_safe
- plan h2e2 --live: справжній хід з фігурою
- park --live: від'їхати в точку park (якщо вона є в robot_calib.json)


Усі справжні рухи (--live): зона вільна, рука біля перемикача POWER, швидкість 10 %.

robot_calib.json (мм, з панелі Control у DobotStudio; X вправо, Y уперед від руки):
  corners  - 4 кути a9, i9, i0, a0 (верхній лівий, верхній правий, нижній правий, нижній лівий)
  z_board  - висота Z, коли присоска торкається верху фігури
  lift     - на скільки мм вище за z_board рухається рука над фігурами (50). z_safe = z_board + lift;
             можна й задати z_safe числом, тоді lift не використовується
  discard  - X, Y місця, куди кладуться побиті фігури
  park     - X, Y місця, куди рука відїжджає після ходу, щоб камера бачила дошку (можна не вказувати)
  r        - кут R, який показує панель (не міняємо)
Шаблон: robot_calib.example.json.
"""
import argparse
import dataclasses
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xiangqi_robot import Move, parse_square  # noqa: E402
from xiangqi_robot.arm import DobotMG400, DryRunArm, Mover, RobotCalibration  # noqa: E402
from xiangqi_robot.board import COLS, ROWS  # noqa: E402

REACH_MIN, REACH_MAX = 150.0, 400.0


def load_calib(path: str) -> RobotCalibration:
    if not Path(path).exists():
        raise SystemExit(
            f"Немає файлу {path}. Скопіюйте robot_calib.example.json у {path} "
            "і впишіть свої координати (мм) з DobotStudio."
        )
    cal = RobotCalibration.load(path)
    if all(abs(c) < 1e-9 for pt in cal.corners for c in pt):
        raise SystemExit(f"У {path} усі кути нульові: впишіть справжні координати.")
    return cal


def report(cal: RobotCalibration) -> bool:
    """Друкує зведення й повертає True, якщо все виглядає правдоподібно."""
    ok = True
    radii = []
    for r in range(ROWS):
        for c in range(COLS):
            x, y = cal.square_xy((r, c))
            radii.append(math.hypot(x, y))
    dx = [math.dist(cal.corners[a], cal.corners[b]) for a, b in ((0, 1), (3, 2))]
    dy = [math.dist(cal.corners[a], cal.corners[b]) for a, b in ((0, 3), (1, 2))]
    print(f"Ширина дошки (a-i): {dx[0]:.0f} / {dx[1]:.0f} мм;  довжина (9-0): {dy[0]:.0f} / {dy[1]:.0f} мм")
    print(f"Радіус клітинок від основи: {min(radii):.0f} .. {max(radii):.0f} мм "
          f"(орієнтовна зона {REACH_MIN:.0f}..{REACH_MAX:.0f})")
    dr = math.hypot(*cal.discard)
    print(f"Місце скидання: {cal.discard}, радіус {dr:.0f} мм")
    if cal.park:
        print(f"Місце, куди рука відїжджає після ходу: {cal.park}, радіус {math.hypot(*cal.park):.0f} мм")
    print(f"z_board={cal.z_board}, z_safe={cal.z_safe}, підйом {cal.z_safe - cal.z_board:.0f} мм, r={cal.r}")
    if abs(dx[0] - dx[1]) > 5 or abs(dy[0] - dy[1]) > 5:
        print("УВАГА: протилежні сторони відрізняються більш ніж на 5 мм, перевірте кути й порядок a9, i9, i0, a0.")
        ok = False
    if max(dx + dy) > 450:
        print("УВАГА: сторона дошки понад 450 мм: перевірте, що числа в мм і кути не переплутані.")
        ok = False
    if max(radii) > REACH_MAX or min(radii) < REACH_MIN or not REACH_MIN <= dr <= REACH_MAX:
        print("УВАГА: частина точок може бути поза робочою зоною руки: перевірте через goto.")
        ok = False
    if not 20 <= cal.z_safe - cal.z_board <= 100:
        print("УВАГА: підйом над фігурою має бути приблизно 20-100 мм.")
        ok = False
    print("Висновок:", "виглядає правдоподібно" if ok else "є попередження, див. вище")
    return ok


def make_arm(args):
    if args.live:
        input("УВАГА: рука рухатиметься. Зона вільна, рука біля перемикача POWER? "
              "Enter, щоб продовжити, Ctrl+C щоб скасувати. ")
        arm = DobotMG400(args.ip, suction_do=args.suction_do, speed_percent=args.speed, tool_do=args.tool_do)
        if args.timing:
            _add_timing(arm)
        return arm
    print("Режим показу: рука НЕ рухається.")
    return DryRunArm()


def _add_timing(arm) -> None:
    """Друкує, скільки секунд забирає кожна дія руки: так видно, де йде час (відправка команди чи очікування)."""
    t_start = time.time()
    arm.trace = True
    for name in ("move_to", "wait", "suction"):
        orig = getattr(arm, name)

        def timed(*a, _orig=orig, _name=name, **kw):
            t0 = time.time()
            try:
                return _orig(*a, **kw)
            finally:
                print(f"[{time.time() - t_start:6.1f} с] {_name:8s} зайняв {time.time() - t0:5.2f} с")
        setattr(arm, name, timed)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s):
        s.add_argument("--calib", default="robot_calib.json")
        s.add_argument("--live", action="store_true", help="справді рухати руку (інакше лише показати)")
        s.add_argument("--ip", default="192.168.1.6")
        s.add_argument("--speed", type=int, default=10)
        s.add_argument("--suction-do", type=int, default=1)
        s.add_argument("--timing", action="store_true", help="друкувати, скільки часу забирає кожна дія руки")
        s.add_argument("--tool-do", action="store_true", help="присоска на виході інструмента (ToolDO), а не на DO контролера")

    c = sub.add_parser("check")
    c.add_argument("--calib", default="robot_calib.json")

    s = sub.add_parser("plan")
    s.add_argument("move", help="хід у UCI, наприклад h2e2")
    s.add_argument("--capture", action="store_true", help="це побиття")
    s.add_argument("--hover", action="store_true", help="не опускатись нижче z_safe - 1 мм (тест у повітрі)")
    s.add_argument("--repeat", type=int, default=1,
                   help="скільки ходів зробити В ОДНОМУ запуску (h2e2, потім e2h2 назад, і так далі): перевірка стабільності та часу")
    common(s)

    g = sub.add_parser("goto")
    g.add_argument("squares", nargs="+", help="клітинки, наприклад a9 i9 i0 a0")
    g.add_argument("--down", action="store_true", help="опускатись до z_board (за замовчуванням лише зависання)")
    common(g)

    common(sub.add_parser("park", help="відїхати в точку park з robot_calib.json (на висоті z_safe)"))

    args = p.parse_args()
    cal = load_calib(args.calib)

    if args.cmd == "check":
        sys.exit(0 if report(cal) else 1)

    report(cal)
    if args.cmd == "plan":
        if args.hover:
            cal = dataclasses.replace(cal, z_board=cal.z_safe - 1.0)
        mv = args.move
        forward = Move("?", parse_square(mv[:2]), parse_square(mv[2:4]), "x" if args.capture else ".")
        back = Move("?", parse_square(mv[2:4]), parse_square(mv[:2]), ".")
        arm = make_arm(args)
        try:
            mover = Mover(arm, cal)
            for i in range(max(1, args.repeat)):
                move = forward if i % 2 == 0 else back
                t0 = time.time()
                mover.play(move)
                print(f"== Хід {i + 1}/{args.repeat} ({'туди' if i % 2 == 0 else 'назад'}) зайняв {time.time() - t0:.1f} с")
        finally:
            arm.close()
    elif args.cmd == "park":
        if not cal.park:
            sys.exit("У robot_calib.json немає рядка \"park\": [x, y].")
        print(f"-> park: x={cal.park[0]:.1f} y={cal.park[1]:.1f} на висоті z_safe={cal.z_safe}")
        arm = make_arm(args)
        try:
            arm.move_to(cal.park[0], cal.park[1], cal.z_safe, cal.r)
            arm.wait()
        finally:
            arm.close()
    else:  # goto
        arm = make_arm(args)
        try:
            for name in args.squares:
                x, y = cal.square_xy(parse_square(name))
                print(f"-> {name}: x={x:.1f} y={y:.1f}")
                arm.move_to(x, y, cal.z_safe, cal.r)
                arm.wait()
                if args.down:
                    arm.move_to(x, y, cal.z_board, cal.r)
                    arm.wait()
                if args.live:
                    input("   Присоска над потрібним перетином? Enter, щоб піднятись і йти далі ")
                if args.down:
                    arm.move_to(x, y, cal.z_safe, cal.r)
                    arm.wait()
        finally:
            arm.close()


if __name__ == "__main__":
    main()
