"""
Керування рукою:
клітинка шахівниці -> координати робота -> підняти й поставити фігуру.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import re
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .board import COLS, ROWS, Move, Square

XYZ = Tuple[float, float, float]

# 1. Калібрування: клітинка (row, col) -> (x, y) у координатах робота, мм
@dataclass
class RobotCalibration:
    """
    Чотири кути ігрового поля в координатах робота (мм).
    Порядок такий самий, як у vision: a9, i9, i0, a0, тобто верхній лівий,
    верхній правий, нижній правий, нижній лівий перетини (верх = бік чорних).
    """
    corners: List[Tuple[float, float]]# 4 точки (x, y)
    z_board: float # висота, на якій присоска торкається верху фігури
    discard: Tuple[float, float] # куди класти побиті фігури (поза дошкою)
    z_safe: Optional[float] = None # висота руху над фігурами; не задано = z_board + lift
    r: float = 0.0 # кут повороту
    lift: float = 50.0 # на скільки мм z_safe вище за z_board, якщо z_safe не задано
    park: Optional[Tuple[float, float]] = None # куди відїжджати після ходу, щоб не затуляти дошку камері (x, y на z_safe)

    def __post_init__(self) -> None:
        if len(self.corners) != 4:
            raise ValueError("Потрібно рівно 4 кути")
        if self.z_safe is None:
            self.z_safe = self.z_board + self.lift
        if self.z_safe <= self.z_board:
            raise ValueError("z_safe має бути вищим за z_board")

    def square_xy(self, sq: Square) -> Tuple[float, float]:
        """
        Білінійна інтерполяція між кутами
        """
        row, col = sq
        if not (0 <= row < ROWS and 0 <= col < COLS):
            raise ValueError(f"Клітинка поза дошкою: {sq}")
        u = col / (COLS - 1) # 0 ліворуч .. 1 праворуч
        v = row / (ROWS - 1) # 0 угорі (чорні) .. 1 унизу (червоні)
        (x00, y00), (x10, y10), (x11, y11), (x01, y01) = self.corners
        x = (1 - u) * (1 - v) * x00 + u * (1 - v) * x10 + u * v * x11 + (1 - u) * v * x01
        y = (1 - u) * (1 - v) * y00 + u * (1 - v) * y10 + u * v * y11 + (1 - u) * v * y01
        return x, y

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, path: str) -> "RobotCalibration":
        d = json.loads(Path(path).read_text())
        d["corners"] = [tuple(p) for p in d["corners"]]
        d["discard"] = tuple(d["discard"])
        if d.get("park"):
            d["park"] = tuple(d["park"])
        return cls(**d)

# 2. Інтерфейс руки й реалізації
class Arm:
    """
    Усе, що потрібно від руки для гри. Три дії
    """

    def move_to(self, x: float, y: float, z: float, r: float = 0.0) -> None:
        raise NotImplementedError

    def suction(self, on: bool) -> None:
        raise NotImplementedError

    def wait(self) -> None:
        """Дочекатися кінця всіх поставлених рухів."""

    def close(self, disable: bool = False) -> None:
        """Закрити з'єднання (disable=True ще й вимкнути руку, лише якщо вона в безпечному положенні)."""


@dataclass
class DryRunArm(Arm):
    """Нічого не рухає: записує дії. Для тестів."""
    verbose: bool = True
    log: List[Tuple] = field(default_factory=list)

    def move_to(self, x, y, z, r=0.0):
        self.log.append(("move", round(x, 1), round(y, 1), round(z, 1)))
        if self.verbose:
            print(f"  [dry] move  x={x:7.1f} y={y:7.1f} z={z:6.1f}")

    def suction(self, on):
        self.log.append(("suction", on))
        if self.verbose:
            print(f"  [dry] suction {'ON ' if on else 'OFF'}")


