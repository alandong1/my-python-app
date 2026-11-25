"""一局湖北卡五星（三人）的流程：两门数牌加中发白、碰、杠、和牌、屁胡规则、流局，以及电脑对打时牌数守恒。"""
import random

import pytest

from projects.mahjong import ai
from projects.mahjong import rules as R
from projects.mahjong.engine import GameError, Match, Round


def set_hands(r, hands):
    """把每家的手牌换成指定的牌种列表（用于构造测试场景）。"""
    for s in range(3):
        r.hands[s] = R.counts_of(hands[s])
        r.melds[s] = []
        r.discards[s] = []
    r.phase = "discard"
    r.pending = {}
    r.responses = {}
    r.last = None


def total_tiles(r):
    n = sum(sum(h) for h in r.hands) + len(r.wall) + sum(len(d) for d in r.discards)
    for seat in r.melds:
        for m in seat:
            n += 3 if m["type"] == "pong" else 4
    return n


def answer(r, actions):
    """按字典回应 claim 阶段，没写的人一律过。"""
    for t in list(r.pending):
        if r.phase != "claim":
            break
        if t not in r.responses:
            r.respond(t, actions.get(t, "pass"))


def pinghu_waiting_on_fa():
    """屁胡听发（13 张，没有五）：123万 789万 111条 中中中 + 发。"""
    return [0, 1, 2, 6, 7, 8, 9, 9, 9, 27, 27, 27, 28]


def test_wall_has_two_suits_and_honors_only():
    for seed in range(20):
        r = Round(0, random.Random(seed))
        assert len(r.suits) == 2
        assert total_tiles(r) == 2 * 36 + 12
        kinds = set(r.wall) | {k for h in r.hands for k in R.expand(h)}
        for k in kinds:
            assert k >= 27 or R.suit_of(k) in r.suits


def test_deal_sizes_and_starts_discarding_right_away():
    r = Round(0, random.Random(1))
    assert [sum(h) for h in r.hands] == [14, 13, 13]
    assert len(r.wall) == 84 - 40
    assert total_tiles(r) == 84
    assert r.phase == "discard" and r.turn == 0 and r.drawn is True


