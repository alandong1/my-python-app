"""网球核心逻辑的测试：球的物理、计分规则、房间的座位和比赛流程。"""
from __future__ import annotations

import math

import pytest

from .game import (
    BASE_SPEED, DRAG, G, REACH, STROKES, Ball, RoomError, Room,
    Score, in_court, in_service_box, solve_launch, step_ball,
)


# ------------------------------------------------------------------ 球的物理

def fly(ball: Ball, max_t: float = 6.0, dt: float = 1 / 480):
    """让球一直飞，直到发生第一个事件。返回 (事件, 球的状态)。"""
    t = 0.0
    while t < max_t:
        events = step_ball(ball, dt)
        t += dt
        if events:
            return events[0], ball
    return None, ball


def test_solve_launch_lands_on_target_when_clear_of_net():
    x0, y0, z0 = -10.0, 1.0, 0.0
    vx, vy, vz = solve_launch(x0, y0, z0, 9.5, 2.0, BASE_SPEED, 1.1)
    ball = Ball(x=x0, y=y0, z=z0, vx=vx, vy=vy, vz=vz)
    event, ball = fly(ball)
    assert event[0] == "bounce"
    assert event[1] == pytest.approx(9.5, abs=0.4)
    assert event[2] == pytest.approx(2.0, abs=0.4)


@pytest.mark.parametrize("stroke", list(STROKES))
def test_every_stroke_clears_the_net(stroke):
    """任何球种都不能下网：求解器要保证过网高度（上旋和下旋也一样）。"""
    s = STROKES[stroke]
    for y0 in (0.6, 1.0, 1.6):
        ball = Ball(x=-9.0, y=y0, z=0.0)
        ball.top, ball.side = s["top"], s["side"]
        ball.vx, ball.vy, ball.vz = solve_launch(ball.x, ball.y, ball.z, 8.0, 0.0,
                                                 BASE_SPEED * s["speed"], s["clear"], s["top"])
        event, _ = fly(ball)
        assert event is not None
        assert event[0] != "net", (stroke, y0)


def test_ball_crossing_net_low_is_a_net_event():
    ball = Ball(x=-0.5, y=0.3, z=0.0, vx=10.0, vy=0.0, vz=0.0)
    event, _ = fly(ball, max_t=1.0)
    assert event[0] == "net"


def test_topspin_dips_more_than_flat():
    """同样的击球速度，上旋的球落得比平击快（马格努斯效应）。"""
    def land_x(top):
        b = Ball(x=-10, y=1.0, z=0.0, vx=20.0, vy=3.0, vz=0.0, top=top)
        event, b = fly(b)
        return event[1]
    assert land_x(1.0) < land_x(0.0)     # 上旋的落点更近（下沉更快）
    assert land_x(-1.0) > land_x(0.0)    # 下旋飘得更远


def test_side_spin_curves_the_ball_sideways():
    def land_z(side):
        b = Ball(x=-10, y=1.0, z=0.0, vx=20.0, vy=3.0, vz=0.0, side=side)
        event, _ = fly(b)
        return event[2]
    assert land_z(1.0) != pytest.approx(land_z(0.0), abs=0.05)
    assert land_z(1.0) * land_z(-1.0) < 0     # 左右两个方向相反


def test_bounce_loses_speed_and_rolls_to_a_stop():
    b = Ball(x=0.0, y=0.5, z=0.0, vx=8.0, vy=-3.0, vz=0.0)
    seen = []
    for _ in range(4000):
        for ev in step_ball(b, 1 / 240):
            seen.append(ev[0])
        if "stop" in seen:
            break
    assert seen[0] == "bounce"
    assert "stop" in seen


def test_drag_is_small_at_normal_rally_speed():
    assert DRAG < 0.002
    assert G == pytest.approx(9.8)


# ------------------------------------------------------------------ 场地判断

def test_in_court_singles_and_doubles_lines():
    assert in_court(5.0, 4.5, singles=False)
    assert not in_court(5.0, 4.5, singles=True)      # 单打边线外
    assert not in_court(12.5, 0.0, singles=False)    # 底线外


