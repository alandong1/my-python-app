"""网球核心逻辑的测试：选项与局面、选择与成败、发球与失误、计分、房间座位、电脑。"""
from __future__ import annotations

import random

import pytest

from .game import (
    AI_ID, BEST_P, FALLBACK_P, MENU_TIME, OPTIONS, POOLS, POINT_PAUSE, SERVE_IDS, SHOT_TIME,
    Room, RoomError, Score, tactical_best,
)


def make_room(mode="single", ai=False, seed=1):
    room = Room(id="r", name="测试", mode=mode, host_id=1, host_name="房主", ai=ai)
    room.rng.seed(seed)
    if not ai:
        for uid in range(2, 5 if mode == "double" else 3):
            room.join(uid, f"u{uid}")
    return room


def finish_animation(room: Room):
    """把击球动画跑完（服务器每帧会做的事）。"""
    room.tick(SHOT_TIME + 0.01)


def wait_for_menu(room: Room, phase=("menu", "serve_menu")):
    for _ in range(int(60 / 0.1)):
        if room.phase in phase:
            return
        room.tick(0.1)
    raise AssertionError(f"没有进入 {phase}，现在是 {room.phase}")


def make_menu_for(room: Room, situation: str, opp_zone: str = "back"):
    """直接给击球方一个指定局面的菜单（测试用）。"""
    room._open_rally_menu(room.hitter if room.hitter is not None else 0, situation, opp_zone)


# ------------------------------------------------------------------ 选项与局面

def test_tactical_best_matches_opponent_position():
    assert tactical_best("deep", "net") == "lob"
    assert tactical_best("deep", "back") == "drop"
    assert tactical_best("deep", "mid") == "flat"
    assert tactical_best("short", "back") == "volley"
    assert tactical_best("lob", "net") == "smash"


@pytest.mark.parametrize("situation,opp", [("deep", "net"), ("deep", "back"), ("deep", "mid"),
                                           ("short", "back"), ("lob", "mid")])
def test_menu_has_three_options_and_the_best_one_is_among_them(situation, opp):
    room = make_room()
    room.start(1)
    room.phase = "menu"
    room._build_menu(situation, opp)
    assert len(room.menu_options) == 3
    assert len(set(room.menu_options)) == 3
    assert all(o in POOLS[situation] for o in room.menu_options)
    best = tactical_best(situation, opp)
    if best is not None:
        assert room.menu_best == best and room.menu_best in room.menu_options
        assert room.menu_best_p == BEST_P
    else:
        assert room.menu_best in room.menu_options and room.menu_best_p == FALLBACK_P


def test_serve_menu_offers_the_three_serves():
    room = make_room()
    room.start(1)
    assert room.phase == "serve_menu"
    assert sorted(room.menu_options) == sorted(SERVE_IDS)


# ------------------------------------------------------------------ 选择与结果

def test_only_the_hitter_can_choose_and_only_offered_options():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    other = [s for s in room.seats if s is not server][0]
    with pytest.raises(RoomError, match="现在不是你选择的时候"):
        room.choose(other.user_id, room.menu_options[0])
    with pytest.raises(RoomError, match="没有这个选项"):
        room.choose(server.user_id, "smash")


def test_choosing_moves_the_hitter_to_the_option_zone():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    option = room.menu_options[0]
    room.choose(server.user_id, option)
    assert room.phase == "animating"
    assert server.zone == OPTIONS[option]["zone"]


def test_failed_shot_loses_the_point_for_the_hitter_after_animation():
    room = make_room(seed=5)
    room.start(1)
    room.phase = "menu"                      # 直接进入一次对打（不是发球）
    room.hitter = 0
    room.menu_options = ["flat", "top", "slice"]
    room.menu_best, room.menu_best_p = "flat", BEST_P
    room.rng.random = lambda: 0.999          # 强制失败
    room.choose(1, "flat")                   # 深球打出界
    ev = [e for e in room.events if e["type"] == "shot"][-1]
    assert ev["result"] == "fail" and ev["fail"] == "out"
    assert room.score.points == [0, 0]       # 动画还没结束，还没得分
    finish_animation(room)
    assert room.phase == "point_over"
    point = [e for e in room.events if e["type"] == "point"]
    assert point and point[-1]["winner"] == 1      # 击球的是队 0，所以队 1 得分


def test_successful_shot_passes_the_ball_to_the_other_side():
    room = make_room(seed=7)
    room.start(1)
    room.rng.random = lambda: 0.0            # 强制成功
    server = room.seats[room.server_seat]
    option = OPTIONS[room.menu_options[0]]
    room.choose(server.user_id, room.menu_options[0])
    finish_animation(room)
    assert room.phase == "menu"
    assert room.hitter is not None
    receiver = room.seats[room.hitter]
    assert receiver.team != server.team
    assert room.menu_opp_zone == option["zone"]


def test_winner_scores_immediately_for_the_hitter():
    room = make_room(seed=9)
    room.start(1)
    room.phase = "menu"
    room.hitter = 0
    room.menu_options = ["volley", "drop", "lob"]
    room.menu_best, room.menu_best_p = "volley", 1.0
    room.rng.random = lambda: 0.0            # 成功，且直接得分（0 < WINNER_P）
    room.choose(1, "volley")
    finish_animation(room)
    point = [e for e in room.events if e["type"] == "point"]
    assert point and point[-1]["winner"] == 0 and "直接得分" in point[-1]["reason"]


