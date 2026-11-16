"""Зір: з фото дошки отримати карту кольорів 10x9 (0 порожньо, 1 червоні, 2 чорні).

Потрібні opencv-python і numpy. Ядро проєкту
(board, rules, move_detection) від цього модуля не залежить.

Ідея:
1. Людина вказує на фото 4 кути ігрового поля (крайні перетини ліній).
   Порядок: a9, i9, i0, a0, тобто верхній лівий, верхній правий, нижній правий,
   нижній лівий кут у координатах Board (рядок 0 зверху, бік чорних).
   Камера може бути повернута як завгодно: порядок кутів визначає орієнтацію.
2. Гомографія переводить логічні координати (col, row) у пікселі, тож ми знаємо
   піксель кожного з 90 перетинів.
3. Навколо кожного перетину в круглій області міряємо контрастність (фігура з
   ієрогліфом контрастніша за порожню клітинку) і червоність (червоні ієрогліфи).
4. Пороги калібруємо на фото стартової позиції, де відомо,
   які клітинки зайняті й яким кольором.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .board import COLS, NO_PIECE, RED, BLACK, ROWS, Board

Point = Tuple[float, float]


def homography_from_corners(corners: Sequence[Point]) -> np.ndarray:
    """3x3 матриця: логічні (col,row) -> піксель. corners: a9, i9, i0, a0."""
    if len(corners) != 4:
        raise ValueError("Потрібно рівно 4 кути")
    src = np.float32([[0, 0], [COLS - 1, 0], [COLS - 1, ROWS - 1], [0, ROWS - 1]])
    dst = np.float32(corners)
    return cv2.getPerspectiveTransform(src, dst)


def grid_points(h: np.ndarray) -> np.ndarray:
    """Масив (ROWS, COLS, 2) з пікселями всіх перетинів."""
    pts = np.float32([[c, r] for r in range(ROWS) for c in range(COLS)]).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(pts, h).reshape(ROWS, COLS, 2)
    return out


def cell_radius(points: np.ndarray, r: int, c: int, factor: float = 0.38) -> int:
    """Радіус області аналізу: частка відстані до сусіда."""
    p = points[r, c]
    dists = []
    if c + 1 < COLS:
        dists.append(np.linalg.norm(points[r, c + 1] - p))
    if c - 1 >= 0:
        dists.append(np.linalg.norm(points[r, c - 1] - p))
    if r + 1 < ROWS:
        dists.append(np.linalg.norm(points[r + 1, c] - p))
    if r - 1 >= 0:
        dists.append(np.linalg.norm(points[r - 1, c] - p))
    return max(3, int(min(dists) * factor))


@dataclass
class Features:
    texture: np.ndarray  # (ROWS, COLS) розкид яскравості: фігура з ієрогліфом контрастніша за порожню клітинку
    redness: np.ndarray  # (ROWS, COLS) наскільки «червоні» найчервоніші пікселі (R мінус середнє G і B)
    brightness: np.ndarray  # (ROWS, COLS) середня яскравість: світлий диск фігури яскравіший за дошку й напис «річка»


def extract_features(frame_bgr: np.ndarray, points: np.ndarray) -> Features:
    """Для кожного перетину: контрастність і червоність у колі всередині фігури."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b, g, r_ch = [frame_bgr[..., i].astype(np.float32) for i in range(3)]
    redc = r_ch - (g + b) / 2
    height, width = gray.shape
    texture = np.zeros((ROWS, COLS), dtype=np.float32)
    redness = np.zeros((ROWS, COLS), dtype=np.float32)
    brightness = np.zeros((ROWS, COLS), dtype=np.float32)
    for r in range(ROWS):
        for c in range(COLS):
            x, y = points[r, c]
            rad = cell_radius(points, r, c)
            x0, x1 = int(max(0, x - rad)), int(min(width, x + rad + 1))
            y0, y1 = int(max(0, y - rad)), int(min(height, y + rad + 1))
            if x1 <= x0 or y1 <= y0:
                continue  # перетин поза кадром
            yy, xx = np.mgrid[y0:y1, x0:x1]
            mask = (xx - x) ** 2 + (yy - y) ** 2 <= rad ** 2
            if not mask.any():
                continue
            texture[r, c] = float(gray[y0:y1, x0:x1][mask].std())
            redness[r, c] = float(np.percentile(redc[y0:y1, x0:x1][mask], 97))
            brightness[r, c] = float(gray[y0:y1, x0:x1][mask].mean())
    return Features(texture, redness, brightness)