def test_discard_with_no_claims_passes_turn():
    r = Round(0, random.Random(3))
    set_hands(r, [[0] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    r.discard(0, 0)
    assert r.phase == "discard"
    assert r.turn == 1 and r.drawn is True
    assert sum(r.hands[1]) == 14


def test_pong_takes_tile_and_turn_moves_to_taker():
    r = Round(0, random.Random(4))
    set_hands(r, [
        [0, 18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11],   # 庄家打出一万
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
        [0, 0, 13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14],    # 手里两张一万，可以碰
    ])
    r.turn = 0
    r.drawn = True
    before = total_tiles(r)
    r.discard(0, 0)
    assert r.phase == "claim"
    assert "pong" in r.pending[2]
    answer(r, {2: "pong"})
    assert r.phase == "discard" and r.turn == 2
    assert r.melds[2] == [{"type": "pong", "kind": 0, "from": 0}]
    assert total_tiles(r) == before


def test_pinghu_cannot_win_on_discard_unless_opened():
    r = Round(0, random.Random(6))
    set_hands(r, [[28] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  pinghu_waiting_on_fa(),
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    r.discard(0, 28)
    assert r.phase == "discard" and r.turn == 1   # 屁胡不能点炮，直接轮到下家


def test_opened_pinghu_can_be_won_on_discard():
    r = Round(0, random.Random(7))
    set_hands(r, [[28] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  pinghu_waiting_on_fa(),
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 1
    r.drawn = False
    assert {"action": "open", "kind": None} in r.self_options(1)
    r.act_self(1, "open")
    assert r.opened[1] is True
    r.turn = 0
    r.drawn = True
    r.discard(0, 28)
    assert r.pending.get(1) == ["hu"]
    answer(r, {1: "hu"})
    res = r.result
    assert res["type"] == "win" and res["winners"][0]["seat"] == 1
    assert res["winners"][0]["fan"] == 1                 # 明牌 1 翻
    assert res["winners"][0]["points"] == 2              # 2 的 1 次方
    assert res["deltas"] == [-2, 2, 0]


def test_cannot_open_before_tenpai():
    r = Round(0, random.Random(20))
    set_hands(r, [[0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 28, 29, 27, 18],    # 离听牌还远
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    assert not any(o["action"] == "open" for o in r.self_options(0))
    with pytest.raises(GameError):
        r.act_self(0, "open")


def test_pinghu_self_draw_is_allowed():
    r = Round(0, random.Random(8))
    hand = pinghu_waiting_on_fa() + [28]          # 摸到发，自摸和牌
    set_hands(r, [hand, [18] * 13, [20] * 13])
    r.turn = 0
    r.drawn = True
    assert any(o["action"] == "hu" for o in r.self_options(0))
    r.act_self(0, "hu")
    res = r.result
    assert res["winners"][0]["selfDraw"] is True
    w = res["winners"][0]
    assert w["fan"] == 1                          # 屁胡不翻，自摸 1 翻
    assert w["points"] == 2
    assert res["deltas"] == [2 * w["points"], -w["points"], -w["points"]]


def test_big_hu_wins_on_discard_without_opening():
    r = Round(0, random.Random(10))
    # 七对听一张：2 番，大胡，可以点炮
    set_hands(r, [[27] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  [0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10, 12],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    r.discard(0, 12)
    assert r.pending.get(1) == ["hu"]


def test_gang_ming_draws_replacement_and_pays_discarder():
    r = Round(0, random.Random(11))
    set_hands(r, [[5, 18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11],
                  [5, 5, 5, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    r.discard(0, 5)
    answer(r, {1: "gang_ming"})
    assert r.melds[1][0]["type"] == "gang_ming"
    assert r.gang_pay == [-1, 1, 0]
    assert r.turn == 1 and r.phase == "discard" and r.drawn is True


def test_concealed_gang_is_not_allowed():
    """四张一样的牌要留在手里做四归一，不能暗杠。"""
    r = Round(0, random.Random(12))
    set_hands(r, [[4] * 4 + [18, 19, 20, 21, 22, 23, 24, 25, 26],
                  [0] * 13, [1] * 13])
    r.turn = 0
    r.drawn = True
    assert not any(o["action"] == "gang_an" for o in r.self_options(0))
    with pytest.raises(GameError):
        r.act_self(0, "gang_an", 4)


def test_bad_actions_raise_and_change_nothing():
    r = Round(0, random.Random(13))
    before = [list(h) for h in r.hands]
    with pytest.raises(GameError):
        r.discard(1, 0)                          # 不是你的回合
    with pytest.raises(GameError):
        r.act_self(0, "hu")                      # 没有和牌
    assert [list(h) for h in r.hands] == before


def test_draw_game_when_wall_is_empty():
    r = Round(0, random.Random(14))
    set_hands(r, [[0] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]])
    r.wall = []
    r.turn = 0
    r.drawn = True
    r.discard(0, 0)
    assert r.phase == "over"
    assert r.result["type"] == "draw"
    assert r.result["deltas"] == [0, 0, 0]


def test_match_rotates_dealer_among_three_when_dealer_loses():
    m = Match(rounds=2, rng=random.Random(15))
    m.begin_round()
    r = m.round
    r.phase = "over"
    r.result = {"type": "win", "winners": [{"seat": 2}], "deltas": [-1, 0, 1]}
    m.record()
    assert m.dealer == 1
    assert m.scores == [-1, 0, 1]
    assert not m.finished


def simulate(seed):
    """用电脑的打法把一整局打完，每一步都检查牌数是否守恒。"""
    r = Round(0, random.Random(seed))
    steps = 0
    while r.phase != "over":
        assert total_tiles(r) == 84
        steps += 1
        assert steps < 4000, "牌局没有结束"
        if r.phase == "discard":
            seat = r.turn
            opts = [o for o in r.self_options(seat) if o["action"] != "open"]
            act, kind = ai.decide_self(r.hands[seat], len(r.melds[seat]), r.visible(), opts)
            if act == "discard":
                r.discard(seat, kind)
            elif act == "hu":
                r.act_self(seat, "hu")
            else:
                r.act_self(seat, act, kind)
        else:
            for t in list(r.pending):
                if r.phase != "claim":
                    break
                if t not in r.responses:
                    r.respond(t, ai.decide_claim(r.hands[t], len(r.melds[t]), r.visible(),
                                                 r.pending[t], r.last[1]))
    assert total_tiles(r) == 84
    return r


@pytest.mark.parametrize("seed", [21, 22, 23])
def test_computer_players_finish_a_round(seed):
    r = simulate(seed)
    assert r.result["type"] in ("win", "draw")
    assert sum(r.result["deltas"]) == 0
    for w in r.result["winners"]:
        assert w["fan"] >= 1


def test_match_history_is_json_ready_for_scoreboard():
    import json
    m = Match(rounds=1, rng=random.Random(31))
    m.begin_round()
    r = m.round
    while r.phase != "over":
        if r.phase == "discard":
            seat = r.turn
            opts = [o for o in r.self_options(seat) if o["action"] != "open"]
            act, kind = ai.decide_self(r.hands[seat], len(r.melds[seat]), r.visible(), opts)
            if act == "discard":
                r.discard(seat, kind)
            elif act == "hu":
                r.act_self(seat, "hu")
            else:
                r.act_self(seat, act, kind)
        else:
            for t in list(r.pending):
                if r.phase == "claim" and t not in r.responses:
                    r.respond(t, ai.decide_claim(r.hands[t], len(r.melds[t]), r.visible(),
                                                 r.pending[t], r.last[1]))
    m.record()
    assert len(m.history) == 1
    entry = json.loads(json.dumps(m.history))[0]
    assert entry["round"] == 1 and entry["type"] in ("win", "draw")
    assert len(entry["deltas"]) == 3 and sum(entry["deltas"]) == 0
    if entry["type"] == "win":
        assert entry["winners"][0]["items"] and entry["winners"][0]["hand"]
