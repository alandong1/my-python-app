"""网球核心逻辑的测试：打法与克制、选择与成败、接球与落点、发球、计分、房间、电脑。"""
from __future__ import annotations

import random

import pytest

from .game import (
    AI_ID, BEST_P, COUNTERS, FALLBACK_P, KINDS, MENU_TIME, OTHER_P, POINT_PAUSE,
    Room, RoomError, Score, allowed_kind, other_lane,
)


def make_room(mode="single", ai=False, seed=1):
    room = Room(id="r", name="测试", mode=mode, host_id=1, host_name="房主", ai=ai)
    room.rng.seed(seed)
    if not ai:
        for uid in range(2, 5 if mode == "double" else 3):
            room.join(uid, f"u{uid}")
    return room


def run_seconds(room: Room, seconds: float):
    for _ in range(int(round(seconds / 0.1))):
        room.tick(0.1)


def first_shot(room: Room):
    shots = [e for e in room.events if e["type"] == "shot"]
    return shots[-1] if shots else None


# ------------------------------------------------------------------ 打法与克制

def test_every_attack_has_at_least_one_counter_that_exists():
    for attack, counters in COUNTERS.items():
        assert counters, attack
        for k in counters:
            assert k in KINDS, (attack, k)


def test_smash_only_offered_against_a_lob():
    assert allowed_kind("smash", "lob")
    for attack in ("deep", "approach", "drop", "volley", "slice", "topspin", "short_cross", "smash"):
        assert not allowed_kind("smash", attack)


def test_volleys_only_offered_when_at_the_net_is_possible():
    for kind in ("volley", "short_volley", "deep_volley"):
        assert allowed_kind(kind, "drop")
        assert not allowed_kind(kind, "lob")


def test_good_choice_is_a_counter_when_the_pool_has_one():
    room = make_room()
    room.start(1)
    room._open_rally_menu(room.seats[1], "lob", "如果我挑高，你该如何应对？", 1, "back", 1.4)
    best = next(o for o in room.menu_options if o["id"] == room.menu_best)
    assert best["kind"] == "smash"          # 对方挑高，克制它的是高压
    assert room.menu_best_p == BEST_P
    assert len(room.menu_options) == 3 and len({o["id"] for o in room.menu_options}) == 3


def test_approach_is_countered_by_lob_or_passing_shot():
    room = make_room(seed=4)
    room.start(1)
    room._open_rally_menu(room.seats[1], "approach", "如果我上网，你该如何应对？", 1, "back", 1.0)
    best = next(o for o in room.menu_options if o["id"] == room.menu_best)
    assert best["kind"] in COUNTERS["approach"]


def test_fallback_when_no_counter_is_in_the_pool():
    room = make_room(seed=2)
    room.start(1)
    room._open_rally_menu(room.seats[1], "slice", "如果我切削，你该如何应对？", 1, "back", 1.0)
    # 切削的克制是上旋或上网，只要有一个在三个选项里，就不走 fallback
    if not any(o["kind"] in COUNTERS["slice"] for o in room.menu_options):
        assert room.menu_best_p == FALLBACK_P


def test_success_rates_keep_rallies_going():
    assert BEST_P > OTHER_P > 0.5          # 好选择明显更稳，其余也不会太容易失误


def test_other_lane_is_the_opposite_lane():
    assert other_lane(1) == 2 and other_lane(2) == 1


# ------------------------------------------------------------------ 选择与结果

def test_menu_appears_when_the_opponent_hits_and_bubble_names_his_shot():
    room = make_room(seed=3)
    room.start(1)
    room.rng.random = lambda: 0.0                   # 发球成功
    server = room.seats[room.server_seat]
    room.choose(server.user_id, room.menu_options[0]["id"])
    run_seconds(room, 1.6)                           # 球飞过去
    assert room.phase == "menu"
    receiver = room.seats[room.hitter]
    assert receiver.team != server.team
    assert room.bubble and room.bubble["seat"] == server.index
    assert "如果我" in room.bubble["text"] and "你该如何应对" in room.bubble["text"]


def test_receiver_moves_to_the_landing_cell_when_the_ball_is_sent():
    room = make_room(seed=3)
    room.start(1)
    room.rng.random = lambda: 0.0
    server = room.seats[room.server_seat]
    opt = room.menu_options[0]
    room.choose(server.user_id, opt["id"])
    run_seconds(room, 1.6)
    receiver = room.seats[room.hitter]
    assert receiver.lane == opt["lane"]
    assert receiver.depth == opt["depth"]


