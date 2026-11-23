"""突击行动的游戏逻辑：移动、碰撞、射线、开火、爆头、掩体、射速、复活、输入防作弊。"""
import math
import random

import pytest

from projects.strike import config as C
from projects.strike.game import Arena, direction, move, ray_box


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def arena(clock):
    return Arena(clock=clock, rng=random.Random(1))


def place(p, x, z, yaw=0.0, pitch=0.0):
    p.x, p.z, p.yaw, p.pitch = float(x), float(z), yaw, pitch


# ---------------------------------------------------------------- 移动

OPEN = (0.0, 20.0)   # 远离中央柱子和箱子的空地（中央柱子在原点附近，会挡住移动）


def test_forward_is_negative_z_and_right_is_positive_x():
    x, z = move(*OPEN, 1.0, 0.0, 0.0, 0.1)
    assert x == pytest.approx(0.0) and z < OPEN[1]
    x, z = move(*OPEN, 0.0, 1.0, 0.0, 0.1)
    assert x > 0 and z == pytest.approx(OPEN[1])


def test_yaw_rotates_forward_direction():
    # 转 90 度（yaw=π/2）后，前进方向应该是 -x
    x, z = move(*OPEN, 1.0, 0.0, math.pi / 2, 0.1)
    assert x < 0 and z == pytest.approx(OPEN[1], abs=1e-9)


def test_diagonal_is_not_faster_than_straight():
    x1, z1 = move(*OPEN, 1.0, 0.0, 0.0, 0.1)
    x2, z2 = move(*OPEN, 1.0, 1.0, 0.0, 0.1)
    assert math.hypot(x2 - OPEN[0], z2 - OPEN[1]) == pytest.approx(math.hypot(x1 - OPEN[0], z1 - OPEN[1]))


def test_dt_is_capped_so_a_lag_spike_cannot_teleport():
    x, z = move(*OPEN, 1.0, 0.0, 0.0, 50.0)
    assert math.hypot(x - OPEN[0], z - OPEN[1]) == pytest.approx(C.MOVE_SPEED * C.MAX_DT)


def test_wall_blocks_movement_and_player_slides_along_it():
    wall = [[-4.0, 0.0, 6.0, 4.0, 1.2, 8.0]]     # 箱子：z 在 6–8 之间
    z = 9.0
    for _ in range(30):                           # 朝 -z 一直往箱子走
        _, z = move(0.0, z, 1.0, 0.0, 0.0, 0.1, walls=wall)
    assert z >= 8.0                               # 停在箱子外面
    # 斜着走：朝墙的方向被挡住，但沿着墙的方向还能动（滑墙）。只走 8 步，还在箱子的宽度之内
    x, z = 0.0, 9.0
    for _ in range(8):
        x, z = move(x, z, 1.0, 1.0, 0.0, 0.1, walls=wall)
    assert 0.5 < x < 4.0 and z >= 8.0


def test_player_stays_inside_arena():
    x, z = OPEN
    for _ in range(1000):
        x, z = move(x, z, 0.0, 1.0, 0.0, 0.1)
    assert x == pytest.approx(C.ARENA_HALF - C.PLAYER_RADIUS)


def test_no_walls_overlap_spawn_points():
    for sx, sz in C.SPAWNS:
        for x0, _, z0, x1, _, z1 in C.WALLS:
            assert not (x0 - 2 < sx < x1 + 2 and z0 - 2 < sz < z1 + 2), (sx, sz)


# ---------------------------------------------------------------- 射线

def test_ray_hits_box_at_expected_distance():
    assert ray_box((0, 0, 0), (1, 0, 0), (5, 0, -1), (6, 2, 1)) == pytest.approx(5.0)


def test_ray_misses_box_beside_it():
    assert ray_box((0, 0, 0), (1, 0, 0), (5, 0, 2), (6, 2, 3)) is None


def test_ray_from_inside_box_returns_zero():
    assert ray_box((5.5, 1, 0), (1, 0, 0), (5, 0, -1), (6, 2, 1)) == 0.0


def test_direction_is_unit_and_pitch_up_is_positive_y():
    d = direction(0.3, 0.5)
    assert math.sqrt(sum(v * v for v in d)) == pytest.approx(1.0)
    assert d[1] > 0
    assert direction(0.0, 0.0) == pytest.approx((0.0, 0.0, -1.0))


# ---------------------------------------------------------------- 开火

def two_players(arena, clock, dz=10.0):
    """甲、乙面对面，都在 x=8 这条线上（这条线上没有障碍物）。甲在 z=0，乙在 z=-dz。"""
    a = arena.add_player("甲")
    b = arena.add_player("乙")
    place(a, 8.0, 0.0)
    place(b, 8.0, -dz)
    return a, b


def test_body_shot_does_25_damage(arena, clock):
    a, b = two_players(arena, clock)
    a.pitch = math.atan2(1.0 - C.EYE_HEIGHT, 10.0)   # 瞄准约 1 米高的身体
    arena.fire(a.id)
    assert b.hp == C.MAX_HP - C.BODY_DAMAGE
    hits = [e for e in arena.take_events() if e["e"] == "hit"]
    assert len(hits) == 1 and hits[0]["head"] is False