@dataclass
class Calibration:
    texture_threshold: float # вище: клітинка зайнята
    red_threshold: float # вище: фігура червона (серед зайнятих)
    brightness_threshold: float # вище: світлий диск фігури (відсікає напис «річка»); -1 = вимкнено
    occupancy_gap: float # >0: зайняті й порожні чисто розділяються
    color_gap: float # >0: червоні й чорні чисто розділяються
    color_accuracy: float # частка стартових фігур з правильним кольором
    # Індивідуальний «рівень порожньої клітинки» зі стартового фото (None там, де стояла фігура).
    # Потрібен, бо на дошці є клітинки з написами/лініями (річка, палац), де порожньо, але контраст
    # вищий за загальний поріг. Для них поріг = власний рівень + margin.
    empty_texture: Optional[List[List[Optional[float]]]] = None
    margin: float = 0.0

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        return cls(**json.loads(text))


def calibrate_on_start(features: Features, board: Board | None = None) -> Calibration:
    """Підбирає пороги за фото стартової позиції"""
    board = board or Board.start()
    truth = np.array(board.colors())
    tex, red = features.texture, features.redness

    occ_low = float(np.percentile(tex[truth != NO_PIECE], 5))
    empty_high = float(np.percentile(tex[truth == NO_PIECE], 95))
    tex_thr = (occ_low + empty_high) / 2

    red_low = float(np.percentile(red[truth == RED], 5))
    black_high = float(np.percentile(red[truth == BLACK], 95))
    red_thr = (red_low + black_high) / 2

    # Яскравість: відсікає темні написи на дошці (річка), які дають високу контрастність.
    b_low = float(np.percentile(features.brightness[truth != NO_PIECE], 5))
    b_high = float(np.percentile(features.brightness[truth == NO_PIECE], 95))
    bright_thr = (b_low + b_high) / 2 if b_low > b_high else -1.0

    # Індивідуальні рівні порожніх клітинок: найконтрастніша порожня клітинка (напис «річка»)
    # не повинна визначатися зайнятою, навіть якщо вона вища за 95-й процентиль.
    empty_mask = truth == NO_PIECE
    base = np.where(empty_mask, tex, np.nan)
    margin = max(3.0, 0.35 * (occ_low - float(np.median(tex[empty_mask]))))
    empty_texture = [[None if np.isnan(v) else float(v) for v in row] for row in base]

    cal = Calibration(tex_thr, red_thr, bright_thr, occ_low - empty_high, red_low - black_high, 0.0,
                      empty_texture, margin)
    pred = classify(features, cal)
    occupied = truth != NO_PIECE
    cal.color_accuracy = float((pred[occupied] == truth[occupied]).mean())
    return cal


def classify(features: Features, cal: Calibration) -> np.ndarray:
    """Карта кольорів (ROWS, COLS): 0 порожньо, 1 червоні, 2 чорні."""
    out = np.zeros((ROWS, COLS), dtype=int)
    thr = np.full((ROWS, COLS), cal.texture_threshold, dtype=np.float32)
    if cal.empty_texture is not None:
        base = np.array(cal.empty_texture, dtype=np.float32)  # None -> nan
        thr = np.where(np.isnan(base), thr, np.maximum(thr, base + cal.margin))
    occupied = (features.texture > thr) & (features.brightness > cal.brightness_threshold)
    is_red = features.redness > cal.red_threshold
    out[occupied & is_red] = RED
    out[occupied & ~is_red] = BLACK
    return out


def to_list(colors: np.ndarray) -> List[List[int]]:
    return [[int(v) for v in row] for row in colors]


def draw_overlay(frame_bgr: np.ndarray, points: np.ndarray, colors: np.ndarray) -> np.ndarray:
    """Копія кадру з кружками: червоний = червона фігура, синій = чорна, сірий = порожньо."""
    img = frame_bgr.copy()
    palette = {NO_PIECE: (170, 170, 170), RED: (0, 0, 255), BLACK: (255, 80, 0)}
    for r in range(ROWS):
        for c in range(COLS):
            x, y = points[r, c]
            rad = cell_radius(points, r, c)
            v = int(colors[r, c])
            thickness = 1 if v == NO_PIECE else 3
            cv2.circle(img, (int(x), int(y)), rad, palette[v], thickness)
    return img