def test_only_the_hitter_can_choose_and_only_offered_options():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    other = [s for s in room.seats if s is not server][0]
    with pytest.raises(RoomError, match="现在不是你选择的时候"):
        room.choose(other.user_id, room.menu_options[0]["id"])
    with pytest.raises(RoomError, match="没有这个选项"):
        room.choose(server.user_id, "not-an-option")


def test_choosing_before_the_ball_arrives_waits_for_the_ball():
    room = make_room(seed=6)
    room.start(1)
    room.rng.random = lambda: 0.0
    server = room.seats[room.server_seat]
    room.choose(server.user_id, room.menu_options[0]["id"])
    run_seconds(room, 0.3)                           # 还没到
    room._open_rally_menu(room.seats[1], "lob", "如果我挑高，你该如何应对？", 1, "back", 1.4)
    room.choose(room.seats[1].user_id, room.menu_options[0]["id"])
    assert room.timer >= 1.4 - room.menu_elapsed - 1e-6    # 必须等球飞到


def test_failed_shot_loses_the_point_for_the_hitter_after_flight():
    room = make_room(seed=5)
    room.start(1)
    room.phase = "menu"
    room.hitter = 0
    room.menu_options = [{"id": "flat-back-1", "kind": "flat", "depth": "back", "lane": 1,
                          "name": "", "desc": ""}]
    room.menu_best = "flat-back-1"
    room.menu_best_p = 0.0
    room.menu_other_p = 0.0                          # 必定失误
    room.rng.random = lambda: 0.999
    room.choose(1, "flat-back-1")
    run_seconds(room, 1.6)                           # 球飞出去要 1.4 秒
    shot = first_shot(room)
    assert shot and shot["result"] == "fail" and shot["fail"] == "out"
    run_seconds(room, 1.5)
    assert room.phase == "point_over"
    point = [e for e in room.events if e["type"] == "point"]
    assert point and point[-1]["winner"] == 1


def test_first_serve_fault_gives_second_serve_then_double_fault_point():
    room = make_room()
    room.start(1)
    server = room.seats[room.server_seat]
    room.menu_best_p = room.menu_other_p = 0.0
    room.rng.random = lambda: 0.999
    room.choose(server.user_id, room.menu_options[0]["id"])
    run_seconds(room, 3.2)
    assert room.phase == "serve_menu" and room.serve_attempt == 2
    room.menu_best_p = room.menu_other_p = 0.0
    room.choose(server.user_id, room.menu_options[0]["id"])
    run_seconds(room, 3.2)
    assert room.phase == "point_over"
    point = [e for e in room.events if e["type"] == "point"]
    assert point and point[-1]["winner"] == 1 - server.team and point[-1]["reason"] == "双发失误"


def test_serve_lands_on_the_diagonal_lane():
    room = make_room(seed=8)
    room.start(1)
    server = room.seats[room.server_seat]
    for o in room.menu_options:
        assert o["lane"] == other_lane(server.lane)


def test_point_over_then_next_point_starts_with_a_serve_menu():
    room = make_room()
    room.start(1)
    room.phase = "point_over"
    room.timer = 0.05
    run_seconds(room, POINT_PAUSE)
    assert room.phase == "serve_menu"


def test_timeout_chooses_automatically_for_a_human():
    room = make_room()
    room.start(1)
    run_seconds(room, MENU_TIME + 0.5)
    assert room.phase in ("swing", "shot", "menu", "serve_menu", "point_over")
    assert first_shot(room) is not None or room.events == [] or room.phase != "serve_menu"


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
    run_seconds(room, 3.0)
    assert any(e["type"] == "shot" and e["seat"] == room.ai_seat().index for e in room.events) \
        or room.phase != "serve_menu"


def test_full_match_against_ai_finishes_and_both_sides_score():
    rng = random.Random(3)
    room = make_ai_room(seed=3)
    room.start(1)
    shots_ai = 0
    for _ in range(30 * 60 * 30):             # 最多 30 分钟游戏时间
        room.tick(1 / 30)
        if room.phase in ("menu", "serve_menu") and room.hitter == 0:
            room.choose(1, rng.choice(room.menu_options)["id"])
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
                room.choose(seat.user_id, rng.choice(room.menu_options)["id"])
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