def test_first_serve_fault_gives_second_serve_then_double_fault_point():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    room.rng.random = lambda: 0.999          # 发球失误
    room.choose(server.user_id, room.menu_options[0])
    finish_animation(room)
    assert room.phase == "serve_menu" and room.serve_attempt == 2
    room.choose(server.user_id, room.menu_options[0])
    finish_animation(room)
    assert room.phase == "point_over"
    point = [e for e in room.events if e["type"] == "point"]
    assert point and point[-1]["winner"] == 1 - server.team and point[-1]["reason"] == "双发失误"


def test_point_over_then_next_point_starts_with_a_serve_menu():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    room.rng.random = lambda: 0.999
    room.choose(server.user_id, room.menu_options[0])
    room.serve_attempt = 2                   # 直接按双发失误算
    room.pending = (1 - server.team, "测试")
    finish_animation(room)
    assert room.phase == "point_over"
    room.tick(POINT_PAUSE + 0.05)
    assert room.phase == "serve_menu"


def test_timeout_chooses_automatically_for_a_human():
    room = make_room()
    room.start(1)
    room.tick(MENU_TIME + 0.1)               # 超过选择时限
    assert room.phase == "animating"         # 自动选了一个，进入击球动画
    assert [e for e in room.events if e["type"] == "shot"]


# ------------------------------------------------------------------ 计分（规则保持不变）

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

def test_host_takes_seat_zero_and_first_come_first_served():
    room = make_room()
    assert room.seat_of(1).index == 0
    with pytest.raises(RoomError, match="房间已满"):
        room.join(9, "多余的人")


def test_doubles_seats_and_teams():
    room = make_room("double")
    assert [s.team for s in room.seats] == [0, 0, 1, 1]


def test_cannot_start_before_full_and_only_host_can_start():
    room = Room(id="r", name="x", mode="single", host_id=1, host_name="a")
    with pytest.raises(RoomError):
        room.start(1)
    room.join(2, "甲")
    with pytest.raises(RoomError, match="房主"):
        room.start(2)
    room.start(1)
    assert room.status == "playing"


def test_cannot_join_running_match():
    room = make_room()
    room.start(1)
    with pytest.raises(RoomError, match="进行中"):
        room.join(9, "乙")


# ------------------------------------------------------------------ 电脑

def make_ai_room(seed=1):
    return make_room(ai=True, seed=seed)


def test_ai_room_is_full_single_and_has_ai_seat():
    room = make_ai_room()
    assert room.player_count() == 2
    seat = room.ai_seat()
    assert seat is not None and seat.is_ai and seat.team == 1 and seat.user_id == AI_ID
    with pytest.raises(RoomError, match="只支持单打"):
        Room(id="x", name="x", mode="double", host_id=1, host_name="a", ai=True)


def test_ai_chooses_by_itself_when_it_is_its_turn():
    room = make_ai_room()
    room.start(1)
    room.score.total_games = 1
    room._next_point()                       # 第二局轮到电脑发球
    assert room.hitter == room.ai_seat().index
    for _ in range(int(3 / 0.1)):
        room.tick(0.1)
        if any(e["type"] == "shot" and e["seat"] == room.ai_seat().index for e in room.events):
            break
        room.events.clear()
    assert any(e["type"] == "shot" and e["seat"] == room.ai_seat().index for e in room.events)


def test_full_match_against_ai_finishes_and_both_sides_score():
    rng = random.Random(3)
    room = make_ai_room(seed=3)
    room.start(1)
    shots_ai = 0
    for _ in range(30 * 60 * 30):             # 最多 30 分钟游戏时间
        room.tick(1 / 30)
        if room.phase in ("menu", "serve_menu") and room.hitter == 0:
            room.choose(1, rng.choice(room.menu_options))
        for e in room.events:
            if e["type"] == "shot" and e["seat"] == room.ai_seat().index:
                shots_ai += 1
        room.events.clear()
        if room.status == "finished":
            break
    assert room.status == "finished"
    assert shots_ai > 20


def test_full_random_doubles_match_finishes_without_errors():
    rng = random.Random(7)
    room = make_room("double", seed=7)
    room.start(1)
    for _ in range(30 * 60 * 30):
        room.tick(1 / 30)
        if room.phase in ("menu", "serve_menu") and room.hitter is not None:
            seat = room.seats[room.hitter]
            if not seat.is_ai:
                room.choose(seat.user_id, rng.choice(room.menu_options))
        room.events.clear()
        if room.status == "finished":
            break
    assert room.status == "finished"


def test_snapshot_has_menu_for_client_and_clears_events():
    room = make_room()
    room.start(1)
    snap = room.snapshot()
    for key in ("status", "phase", "message", "serveSeat", "hitter", "score", "menu", "seats", "events"):
        assert key in snap
    assert snap["menu"] and len(snap["menu"]["options"]) == 3
    assert room.events == []