def test_headshot_kills_and_counts(arena, clock):
    a, b = two_players(arena, clock)
    a.pitch = 0.0                                  # 眼睛高度 1.6 米，正好打在头部
    arena.fire(a.id)
    assert b.hp == 0 and not b.alive
    assert a.kills == 1 and b.deaths == 1
    kills = [e for e in arena.take_events() if e["e"] == "kill"]
    assert kills and kills[0]["head"] is True and kills[0]["by"] == a.id


def test_wall_blocks_the_shot(arena, clock):
    # 中央柱子 [-1,1]×[-1,1]，高 2.5 米，挡在两人中间（甲在 z=5，乙在 z=-5，都在 x=0）
    a = arena.add_player("甲")
    b = arena.add_player("乙")
    place(a, 0.0, 5.0)
    place(b, 0.0, -5.0)
    a.pitch = math.atan2(1.0 - C.EYE_HEIGHT, 10.0)
    arena.fire(a.id)
    assert b.hp == C.MAX_HP
    assert not [e for e in arena.take_events() if e["e"] == "hit"]


def test_low_crate_blocks_low_shots_but_not_high_ones(arena, clock):
    # 中间的箱子 [-4,4]×[6,8]，高 1.2 米。甲在 z=12，乙在 z=2，子弹经过箱子时的高度是两者的中点
    a = arena.add_player("甲")
    b = arena.add_player("乙")
    place(a, 0.0, 12.0)
    place(b, 0.0, 2.0)
    a.pitch = math.atan2(0.5 - C.EYE_HEIGHT, 10.0)   # 子弹经过箱子时约 1.05 米，被挡住
    arena.fire(a.id)
    assert b.hp == C.MAX_HP
    clock.t += C.FIRE_INTERVAL
    a.pitch = math.atan2(1.0 - C.EYE_HEIGHT, 10.0)   # 子弹经过箱子时约 1.3 米，从箱子上方飞过
    arena.fire(a.id)
    assert b.hp == C.MAX_HP - C.BODY_DAMAGE


def test_fire_rate_limit(arena, clock):
    a, b = two_players(arena, clock)
    a.pitch = math.atan2(1.0 - C.EYE_HEIGHT, 10.0)
    arena.fire(a.id)
    arena.fire(a.id)                               # 同一时刻，超过射速，应被忽略
    shots = [e for e in arena.take_events() if e["e"] == "shot"]
    assert len(shots) == 1
    clock.t += C.FIRE_INTERVAL
    arena.fire(a.id)
    assert len([e for e in arena.take_events() if e["e"] == "shot"]) == 1


def test_dead_players_cannot_fire_or_be_hit(arena, clock):
    a, b = two_players(arena, clock)
    b.alive = False
    arena.fire(a.id)
    assert b.hp == C.MAX_HP
    assert not [e for e in arena.take_events() if e["e"] == "hit"]
    a.alive = False
    clock.t += C.FIRE_INTERVAL
    arena.fire(a.id)
    assert not [e for e in arena.take_events() if e["e"] == "shot"]


# ---------------------------------------------------------------- 复活与出生点

def test_respawn_after_delay(arena, clock):
    a, b = two_players(arena, clock)
    a.pitch = 0.0
    arena.fire(a.id)
    assert not b.alive
    clock.t += C.RESPAWN_SECONDS - 0.1
    arena.tick()
    assert not b.alive
    clock.t += 0.2
    arena.tick()
    assert b.alive and b.hp == C.MAX_HP


def test_spawn_prefers_point_far_from_living_enemies(arena, clock):
    enemy = arena.add_player("敌")
    place(enemy, 24.0, 24.0)
    p = arena.add_player("新人")
    assert math.hypot(p.x - 24.0, p.z - 24.0) >= 40.0


def test_room_full_is_refused(arena, clock):
    for i in range(C.MAX_PLAYERS):
        arena.add_player(f"p{i}")
    with pytest.raises(ValueError):
        arena.add_player("多余的人")


# ---------------------------------------------------------------- 输入（防作弊）

def test_old_or_repeated_inputs_are_ignored(arena, clock):
    a = arena.add_player("甲")
    place(a, *OPEN)
    clock.t += 1
    arena.input(a.id, seq=5, fwd=0, side=0, yaw=0.0, pitch=0.0, dt=0.0)
    arena.input(a.id, seq=3, fwd=1, side=0, yaw=0.0, pitch=0.0, dt=0.1)
    assert a.ack == 5 and a.z == OPEN[1]


def test_input_speed_is_limited_by_real_elapsed_time(arena, clock):
    """客户端发送很多 dt=0.1 的消息，但真实时间没有过去，服务器只允许走一小段。"""
    a = arena.add_player("甲")
    place(a, *OPEN)
    start = (a.x, a.z)
    for seq in range(1, 51):
        arena.input(a.id, seq=seq, fwd=1, side=0, yaw=0.0, pitch=0.0, dt=0.1)
    assert math.hypot(a.x - start[0], a.z - start[1]) <= C.MAX_INPUT_BUDGET * C.MOVE_SPEED + 1e-6


def test_pitch_is_clamped(arena, clock):
    a = arena.add_player("甲")
    clock.t += 1
    arena.input(a.id, seq=1, fwd=0, side=0, yaw=0.0, pitch=99.0, dt=0.0)
    assert a.pitch == C.MAX_PITCH


def test_take_events_clears_queue(arena, clock):
    a, b = two_players(arena, clock)
    a.pitch = 0.0
    arena.fire(a.id)
    assert arena.take_events()
    assert arena.take_events() == []
