"""
Тести керування рукою на DryRunArm (без робота): координати й послідовність дій
"""
import pytest

from xiangqi_robot import Board, Move, parse_square
from xiangqi_robot.arm import DryRunArm, Mover, RobotCalibration

# Дошка 8x9 «клітинок» по 30 мм: a9 (верхній лівий) у (300, -120), далі вниз по x.
# x росте від чорних до червоних, y росте праворуч (довільні, але правдоподібні числа).
CAL = RobotCalibration(
    corners=[(300.0, -120.0), (300.0, 120.0), (570.0, 120.0), (570.0, -120.0)],
    z_board=-10.0, z_safe=40.0, discard=(250.0, 220.0),
)


def test_corners_map_to_themselves():
    assert CAL.square_xy((0, 0)) == pytest.approx((300, -120)) # a9
    assert CAL.square_xy((0, 8)) == pytest.approx((300, 120)) # i9
    assert CAL.square_xy((9, 8)) == pytest.approx((570, 120)) # i0
    assert CAL.square_xy((9, 0)) == pytest.approx((570, -120)) # a0


def test_neighbours_are_30mm_apart():
    x1, y1 = CAL.square_xy(parse_square("e2"))
    x2, y2 = CAL.square_xy(parse_square("e3"))
    assert abs(x1 - x2) == pytest.approx(30) # сусідні ряди
    x3, y3 = CAL.square_xy(parse_square("f2"))
    assert abs(y3 - y1) == pytest.approx(30) # сусідні колонки


def test_quiet_move_sequence():
    arm = DryRunArm(verbose=False)
    Mover(arm, CAL).play(Move("C", parse_square("h2"), parse_square("e2")))
    kinds = [a[0] if a[0] == "suction" else "move" for a in arm.log]
    assert kinds.count("suction") == 2
    assert [a for a in arm.log if a[0] == "suction"] == [("suction", True), ("suction", False)]
    first_on = arm.log.index(("suction", True))
    assert arm.log[first_on - 1][3] == CAL.z_board
    assert all(a[3] == CAL.z_safe for a in arm.log[first_on + 1: first_on + 3])


def test_capture_removes_piece_first():
    arm = DryRunArm(verbose=False)
    move = Move("c", parse_square("b7"), parse_square("b0"), "N")
    Mover(arm, CAL).play(move)
    moves = [a for a in arm.log if a[0] == "move"]
    b0 = CAL.square_xy(parse_square("b0"))
    assert moves[0][1:3] == pytest.approx(b0, abs=0.1)
    assert moves[4][1:3] == pytest.approx(CAL.discard, abs=0.1)
    assert moves[4][3] == CAL.z_board
    assert arm.log.count(("suction", True)) == 2 and arm.log.count(("suction", False)) == 2


def test_bad_calibration_rejected():
    with pytest.raises(ValueError):
        RobotCalibration(corners=[(0, 0)] * 3, z_board=0, z_safe=10, discard=(0, 0))
    with pytest.raises(ValueError):
        RobotCalibration(corners=[(0, 0)] * 4, z_board=10, z_safe=5, discard=(0, 0))


def test_z_safe_defaults_to_z_board_plus_lift():
    cal = RobotCalibration(corners=[(0, 0)] * 4, z_board=-29.0, discard=(0, 0))
    assert cal.z_safe == 21.0  # -29 + 50
    cal = RobotCalibration(corners=[(0, 0)] * 4, z_board=-29.0, discard=(0, 0), lift=40.0)
    assert cal.z_safe == 11.0
    cal = RobotCalibration(corners=[(0, 0)] * 4, z_board=-29.0, discard=(0, 0), z_safe=30.0)
    assert cal.z_safe == 30.0 # явне значення важливіше за lift


#DobotMG400 з підробленою бібліотекою dobot_api (без руки)
import sys
import types as _types