class DobotMG400(Arm):
    """Справжня MG400 через офіційну бібліотеку Dobot (TCP/IP).

    1. Файл dobot_api.py з https://github.com/Dobot-Arm/TCP-IP-4Axis-Python п
    2. У DobotStudio Pro увімкнути режим «TCP/IP secondary development».
    3. Мережевий кабель у LAN1 контролера; у ПК фіксована адреса
    4. Порти: 29999 (команди й GetPose), 30003 (рух).
    5. suction_do: DO 2
    """

    def __init__(self, ip: str = "192.168.1.6", suction_do: int = 1, speed_percent: int = 20,
                 tool_do: bool = False, enable_wait_s: float = 3.0, ready_timeout_s: float = 10.0) -> None:
        try:
            from dobot_api import DobotApiDashboard, DobotApiMove  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Не знайдено dobot_api.py. Завантажте його з "
                "https://github.com/Dobot-Arm/TCP-IP-4Axis-Python і покладіть поруч."
            ) from e
        self._dash = self._connect(DobotApiDashboard, ip, 29999)
        try:
            self._move = self._connect(DobotApiMove, ip, 30003)
        except Exception:
            if hasattr(self._dash, "close"):
                self._dash.close()
            raise
        self._suction_do = suction_do
        self._tool_do = tool_do
        self.last_reply = ""
        self._target = None
        self._move_time = 0.0
        self._speed = speed_percent
        self.base_s = 1.0
        self.mm_per_s_per_percent = 2.0
        self.poll_s = 0.2
        self.trace = False
        self._patch_reply_decoding(self._move)
        self._dash.ClearError()
        self._dash.EnableRobot()
        time.sleep(enable_wait_s)
        if hasattr(self._dash, "SpeedFactor"):
            self._dash.SpeedFactor(speed_percent)
        self._wait_ready(ready_timeout_s)

    def _wait_ready(self, timeout: float) -> None:
        """Після Enable контролер має почати віддавати справжню позу. Якщо ні, рука не готова
        (тривога, вимкнулась): рухи слати не можна."""
        if timeout <= 0 or not hasattr(self._dash, "GetPose"):
            return
        end = time.time() + timeout
        while time.time() < end:
            if self._pose() is not None:
                return
            time.sleep(0.5)
        raise RuntimeError(
            "Рука не віддає позу після Enable (повертає нулі). Ймовірно, тривога або вона вимкнулась: "
            "подивіться Log у DobotStudio, натисніть Clear Alarm / Enable і спробуйте ще раз."
        )

    @staticmethod
    def _connect(cls, ip: str, port: int, tries: int = 3, delay_s: float = 2.0):
        """Підключитися з повторами: контролер після попереднього запуску інколи ще кілька секунд тримає старе з'єднання."""
        last = None
        for i in range(tries):
            try:
                return cls(ip, port)
            except Exception as err: # noqa: BLE001
                last = err
                if i + 1 < tries:
                    print(f"  Контролер ще не приймає з'єднання на порту {port}, чекаю {delay_s:.0f} с "
                          f"(спроба {i + 1}/{tries})...")
                    time.sleep(delay_s)
        raise RuntimeError(
            f"Контролер {ip} не приймає з'єднання на порту {port} (спроб: {tries}). "
            "Закрийте інші програми, що підключені до руки (інший запуск скрипта), зачекайте хвилину, "
            "перевірте ping і режим TCP/IP secondary development у DobotStudio."
        ) from last

    def _patch_reply_decoding(self, api) -> None:
        """Бібліотека Dobot декодує відповідь контролера строго як UTF-8 і падає, якщо там інші байти
        (наприклад, повідомлення про помилку китайською в GBK). Підміняємо читання відповіді на
        стійке, а текст відповіді зберігаємо в self.last_reply і друкуємо, коли це не успіх."""
        sock = getattr(api, "socket_dobot", None)
        if sock is None:
            return
        outer = self

        def wait_reply(self_api):
            data = sock.recv(1024)
            if len(data) >= 1000 or data.count(b"\x00") > 20:
                outer.last_reply = "<feedback packet>"
                return outer.last_reply
            for enc in ("utf-8", "gbk"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    text = None
            if text is None:
                text = repr(data)
            outer.last_reply = text
            if not text.lstrip().startswith("0"):
                print(f"  [dobot] відповідь контролера: {text!r}")
            return text

        api.wait_reply = types.MethodType(wait_reply, api)

    def move_to(self, x, y, z, r=0.0):
        prev, self._target = self._target, (x, y, z)
        dist = 300.0 if prev is None else math.dist(prev, self._target)
        self._move_time = self.base_s + dist / (self._speed * self.mm_per_s_per_percent)
        self._move.MovL(x, y, z, r)

    def suction(self, on):
        status = 1 if on else 0
        if self._tool_do and hasattr(self._dash, "ToolDO"):
            self._dash.ToolDO(self._suction_do, status)
        else:
            self._dash.DO(self._suction_do, status)

    def _pose(self):
        """Поточні (x, y, z) з GetPose або None, якщо відповідь не розібрати або там самі нулі
        (контролер віддає нулі, коли поза недоступна)."""
        with contextlib.redirect_stdout(io.StringIO()):
            text = str(self._dash.GetPose())
        m = re.search(r"\{([^}]*)\}", text)
        if not m:
            return None
        try:
            vals = [float(v) for v in m.group(1).split(",")]
        except ValueError:
            return None
        if len(vals) < 3 or all(abs(v) < 1e-9 for v in vals[:4]):
            return None
        return tuple(vals[:3])

    def wait(self, tol: float = 1.0, timeout: float = 30.0):
        """Чекаємо кінця останнього руху. Під час руху контролер на запити GetPose відповідає повільно й
        гальмує сам (бачили затримки по ~9 с), тому спершу просто спимо розрахований час руху,
        і лише потім перевіряємо через GetPose, що рука в межах tol мм від цілі."""
        if self._target is None:
            return
        time.sleep(self._move_time)
        self._move_time = 0.0
        if not hasattr(self._dash, "GetPose"):
            return
        start = time.time()
        pose = None
        while True:
            got = self._pose()
            if self.trace:
                shown = tuple(round(v, 1) for v in got) if got else "нулі/немає"
                print(f"    [перевірка +{time.time() - start:5.1f} с] поза {shown}")
            if got is not None:
                pose = got
                if max(abs(a - b) for a, b in zip(pose, self._target)) <= tol:
                    return
            if time.time() - start > timeout:
                cur = tuple(round(v, 1) for v in pose) if pose else "невідомо"
                raise RuntimeError(
                    f"Рука не дійшла до {tuple(round(v, 1) for v in self._target)} за {timeout:.0f} с, "
                    f"остання поза {cur}. Подивіться тривоги в DobotStudio."
                )
            time.sleep(self.poll_s)

    def close(self, disable: bool = False):
        """Закрити з'єднання. Руку за замовчуванням НЕ вимикаємо: після DisableRobot вона може
        просісти або впасти з висоти. Вимикаємо в DobotStudio, коли вона в безпечному положенні."""
        try:
            if disable:
                self._dash.DisableRobot()
        finally:
            for s in (self._dash, self._move):
                sock = getattr(s, "socket_dobot", None)
                if sock is not None:
                    try:
                        sock.shutdown(2)
                    except (OSError, AttributeError):
                        pass
                if hasattr(s, "close"):
                    s.close()


# 3. Хід -> послідовність дій руки
class Mover:
    """Перетворює Move на pick-and-place. Не знає, яка саме це рука."""

    def __init__(self, arm: Arm, calib: RobotCalibration, grip_delay_s: float = 0.4) -> None:
        self.arm, self.cal, self.delay = arm, calib, grip_delay_s

    def _above(self, xy: Tuple[float, float]) -> None:
        self.arm.move_to(xy[0], xy[1], self.cal.z_safe, self.cal.r)
        self.arm.wait()

    def _down(self, xy: Tuple[float, float]) -> None:
        self.arm.move_to(xy[0], xy[1], self.cal.z_board, self.cal.r)
        self.arm.wait()

    def _pause(self) -> None:
        self.arm.wait()
        if self.delay and not isinstance(self.arm, DryRunArm):
            import time
            time.sleep(self.delay)

    def pick_and_place(self, src_xy: Tuple[float, float], dst_xy: Tuple[float, float]) -> None:
        self._above(src_xy)
        self._down(src_xy)
        self.arm.wait() # присоска вмикається лише коли рука вже ДОЇХАЛА до фігури
        self.arm.suction(True)
        self._pause() # дати присосці схопити фігуру
        self._above(src_xy) # піднімаємо над іншими фігурами
        self._above(dst_xy)
        self._down(dst_xy)
        self.arm.wait() # відпускаємо лише коли рука вже на місці призначення
        self.arm.suction(False)
        self._pause() # дати фігурі відпуститись
        self._above(dst_xy)

    def play(self, move: Move) -> None:
        """Робот робить хід. Якщо це побиття, спочатку прибирає побиту фігуру."""
        src = self.cal.square_xy(move.from_sq)
        dst = self.cal.square_xy(move.to_sq)
        if move.is_capture:
            self.pick_and_place(dst, self.cal.discard)
        self.pick_and_place(src, dst)
        if self.cal.park: # відїхати вбік, щоб рука не заважала камері бачити дошку
            self.arm.move_to(self.cal.park[0], self.cal.park[1], self.cal.z_safe, self.cal.r)
        self.arm.wait()