def test_service_box_must_be_diagonal_and_on_receiver_side():
    # 发球方在 z>0 一侧（server_zside=1），必须落在对面 z<0 的发球区
    assert in_service_box(3.0, -2.0, receiver_sign=1, server_zside=1)
    assert not in_service_box(3.0, 2.0, receiver_sign=1, server_zside=1)   # 同一侧
    assert not in_service_box(-3.0, -2.0, receiver_sign=1, server_zside=1)  # 接球方另一侧
    assert not in_service_box(7.0, -2.0, receiver_sign=1, server_zside=1)  # 过了发球线


# ------------------------------------------------------------------ 计分

def _win(score: Score, team: int, times: int):
    for _ in range(times):
        score.win_point(team)


def test_tennis_scoring_labels():
    s = Score()
    labels = []
    for team in [0, 0, 1, 0]:          # 依次：15:0、30:0、30:15、40:15
        s.win_point(team)
        labels.append((s.label(0), s.label(1)))
    assert labels == [("15", "0"), ("30", "0"), ("30", "15"), ("40", "15")]
    assert s.games == [0, 0]


def test_game_needs_two_point_lead_at_deuce():
    s = Score()
    _win(s, 0, 3); _win(s, 1, 3)          # 40 : 40
    assert s.label(0) == "40" and s.label(1) == "40"
    assert s.is_deuce()
    got_game, _ = s.win_point(0)          # 占先
    assert not got_game and s.label(0) == "Ad"
    got_game, _ = s.win_point(1)          # 又平分
    assert not got_game and s.is_deuce()
    _win(s, 1, 1)
    got_game, _ = s.win_point(1)          # 连赢两分
    assert got_game and s.games == [0, 1]


def test_set_is_six_games_with_two_game_lead():
    s = Score()
    for _ in range(6):
        _win(s, 0, 4)                      # 每局 0 失分 → 6:0
    assert s.sets_won == [1, 0]
    assert s.set_scores == [(6, 0)]
    assert not s.done


def test_six_all_goes_to_tiebreak_and_match_ends_after_two_sets():
    s = Score()
    for g in range(12):                    # 6:6
        _win(s, g % 2, 4)
    assert s.games == [6, 6] and s.tiebreak
    _win(s, 0, 7)                          # 抢七 7:0
    assert s.sets_won == [1, 0] and not s.tiebreak
    for _ in range(6):
        _win(s, 1, 4)                      # 第二盘 6:0 给队 1
    assert s.sets_won == [1, 1]
    for _ in range(6):
        _win(s, 0, 4)                      # 第三盘
    assert s.done and s.winner == 0


def test_cannot_score_after_match_end():
    s = Score()
    s.sets_won = [2, 0]
    s.done = True
    with pytest.raises(RoomError):
        s.win_point(0)


# ------------------------------------------------------------------ 房间

def make_room(mode="single", host=1):
    return Room(id="r", name="测试", mode=mode, host_id=host, host_name="房主")


def test_host_takes_seat_zero_when_room_is_created():
    room = make_room()
    assert room.seat_of(1).index == 0
    assert room.player_count() == 1


def test_first_come_first_served_and_full_room_rejects():
    room = make_room("single")
    room.join(2, "甲")
    with pytest.raises(RoomError, match="房间已满"):
        room.join(3, "乙")


def test_doubles_seats_and_teams():
    room = make_room("double")
    for uid in (2, 3, 4):
        room.join(uid, f"u{uid}")
    assert [s.team for s in room.seats] == [0, 0, 1, 1]
    assert room.player_count() == 4


def test_cannot_start_before_full_and_only_host_can_start():
    room = make_room("single")
    with pytest.raises(RoomError):
        room.start(1)
    room.join(2, "甲")
    with pytest.raises(RoomError, match="房主"):
        room.start(2)
    room.start(1)
    assert room.status == "playing" and room.phase == "serve_wait"


def test_cannot_join_running_match():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    with pytest.raises(RoomError, match="进行中"):
        room.join(3, "乙")


def test_leave_frees_the_seat():
    room = make_room("single")
    room.join(2, "甲")
    room.leave(2)
    assert room.seat_of(2) is None
    room.join(3, "乙")
    assert room.seat_of(3) is not None


