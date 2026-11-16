"""Камера: відкриття з перевіркою та налаштування (однакові для tools/camera_test.py і для play.py).

Налаштування лежать у camera_settings.json (шаблон camera_settings.example.json), щоб один раз підібрати
номер камери, розмір кадру й експозицію, а потім усі скрипти використовували їх самі:
  {"cam": 1, "width": 1920, "height": 1080, "exposure": -6}
exposure: ручна експозиція (DirectShow: від'ємне число, менше = темніше); null = автоматична.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2

from . import vision

DEFAULTS = {"cam": 0, "width": 1920, "height": 1080, "exposure": None}


def load_settings(path: str = "camera_settings.json") -> dict:
    """Налаштування з файлу (якщо він є) поверх значень за замовчуванням."""
    cfg = dict(DEFAULTS)
    if Path(path).exists():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def set_exposure(cap: "cv2.VideoCapture", exposure) -> None:
    """Ручна експозиція; exposure=None залишає автоматичну."""
    if exposure is None:
        return
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)    # 0.25 = вручну в DirectShow
    cap.set(cv2.CAP_PROP_EXPOSURE, exposure)


def open_camera(index: int, width: int, height: int, exposure=None, tries: int = 3) -> "cv2.VideoCapture":
    """Відкриває камеру й перевіряє, що вона справді віддає кадр потрібного розміру.
    DirectShow інколи віддає перші кадри не одразу або вмикає менший розмір (640x480): тоді відкриваємо ще раз."""
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = None
    for _ in range(tries):
        if cap is not None:
            cap.release()
            time.sleep(0.5)
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        set_exposure(cap, exposure)
        ok, frame = False, None
        for _ in range(30):                      # перші кадри часто не віддаються: чекаємо до ~3 с
            ok, frame = cap.read()
            if ok:
                break
            time.sleep(0.1)
        if ok and frame.shape[1] >= 0.9 * width:
            print(f"Камера {index}: {frame.shape[1]}x{frame.shape[0]}"
                  + (f", експозиція {exposure}" if exposure is not None else ", експозиція авто"))
            return cap
    if cap is None or not cap.isOpened():
        raise SystemExit(f"Камеру {index} не вдалося відкрити. Спробуйте `list`.")
    print(f"УВАГА: камера віддає менший розмір, ніж {width}x{height}: "
          f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    return cap


def wait_stable(read, accept, errors, ignore=None, same_needed=3, interval=0.4, timeout=None, on_error=print):
    """Знімає кадри, доки та сама позиція не повториться same_needed разів підряд (руки в кадрі немає), і тоді
    пробує її прийняти: accept(colors). Якщо accept кидає виняток з `errors`, чекає далі (людина може поправити
    фігури); після timeout секунд кидає цей виняток. Позицію `ignore` (ходу ще не було) пропускає мовчки."""
    last, same, shown, start = None, 0, None, time.time()
    while True:
        colors = read()
        same = same + 1 if colors == last else 1
        last = colors
        if same >= same_needed and colors != ignore:
            try:
                return accept(colors)
            except errors as err:
                if str(err) != shown:
                    shown = str(err)
                    on_error(err)
                if timeout is not None and time.time() - start > timeout:
                    raise
        time.sleep(interval)


class BoardCamera:
    """Знімає дошку й повертає карту кольорів 10x9 (0 порожньо, 1 червоні, 2 чорні) для гри.

    Потрібні файли від tools/camera_test.py: corners.json (кути дошки на кадрі) і calibration.json
    (пороги за фото стартової позиції: `camera_test.py check start.jpg`). Камера й експозиція беруться з
    camera_settings.json. Якщо змінилось світло, експозиція чи положення камери, ці файли треба зробити заново.
    """

    def __init__(self, cfg: dict, corners_file: str = "corners.json", calib_file: str = "calibration.json",
                 overlay_out: str = "overlay_last.jpg") -> None:
        for name in (corners_file, calib_file):
            if not Path(name).exists():
                raise SystemExit(f"Немає файлу {name}. Спершу: camera_test.py snap, corners, check (див. README).")
        self.cfg = cfg
        self.points = vision.grid_points(vision.homography_from_corners(json.loads(Path(corners_file).read_text())))
        self.cal = vision.Calibration.from_json(Path(calib_file).read_text())
        self.overlay_out = overlay_out
        self.flush = 5          # скільки застарілих кадрів з буфера викинути перед знімком
        self.cap = None         # камера відкривається один раз і тримається відкритою всю гру

    def read_frame(self):
        if self.cap is None:
            self.cap = open_camera(self.cfg["cam"], self.cfg["width"], self.cfg["height"], self.cfg["exposure"])
        for _ in range(self.flush):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Не вдалося зняти кадр з камери")
        return frame

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def read_colors(self):
        frame = self.read_frame()
        colors = vision.classify(vision.extract_features(frame, self.points), self.cal)
        if self.overlay_out:                      # картинка з розміткою, щоб бачити, що саме розпізнала програма
            cv2.imwrite(self.overlay_out, vision.draw_overlay(frame, self.points, colors))
        return vision.to_list(colors)
