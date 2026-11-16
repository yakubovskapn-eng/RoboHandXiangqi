"""
Тести зору на синтетичних зображеннях (без камери).

Малюємо дошку з фігурами, спотворюємо перспективою, як це зробила б камера під кутом,
і перевіряємо, що vision повертає правильну карту кольорів і хід.
Пропускаються, якщо немає opencv.
"""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from xiangqi_robot import Board, Move, detect_move, parse_square, vision  # noqa: E402
from xiangqi_robot.board import COLS, ROWS  # noqa: E402

CORNERS = [(430, 150), (1500, 190), (1560, 930), (360, 880)]  #a9, i9, i0, a0 у кадрі 1920x1080


def render(board: Board, noise: int = 0) -> np.ndarray:
    """Дошка у «плоскому» вигляді 900x1000, потім перспектива в кадр 1920x1080."""
    step, margin = 100, 50
    flat = np.full((ROWS * step, COLS * step + 100, 3), (120, 170, 215), np.uint8)
    for r in range(ROWS):
        cv2.line(flat, (margin, margin + r * step), (margin + 8 * step, margin + r * step), (20, 20, 20), 2)
    for c in range(COLS):
        cv2.line(flat, (margin + c * step, margin), (margin + c * step, margin + 9 * step), (20, 20, 20), 2)
    for r in range(ROWS):
        for c in range(COLS):
            ch = board.grid[r][c]
            if ch == ".":
                continue
            ctr = (margin + c * step, margin + r * step)
            cv2.circle(flat, ctr, 42, (180, 215, 240), -1)
            cv2.circle(flat, ctr, 42, (60, 90, 130), 2)
            ink = (0, 0, 200) if ch.isupper() else (25, 25, 25)
            cv2.circle(flat, ctr, 22, ink, -1)
    src = np.float32([[margin, margin], [margin + 8 * step, margin],
                      [margin + 8 * step, margin + 9 * step], [margin, margin + 9 * step]])
    m = cv2.getPerspectiveTransform(src, np.float32(CORNERS))
    img = cv2.warpPerspective(flat, m, (1920, 1080), borderValue=(90, 90, 90))
    if noise:
        rng = np.random.default_rng(1)
        img = np.clip(img.astype(int) + rng.integers(-noise, noise + 1, img.shape), 0, 255).astype(np.uint8)
    return img


def setup():
    start = Board.start()
    img = render(start, noise=8)
    pts = vision.grid_points(vision.homography_from_corners(CORNERS))
    cal = vision.calibrate_on_start(vision.extract_features(img, pts), start)
    return start, pts, cal


def test_start_position_classified_perfectly():
    start, pts, cal = setup()
    assert cal.occupancy_gap > 0 and cal.color_gap > 0 and cal.color_accuracy == 1.0
    colors = vision.classify(vision.extract_features(render(start, 8), pts), cal)
    assert colors.tolist() == start.colors()


def test_move_recognized_from_image():
    start, pts, cal = setup()
    move = Move("C", parse_square("h2"), parse_square("e2"))
    after = start.apply(move)
    colors = vision.classify(vision.extract_features(render(after, 8), pts), cal)
    found = detect_move(start, vision.to_list(colors))
    assert found.uci == "h2e2"


def test_capture_recognized_from_image():
    board = Board.from_fen("4k4/9/9/9/4p4/9/4R4/9/9/3K5 w - - 0 1") #R e3 бере p e5? (e5 - чорна піхота)
    move = Move("R", parse_square("e3"), parse_square("e5"), "p")
    start, pts, cal = setup()
    colors = vision.classify(vision.extract_features(render(board.apply(move), 8), pts), cal)
    found = detect_move(board, vision.to_list(colors))
    assert found.uci == "e3e5" and found.is_capture


def _with_river_text(img: np.ndarray, pts: np.ndarray, r: int, c: int) -> np.ndarray:
    """Темні штрихи в порожній клітинці: імітація напису «річка» на дошці."""
    out = img.copy()
    x, y = pts[r, c]
    for dx in range(-22, 23, 11):
        cv2.line(out, (int(x + dx), int(y - 26)), (int(x - dx * 0.4), int(y + 26)), (25, 25, 25), 6)
    cv2.line(out, (int(x - 28), int(y)), (int(x + 28), int(y + 4)), (25, 25, 25), 6)
    return out


def test_empty_cell_with_printed_text_is_not_a_piece():
    """Регресія: напис «річка» на порожній клітинці e5 не має сприйматися як фігура."""
    start = Board.start()
    pts = vision.grid_points(vision.homography_from_corners(CORNERS))
    img = _with_river_text(render(start, 8), pts, 5, 4)
    feats = vision.extract_features(img, pts)
    cal = vision.calibrate_on_start(feats, start)
    assert vision.classify(feats, cal).tolist() == start.colors()
    old = vision.Calibration(**{**cal.__dict__, "empty_texture": None, "margin": 0.0})
    assert vision.classify(feats, old)[5, 4] != 0


def test_real_piece_on_text_cell_still_detected():
    start = Board.start()
    pts = vision.grid_points(vision.homography_from_corners(CORNERS))
    cal = vision.calibrate_on_start(
        vision.extract_features(_with_river_text(render(start, 8), pts, 5, 4), pts), start)
    after = Board.from_fen("4k4/9/9/9/9/4r4/9/9/9/4K4 w - - 0 1")  
    colors = vision.classify(vision.extract_features(render(after, 8), pts), cal)
    assert colors[5, 4] == 2
