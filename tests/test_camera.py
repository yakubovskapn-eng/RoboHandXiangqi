"""Налаштування й відкриття камери (без справжньої камери: підроблений cv2.VideoCapture)."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from xiangqi_robot import camera  # noqa: E402


def test_load_settings_merges_file_over_defaults(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"cam": 1, "exposure": -6}')
    assert camera.load_settings(str(f)) == {"cam": 1, "width": 1920, "height": 1080, "exposure": -6}
    assert camera.load_settings(str(tmp_path / "none.json"))["exposure"] is None


def test_open_camera_reopens_small_frames_and_applies_exposure(monkeypatch):
    monkeypatch.setattr(camera.time, "sleep", lambda s: None)
    made = []

    class Cap:
        def __init__(self, *a):
            made.append(self)
            self.props = {}
        def isOpened(self): return True
        def set(self, prop, value): self.props[prop] = value
        def get(self, prop): return 640
        def release(self): pass
        def read(self):
            size = (480, 640) if len(made) == 1 else (1080, 1920)      # 1-ша спроба: камера вмикає 640x480
            return True, np.zeros((*size, 3), np.uint8)

    monkeypatch.setattr(camera.cv2, "VideoCapture", Cap)
    cap = camera.open_camera(1, 1920, 1080, exposure=-6)
    assert len(made) == 2
    assert cap.props[cv2.CAP_PROP_EXPOSURE] == -6
    assert cap.props[cv2.CAP_PROP_AUTO_EXPOSURE] == 0.25


def test_open_camera_leaves_auto_exposure_when_not_set(monkeypatch):
    monkeypatch.setattr(camera.time, "sleep", lambda s: None)

    class Cap:
        def __init__(self, *a): self.props = {}
        def isOpened(self): return True
        def set(self, prop, value): self.props[prop] = value
        def release(self): pass
        def read(self): return True, np.zeros((1080, 1920, 3), np.uint8)

    monkeypatch.setattr(camera.cv2, "VideoCapture", Cap)
    cap = camera.open_camera(0, 1920, 1080)
    assert cv2.CAP_PROP_EXPOSURE not in cap.props


def test_board_camera_reads_colors_from_frame(monkeypatch, tmp_path):
    """Підміняємо кадр камери синтетичною стартовою позицією: карта кольорів має збігтися з нею."""
    import json
    from xiangqi_robot import Board, vision
    from tests.test_vision import CORNERS, render, setup

    board, pts, cal = setup()
    img = render(board, noise=8)
    corners = CORNERS
    (tmp_path / "corners.json").write_text(json.dumps([list(map(float, c)) for c in corners]))
    (tmp_path / "cal.json").write_text(cal.to_json())
    class Cap:
        grabbed = 0

        def grab(self):
            Cap.grabbed += 1

        def read(self):
            return True, img

        def release(self):
            pass

    opened = []
    monkeypatch.setattr(camera, "open_camera", lambda *a, **k: opened.append(1) or Cap())
    reader = camera.BoardCamera({"cam": 0, "width": 1920, "height": 1080, "exposure": None},
                                str(tmp_path / "corners.json"), str(tmp_path / "cal.json"),
                                overlay_out=str(tmp_path / "o.jpg"))
    assert reader.read_colors() == board.colors()
    assert reader.read_colors() == board.colors()
    assert len(opened) == 1 and Cap.grabbed == 10      # камера відкрита один раз, буфер скидається перед кадром
    reader.close()
    assert (tmp_path / "o.jpg").exists()



def _frames(*maps):
    it = iter(maps)
    return lambda: next(it)


def test_wait_stable_waits_for_same_position_and_skips_unchanged(monkeypatch):
    monkeypatch.setattr(camera.time, "sleep", lambda s: None)
    start, moved = [[0]], [[1]]
    # позиція ще не змінилась (ignore), рука в кадрі (різні кадри), потім ставши стабільною: приймаємо
    read = _frames(start, start, start, [[2]], [[3]], moved, moved, moved)
    assert camera.wait_stable(read, lambda c: c, ValueError, ignore=start) == moved


def test_wait_stable_keeps_waiting_on_error_then_accepts_fixed_position(monkeypatch):
    monkeypatch.setattr(camera.time, "sleep", lambda s: None)
    bad, good = [[1]], [[2]]
    shown = []

    def accept(c):
        if c == bad:
            raise ValueError("не те")
        return c

    read = _frames(bad, bad, bad, bad, good, good, good)
    assert camera.wait_stable(read, accept, ValueError, on_error=shown.append) == good
    assert len(shown) == 1                      # однакова помилка друкується один раз


def test_wait_stable_raises_after_timeout(monkeypatch):
    monkeypatch.setattr(camera.time, "sleep", lambda s: None)
    t = iter(range(0, 100, 10))
    monkeypatch.setattr(camera.time, "time", lambda: next(t))

    def accept(c):
        raise ValueError("не те")

    with pytest.raises(ValueError):
        camera.wait_stable(lambda: [[1]], accept, ValueError, timeout=15, on_error=lambda e: None)