def _install_fake_dobot_api(replies):
    calls = []

    class FakeSocket:
        def __init__(self):
            self.queue = list(replies)

        def recv(self, n):
            return self.queue.pop(0)

    class FakeApi:
        def __init__(self, ip, port):
            self.ip, self.port = ip, port
            self.socket_dobot = FakeSocket()

        def wait_reply(self):
            return str(self.socket_dobot.recv(1024), encoding="utf-8")

        def close(self):
            calls.append(("close", self.port))

    class FakeDashboard(FakeApi):
        def ClearError(self): calls.append("ClearError")
        def EnableRobot(self): calls.append("EnableRobot")
        def DisableRobot(self): calls.append("DisableRobot")
        def SpeedFactor(self, v): calls.append(("SpeedFactor", v))
        poses = []
        idle = (5.0, 5.0, 5.0, 0.0)
        def GetPose(self):
            p = self.poses.pop(0) if self.poses else self.idle
            return "{%f,%f,%f,%f,0.000000,0.000000}" % p

    class FakeMove(FakeApi):
        def MovL(self, x, y, z, r):
            calls.append(("MovL", x, y, z, r))
            return self.wait_reply()

    mod = _types.ModuleType("dobot_api")
    mod.DobotApiDashboard, mod.DobotApiMove = FakeDashboard, FakeMove
    sys.modules["dobot_api"] = mod
    return calls


def test_mg400_survives_non_utf8_reply_and_never_disables_on_close():
    from xiangqi_robot.arm import DobotMG400
    calls = _install_fake_dobot_api([b"\xa0\xb1 error text"])
    try:
        arm = DobotMG400(speed_percent=10, enable_wait_s=0)
        arm.move_to(1, 2, 3, 4)
        assert ("MovL", 1, 2, 3, 4) in calls
        assert arm.last_reply
        arm.close()
        assert "DisableRobot" not in calls
        assert calls.index("EnableRobot") < calls.index(("MovL", 1, 2, 3, 4))
    finally:
        sys.modules.pop("dobot_api", None)


def test_mg400_close_can_disable_when_asked():
    from xiangqi_robot.arm import DobotMG400
    calls = _install_fake_dobot_api([])
    try:
        arm = DobotMG400(enable_wait_s=0)
        arm.close(disable=True)
        assert "DisableRobot" in calls
    finally:
        sys.modules.pop("dobot_api", None)


def test_mg400_retries_connection_and_reports_clearly():
    import time as _t
    from xiangqi_robot.arm import DobotMG400
    calls = _install_fake_dobot_api([])
    mod = sys.modules["dobot_api"]
    original = mod.DobotApiDashboard
    attempts = {"n": 0}

    class Flaky(original):
        def __init__(self, ip, port):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OSError("refused")
            super().__init__(ip, port)

    mod.DobotApiDashboard = Flaky
    sleep = _t.sleep
    _t.sleep = lambda s: None
    try:
        DobotMG400(enable_wait_s=0)
        assert attempts["n"] == 3

        class Dead(original):
            def __init__(self, ip, port):
                raise OSError("refused")

        mod.DobotApiDashboard = Dead
        with pytest.raises(RuntimeError, match="не приймає"):
            DobotMG400(enable_wait_s=0)
    finally:
        _t.sleep = sleep
        sys.modules.pop("dobot_api", None)


def test_mg400_wait_polls_pose_until_target_reached():
    from xiangqi_robot.arm import DobotMG400
    calls = _install_fake_dobot_api([b"\x00" * 1440])
    try:
        arm = DobotMG400(enable_wait_s=0)
        arm.poll_s = 0
        arm.base_s, arm.mm_per_s_per_percent = 0, 1e9
        arm._dash.poses[:] = [(0, 0, 0, 0), (50, 50, -30, 0), (0, 0, 0, 0), (100.2, 200.4, -10.3, 5)]
        arm.move_to(100, 200, -10, 0)
        arm.wait()
        assert arm._dash.poses == []
        assert arm.last_reply == "<feedback packet>"
    finally:
        sys.modules.pop("dobot_api", None)


def test_mg400_wait_times_out_with_clear_message():
    from xiangqi_robot.arm import DobotMG400
    _install_fake_dobot_api([b"\x00" * 1440])
    try:
        arm = DobotMG400(enable_wait_s=0)
        arm.poll_s = 0
        arm.base_s, arm.mm_per_s_per_percent = 0, 1e9
        arm.move_to(100, 200, -10, 0)
        with pytest.raises(RuntimeError, match="не дійшла"):
            arm.wait(timeout=0.05)
    finally:
        sys.modules.pop("dobot_api", None)