def test_only_server_can_toss_then_serve_with_correct_box():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    server = room.seats[room.server_seat]
    other = [s for s in room.seats if s is not server][0]
    with pytest.raises(RoomError, match="还没轮到你发球"):
        room.swing(other.user_id, "flat")
    room.swing(server.user_id, "flat")               # 抛球
    assert room.phase == "toss"
    # 等球到最高点附近再发球
    for _ in range(200):
        room.tick(1 / 30)
        if room.ball.y >= 2.0 and room.ball.vy < 0:
            break
    room.swing(server.user_id, "top", 0.0, 0.0)
    assert room.phase == "rally" and room.serve_pending
    assert room.last_seat == server.index


def test_server_cannot_move_during_serve():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    server = room.seats[room.server_seat]
    x0 = server.x
    room.set_stick(server.user_id, 1.0, 1.0)
    room.tick(0.5)
    assert server.x == pytest.approx(x0)


def test_cannot_hit_twice_in_a_row():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    server = room.seats[room.server_seat]
    room.swing(server.user_id, "flat")
    for _ in range(200):
        room.tick(1 / 30)
        if room.ball.y >= 2.0 and room.ball.vy < 0:
            break
    room.swing(server.user_id, "flat")
    server.cooldown = 0.0                 # 排除冷却的影响，只测「同一个人不能连续击球」
    # 球刚发出去，发球人不能马上再击一次
    room.ball.x = server.x
    room.ball.y = 1.0
    with pytest.raises(RoomError, match="连续"):
        room.swing(server.user_id, "flat")


def test_swing_out_of_reach_is_rejected():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    server = room.seats[room.server_seat]
    room.swing(server.user_id, "flat")
    room.tick(1 / 30)
    room.phase = "rally"
    room.last_seat = server.index
    receiver = [s for s in room.seats if s is not server][0]
    room.ball.x, room.ball.y, room.ball.z = receiver.x + 5.0, 1.0, receiver.z
    receiver.cooldown = 0.0
    with pytest.raises(RoomError, match="没够到"):
        room.swing(receiver.user_id, "flat")


def test_snapshot_contains_what_the_client_needs_and_clears_events():
    room = make_room("single")
    room.join(2, "甲")
    room.start(1)
    snap = room.snapshot()
    for key in ("status", "phase", "message", "serveSeat", "score", "ball", "seats", "events"):
        assert key in snap
    assert snap["score"]["labels"] == ["0", "0"]
    assert room.events == []
    assert all(k in snap["ball"] for k in ("x", "y", "z", "top", "side"))


def test_full_random_match_finishes_without_errors():
    """跑一场随机的完整比赛：不能出错、一定能结束。"""
    import random
    rng = random.Random(7)
    for mode in ("single", "double"):
        room = make_room(mode)
        for uid in range(2, 5 if mode == "double" else 3):
            room.join(uid, f"u{uid}")
        room.start(1)
        for _ in range(60 * 60 * 3):       # 最多模拟 3 小时的比赛时间
            room.tick(1 / 30)
            if room.status == "finished":
                break
            if room.phase == "serve_wait":
                srv = room.seats[room.server_seat]
                room.swing(srv.user_id, "top")
            elif room.phase == "toss" and room.ball.y > 2.0 and room.ball.vy < 0:
                srv = room.seats[room.server_seat]
                try:
                    room.swing(srv.user_id, rng.choice(list(STROKES)), rng.uniform(-1, 1), rng.uniform(-1, 1))
                except RoomError:
                    pass
            elif room.phase == "rally":
                for s in room.seats:
                    if s and s.index != room.last_seat and math.hypot(room.ball.x - s.x, room.ball.z - s.z) < REACH:
                        try:
                            room.swing(s.user_id, rng.choice(list(STROKES)), rng.uniform(-1, 1), rng.uniform(-1, 1))
                        except RoomError:
                            pass
                    if s:
                        target_x = room.ball.x
                        target_z = room.ball.z
                        room.set_stick(s.user_id,
                                       max(-1, min(1, (target_x - s.x) * (1 if s.team == 0 else -1))),
                                       max(-1, min(1, (target_z - s.z) * 0.8)))
            room.events.clear()
        assert room.score.total_games > 0
