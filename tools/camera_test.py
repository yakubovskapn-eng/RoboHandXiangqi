"""
Перевірка зору на реальній камері (USB-камера OV5640).

Кроки
  python tools/camera_test.py list
  python tools/camera_test.py snap  --out start.jpg
  python tools/camera_test.py corners start.jpg
  python tools/camera_test.py check start.jpg
  python tools/camera_test.py timing
  python tools/camera_test.py snap  --out after.jpg
  python tools/camera_test.py move  after.jpg --start start.jpg

яка камера під яким номером
фото стартової позиції (камера й експозиція з camera_settings.json)
клік по 4 кутах -> corners.json
калібрування + картинка overlay
скільки секунд іде на відкриття камери і на кадр
після ходу людини
який хід зроблено
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from xiangqi_robot import Board, MoveDetectionError, detect_move  # noqa: E402
from xiangqi_robot import vision  # noqa: E402
from xiangqi_robot.camera import load_settings, open_camera  # noqa: E402

CORNER_NAMES = ["a9 (верхній лівий, бік чорних)", "i9 (верхній правий)",
                "i0 (нижній правий, бік червоних)", "a0 (нижній лівий)"]


def cmd_list(_args) -> None:
    found = False
    for i in range(6):
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():

            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            ok, frame = cap.read()
            if ok:
                print(f"камера {i}: кадр {frame.shape[1]}x{frame.shape[0]}")
                found = True
        cap.release()
    if not found:
        print("Камер не знайдено. Перевірте кабель і чи не зайнята вона іншою програмою.")


def cmd_snap(args) -> None:
    cap = open_camera(args.cam, args.width, args.height, args.exposure)

    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

    for _ in range(args.warmup):
        cap.read()
        time.sleep(0.03)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("Не вдалося зняти кадр")
    cv2.imwrite(args.out, frame)
    print(f"Збережено {args.out}: {frame.shape[1]}x{frame.shape[0]}")


def cmd_corners(args) -> None:
    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"Не вдалося прочитати {args.image}")
    clicks: list[tuple[int, int]] = []
    scale = min(1.0, 1200 / img.shape[1])
    view = cv2.resize(img, None, fx=scale, fy=scale)

    def redraw() -> None:
        canvas = view.copy()
        for i, (x, y) in enumerate(clicks):
            cv2.circle(canvas, (int(x * scale), int(y * scale)), 6, (0, 255, 0), -1)
            cv2.putText(canvas, str(i + 1), (int(x * scale) + 8, int(y * scale) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        nxt = CORNER_NAMES[len(clicks)] if len(clicks) < 4 else "ГОТОВО: натисніть будь-яку клавішу"
        cv2.putText(canvas, nxt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imshow("corners", canvas)

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((round(x / scale), round(y / scale)))
            redraw()

    cv2.namedWindow("corners")
    cv2.setMouseCallback("corners", on_mouse)
    redraw()
    while len(clicks) < 4:
        if cv2.waitKey(50) == 27:
            raise SystemExit("Скасовано")
    redraw()
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    Path(args.out).write_text(json.dumps(clicks))
    print(f"Кути збережено в {args.out}: {clicks}")


def load_points(image: np.ndarray, corners_file: str):
    corners = json.loads(Path(corners_file).read_text())
    h = vision.homography_from_corners(corners)
    return vision.grid_points(h)


def cmd_check(args) -> None:
    img = cv2.imread(args.image)
    points = load_points(img, args.corners)
    feats = vision.extract_features(img, points)
    cal = vision.calibrate_on_start(feats)
    colors = vision.classify(feats, cal)
    truth = np.array(Board.start().colors())
    wrong = int((colors != truth).sum())
    out = args.overlay
    cv2.imwrite(out, vision.draw_overlay(img, points, colors))
    Path(args.calib).write_text(cal.to_json())
    ok_occ = "добре" if cal.occupancy_gap > 0 else "ПОГАНО: зайняті й порожні змішуються (світло, різкість або кути)"
    ok_col = "добре" if cal.color_gap > 0 else "ПОГАНО: червоні й чорні змішуються (світло або кути)"
    print(f"Порогів: зайнятість {cal.texture_threshold:.1f}, червоність {cal.red_threshold:.1f}")
    print(f"Зайняті/порожні розділяються: {cal.occupancy_gap:+.1f} ({ok_occ})")
    print(f"Червоні/чорні розділяються:   {cal.color_gap:+.1f} ({ok_col})")
    print("Фільтр яскравості (відсікає написи на дошці):",
          f"увімкнено, поріг {cal.brightness_threshold:.1f}" if cal.brightness_threshold >= 0
          else "вимкнено (мало світла, диски фігур не яскравіші за дошку)")
    print(f"Колір фігур вгадано правильно: {cal.color_accuracy:.0%}")
    empty = truth == 0
    worst = sorted(((feats.texture[r, c], (r, c)) for r in range(10) for c in range(9) if empty[r, c]),
                   reverse=True)[:3]
    from xiangqi_robot import square_name as _sn
    print("Найконтрастніші ПОРОЖНІ клітинки (напис, лінії): " +
          ", ".join(f"{_sn(p)}={t:.0f}" for t, p in worst) +
          f"; для них поріг підвищено до власного рівня + {cal.margin:.1f}")
    print(f"Усього клітинок із помилкою: {wrong} з 90")
    print(f"Картинку з розміткою збережено: {out} (червоне коло = червона, синє = чорна, сіре = порожньо)")
    if wrong:
        bad = [(r, c) for r in range(10) for c in range(9) if colors[r, c] != truth[r, c]]
        from xiangqi_robot import square_name
        print("Помилкові клітинки:", ", ".join(square_name(p) for p in bad))


def cmd_move(args) -> None:
    start_img = cv2.imread(args.start)
    after_img = cv2.imread(args.image)
    points = load_points(start_img, args.corners)
    cal_feats = vision.extract_features(start_img, points)
    cal = vision.calibrate_on_start(cal_feats)
    colors = vision.classify(vision.extract_features(after_img, points), cal)
    board = Board.from_fen(args.fen) if args.fen else Board.start()
    cv2.imwrite(args.overlay, vision.draw_overlay(after_img, points, colors))
    try:
        move = detect_move(board, vision.to_list(colors))
    except MoveDetectionError as e:
        print("Хід НЕ розпізнано:", e)
        print(f"Подивіться картинку {args.overlay}: чи правильно позначені клітинки.")
        raise SystemExit(1)
    print(f"Розпізнано хід: {move.uci}  ({move})")
    print("Новий FEN:", board.apply(move).to_fen())


def cmd_timing(args) -> None:
    """Скільки секунд іде на відкриття камери і на кожен кадр (камера лишається відкритою)."""
    cfg = load_settings(args.camera_config)
    t = time.time()
    cap = open_camera(cfg["cam"], cfg["width"], cfg["height"], cfg["exposure"])
    print(f"відкриття камери: {time.time() - t:.2f} с")
    for i in range(args.n):
        t = time.time()
        for _ in range(args.flush):
            cap.grab()
        ok, _frame = cap.read()
        print(f"кадр {i + 1}: {time.time() - t:.2f} с (скинуто {args.flush} кадрів, ok={ok})")
    cap.release()


def cmd_preview(args) -> None:
    """Живе відео у вікні. Якщо задано --start, малює, що програма бачить на клітинках."""
    cap = open_camera(args.cam, args.width, args.height, args.exposure)
    points = cal = None
    if args.start:
        start_img = cv2.imread(args.start)
        points = load_points(start_img, args.corners)
        cal = vision.calibrate_on_start(vision.extract_features(start_img, points))
        print(f"Калібрування за {args.start}: зайнятість {cal.texture_threshold:.1f}, червоність {cal.red_threshold:.1f}")
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    if args.settings:
        cap.set(cv2.CAP_PROP_SETTINGS, 1)
    print("Вікно 'camera': S зберегти кадр, Q або Esc вийти.")
    saved = 0
    failed = 0
    delay = 1.0 / max(1, args.fps)
    while True:
        time.sleep(delay * 0.5)
        ok, frame = cap.read()
        if not ok:
            failed += 1
            if failed > 30:
                print("Камера не віддає кадр понад 3 с: перевірте кабель і чи її не тримає інша програма")
                break
            time.sleep(0.1)
            continue
        failed = 0
        view = frame
        if points is not None:
            colors = vision.classify(vision.extract_features(frame, points), cal)
            view = vision.draw_overlay(frame, points, colors)
        scale = min(1.0, 1280 / view.shape[1])
        cv2.imshow("camera", cv2.resize(view, None, fx=scale, fy=scale))
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s"):
            saved += 1
            name = f"shot_{saved}.jpg"
            cv2.imwrite(name, frame)
            print("Збережено", name)
    cap.release()
    cv2.destroyAllWindows()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    s = sub.add_parser("snap")
    s.add_argument("--cam", type=int)
    s.add_argument("--out", default="frame.jpg")
    s.add_argument("--width", type=int)
    s.add_argument("--height", type=int)
    s.add_argument("--warmup", type=int, default=30)
    s.add_argument("--exposure", type=float, help="ручна експозиція (DirectShow: від'ємне, менше = темніше, пробуйте -5..-9)")
    s.add_argument("--camera-config", default="camera_settings.json", help="файл із cam/width/height/exposure за замовчуванням")
    s.set_defaults(fn=cmd_snap)

    s = sub.add_parser("timing")
    s.add_argument("-n", type=int, default=5, help="скільки кадрів зняти")
    s.add_argument("--flush", type=int, default=5, help="скільки кадрів скинути перед кожним знімком")
    s.add_argument("--camera-config", default="camera_settings.json")
    s.set_defaults(fn=cmd_timing)

    s = sub.add_parser("preview")
    s.add_argument("--cam", type=int)
    s.add_argument("--width", type=int)
    s.add_argument("--height", type=int)
    s.add_argument("--fps", type=int, default=10, help="кадрів за секунду (менше = холодніша камера)")
    s.add_argument("--exposure", type=float, help="ручна експозиція (DirectShow: від'ємне, менше = темніше, пробуйте -5..-9)")
    s.add_argument("--camera-config", default="camera_settings.json", help="файл із cam/width/height/exposure за замовчуванням")
    s.add_argument("--settings", action="store_true", help="відкрити вікно налаштувань драйвера камери (Windows)")
    s.add_argument("--start", help="фото стартової позиції: тоді в кадрі малюється розпізнавання")
    s.add_argument("--corners", default="corners.json")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("corners")
    s.add_argument("image")
    s.add_argument("--out", default="corners.json")
    s.set_defaults(fn=cmd_corners)

    s = sub.add_parser("check")
    s.add_argument("image")
    s.add_argument("--corners", default="corners.json")
    s.add_argument("--overlay", default="overlay_start.jpg")
    s.add_argument("--calib", default="calibration.json")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("move")
    s.add_argument("image", help="фото після ходу")
    s.add_argument("--start", required=True, help="фото стартової позиції (для калібрування)")
    s.add_argument("--corners", default="corners.json")
    s.add_argument("--fen", help="позиція ДО ходу; за замовчуванням стартова")
    s.add_argument("--overlay", default="overlay_move.jpg")
    s.set_defaults(fn=cmd_move)

    args = p.parse_args()
    if hasattr(args, "camera_config"):             
        cfg = load_settings(args.camera_config)
        for name in ("cam", "width", "height", "exposure"):
            if getattr(args, name, None) is None:
                setattr(args, name, cfg[name])
    args.fn(args)


if __name__ == "__main__":
    main()