def test_mg400_refuses_to_start_when_pose_unavailable():
    from xiangqi_robot.arm import DobotMG400
    mod = _install_fake_dobot_api([])
    mod_dash = sys.modules["dobot_api"].DobotApiDashboard
    mod_dash.idle = (0.0, 0.0, 0.0, 0.0)
    try:
        with pytest.raises(RuntimeError, match="не віддає позу"):
            DobotMG400(enable_wait_s=0, ready_timeout_s=0.1)
    finally:
        mod_dash.idle = (5.0, 5.0, 5.0, 0.0)
        sys.modules.pop("dobot_api", None)


def test_mg400_suction_switches_digital_output():
    from xiangqi_robot.arm import DobotMG400
    _install_fake_dobot_api([b"\x00" * 1440])
    try:
        arm = DobotMG400(enable_wait_s=0, suction_do=2)
        calls = []
        arm._dash.DO = lambda n, v: calls.append((n, v))
        arm.suction(True)
        arm.suction(False)
        assert calls == [(2, 1), (2, 0)]
    finally:
        sys.modules.pop("dobot_api", None)


def test_mover_waits_for_arrival_before_suction_on_and_off():
    from xiangqi_robot.arm import Arm, Mover, RobotCalibration
    events = []

    class Rec(Arm):
        def move_to(self, x, y, z, r=0.0): events.append("move")
        def suction(self, on): events.append("on" if on else "off")
        def wait(self): events.append("wait")

    cal = RobotCalibration(corners=[(0, 0), (80, 0), (80, 90), (0, 90)], z_board=-60, discard=(150, 300))
    Mover(Rec(), cal, grip_delay_s=0).pick_and_place((10, 10), (50, 50))
    for i, e in enumerate(events):
        if e in ("on", "off"):
            assert events[i - 1] == "wait", events


def test_mg400_wait_skips_zero_poses_and_errors_if_no_pose_ever_comes():
    from xiangqi_robot.arm import DobotMG400
    _install_fake_dobot_api([b"\x00" * 1440])
    try:
        arm = DobotMG400(enable_wait_s=0)
        arm.poll_s = 0
        arm.base_s, arm.mm_per_s_per_percent = 0, 1e9
        arm.move_to(100, 200, -10, 0)
        arm._dash.idle = (0.0, 0.0, 0.0, 0.0)
        with pytest.raises(RuntimeError, match="невідомо"):
            arm.wait(timeout=0.05)
    finally:
        sys.modules.pop("dobot_api", None)



def test_mg400_wait_sleeps_estimated_move_time_before_checking_pose(monkeypatch):
    import xiangqi_robot.arm as A
    _install_fake_dobot_api([b"\x00" * 1440] * 2)
    sleeps = []
    try:
        arm = A.DobotMG400(speed_percent=40, enable_wait_s=0)
        monkeypatch.setattr(A.time, "sleep", lambda s: sleeps.append(s))
        arm._dash.idle = (0.0, 0.0, -50.0, 0.0)
        arm.move_to(0, 0, 0, 0)
        arm.move_to(0, 0, -50, 0)
        arm.wait()
        assert sleeps[0] == pytest.approx(arm.base_s + 50 / (40 * arm.mm_per_s_per_percent))
    finally:
        sys.modules.pop("dobot_api", None)


def test_arm_parks_aside_after_move_when_park_is_set(tmp_path):
    cal = RobotCalibration(corners=CAL.corners, z_board=-10.0, z_safe=40.0, discard=(250.0, 220.0), park=(100.0, 400.0))
    arm = DryRunArm(verbose=False)
    Mover(arm, cal).play(Move("C", parse_square("h2"), parse_square("e2")))
    assert arm.log[-1] == ("move", 100.0, 400.0, 40.0)
    path = tmp_path / "c.json"
    cal.save(str(path))
    assert RobotCalibration.load(str(path)).park == (100.0, 400.0)   


def test_arm_does_not_park_when_park_is_not_set():
    arm = DryRunArm(verbose=False)
    Mover(arm, CAL).play(Move("C", parse_square("h2"), parse_square("e2")))
    assert arm.log[-1][1:3] == pytest.approx(CAL.square_xy(parse_square("e2")), abs=0.1)
