"""Перша перевірка зв'язку з MG400. Рука НЕ рухається і НЕ вмикається.

    python tools/robot_connect.py # IP за замовчуванням 192.168.1.6
    python tools/robot_connect.py --ip 192.168.1.6

Перед запуском:
  1) файл dobot_api.py з https://github.com/Dobot-Arm/TCP-IP-4Axis-Python лежить у корені проєкту;
  2) у DobotStudio Pro ввімкнено режим TCP/IP secondary development (Settings);
  3) ping 192.168.1.6 проходить, кабель у LAN1.

Скрипт перевіряє по черзі: порт 29999 відкритий -> dobot_api імпортується -> контролер відповідає
на ClearError -> читається поточна поза. Кожен крок друкує OK або що саме не так.
"""
import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def step(text: str) -> None:
    print(f"- {text} ... ", end="", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.1.6")
    args = ap.parse_args()

    step(f"порт {args.ip}:29999 відкритий")
    try:
        socket.create_connection((args.ip, 29999), timeout=3).close()
        print("OK")
    except OSError as err:
        print(f"НЕ ВИЙШЛО ({err}).\n  Перевірте ping, кабель у LAN1 і що DobotStudio не заблокував порт.")
        return 1

    step("імпорт dobot_api")
    try:
        from dobot_api import DobotApiDashboard  # type: ignore
        print("OK")
    except ImportError:
        print("НЕ ВИЙШЛО.\n  Покладіть dobot_api.py у корінь проєкту (посилання у верхньому описі).")
        return 1

    step("підключення до контролера")
    try:
        dash = DobotApiDashboard(args.ip, 29999)
        print("OK")
    except Exception as err:  # noqa: BLE001
        print(f"НЕ ВИЙШЛО ({err}).\n  Увімкніть TCP/IP secondary development у DobotStudio Pro.")
        return 1

    try:
        step("ClearError (скидає тривоги, руху немає)")
        print("OK ->", dash.ClearError())
        for name in ("RobotMode", "GetErrorID", "GetPose", "GetAngle"):
            if hasattr(dash, name):
                step(name)
                print("OK ->", getattr(dash, name)())
            else:
                print(f"- {name}: немає в цій версії dobot_api (нормально)")
    except Exception as err:  # noqa: BLE001
        print(f"НЕ ВИЙШЛО ({err})")
        return 1
    finally:
        for attr in ("close",):
            if hasattr(dash, attr):
                dash.close()

    print("\nГотово. Порівняйте поза з панеллю Control у DobotStudio: X, Y, Z, R мають збігатися.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
