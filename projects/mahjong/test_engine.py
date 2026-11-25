"""一局麻将的流程：发牌、碰、杠、和牌、流局，以及电脑对打时牌数守恒。"""
import random

import pytest

from projects.mahjong import ai
from projects.mahjong import rules as R
from projects.mahjong.engine import GameError, Match, Round


def set_hands(r, hands):
    """把每家的手牌换成指定的牌种列表（用于构造测试场景）。"""
    for s in range(4):
        r.hands[s] = R.counts_of(hands[s])


def win13():
    """听一万的 13 张：二万到九万、111条…（不含一万），和牌差一张一万。"""
    return [1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10]


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


def test_deal_sizes_and_tile_count():
    r = Round(0, random.Random(1))
    assert [sum(h) for h in r.hands] == [14, 13, 13, 13]
    assert len(r.wall) == 108 - 53
    assert total_tiles(r) == 108
    assert r.turn == 0 and r.drawn


def test_discard_with_no_claims_passes_turn_and_next_player_draws():
    r = Round(0, random.Random(2))
    set_hands(r, [[0] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16]])
    r.turn = 0
    r.drawn = True
    r.discard(0, 0)
    assert r.phase == "discard"
    assert r.turn == 1 and r.drawn is True     # 下家摸了一张
    assert sum(r.hands[1]) == 14


def test_pong_takes_tile_and_turn_moves_to_taker():
    r = Round(0, random.Random(3))
    set_hands(r, [
        [0, 18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11],   # 庄家：打出一万
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],          # 无关的一家
        [0, 0, 13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14],    # 手里两张一万，可以碰
        [26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14],
    ])
    r.turn = 0
    r.drawn = True
    r.phase = "discard"
    before = total_tiles(r)
    r.discard(0, 0)
    assert r.phase == "claim"
    assert "pong" in r.pending[2]
    answer(r, {2: "pong"})
    assert r.phase == "discard"
    assert r.turn == 2
    assert r.melds[2] == [{"type": "pong", "kind": 0, "from": 0}]
    assert total_tiles(r) == before          # 牌只是换了地方，总数不变


def test_discard_win_pays_discarder():
    r = Round(0, random.Random(4))
    set_hands(r, [
        [0] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],   # 庄家打出一万
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10],                   # 听一万
        [14, 15, 16, 17, 14, 15, 16, 17, 18, 19, 20, 21, 22],
        [14, 15, 16, 17, 14, 15, 16, 17, 18, 19, 20, 21, 22],
    ])
    r.turn = 0
    r.drawn = True
    r.discard(0, 0)
    assert r.pending.get(1) == ["hu"]
    answer(r, {1: "hu"})
    assert r.phase == "over"
    res = r.result
    assert res["type"] == "win"
    assert res["winners"][0]["seat"] == 1
    assert res["from"] == 0
    assert res["deltas"][1] == res["winners"][0]["fan"] > 0
    assert res["deltas"][0] == -res["deltas"][1]
    assert sum(res["deltas"]) == 0


def test_self_draw_win_pays_everyone():
    r = Round(0, random.Random(5))
    win14 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10]   # 123~9万 111条 22条
    set_hands(r, [win14, [18] * 13, [19] * 13, [20] * 13])
    r.turn = 0
    r.drawn = True
    assert any(o["action"] == "hu" for o in r.self_options(0))
    r.act_self(0, "hu")
    res = r.result
    assert res["winners"][0]["selfDraw"] is True
    fan = res["winners"][0]["fan"]
    assert fan == 3                          # 平胡 + 自摸 + 一个五星
    assert res["deltas"] == [3 * fan, -fan, -fan, -fan]


def test_concealed_gang_and_replacement_tile():
    r = Round(0, random.Random(6))
    set_hands(r, [[5] * 4 + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9], [0] * 13, [1] * 13, [2] * 13])
    r.turn = 0
    r.drawn = True
    opts = r.self_options(0)
    assert {"action": "gang_an", "kind": 5} in opts
    r.act_self(0, "gang_an", 5)
    assert r.melds[0] == [{"type": "gang_an", "kind": 5, "from": None}]
    assert r.gang_pay[0] == 3 and r.gang_pay[1] == -1
    assert r.phase == "discard" and r.drawn is True    # 杠后补了一张，接着要打牌


def test_bad_actions_raise_and_change_nothing():
    r = Round(0, random.Random(7))
    before = [list(h) for h in r.hands]
    with pytest.raises(GameError):
        r.discard(1, 0)                      # 不是你的回合
    with pytest.raises(GameError):
        r.act_self(0, "hu")                  # 没有和牌
    assert [list(h) for h in r.hands] == before


def test_draw_game_when_wall_is_empty():
    r = Round(0, random.Random(8))
    set_hands(r, [[0] + [18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 10, 11, 12],
                  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]])
    r.wall = []
    r.turn = 0
    r.drawn = True
    r.discard(0, 0)
    assert r.phase == "over"
    assert r.result["type"] == "draw"
    assert r.result["deltas"] == [0, 0, 0, 0]


def test_match_rotates_dealer_when_dealer_loses():
    m = Match(rounds=2, rng=random.Random(9))
    m.begin_round()
    r = m.round
    r.phase = "over"
    r.result = {"type": "win", "winners": [{"seat": 2}], "deltas": [-1, 0, 1, 0]}
    m.record()
    assert m.dealer == 1
    assert m.scores == [-1, 0, 1, 0]
    assert not m.finished


def simulate(seed):
    """用电脑的打法把一整局打完，每一步都检查牌数是否守恒。"""
    r = Round(0, random.Random(seed))
    steps = 0
    while r.phase != "over":
        assert total_tiles(r) == 108
        steps += 1
        assert steps < 3000, "牌局没有结束"
        if r.phase == "discard":
            seat = r.turn
            act, kind = ai.decide_self(r.hands[seat], len(r.melds[seat]), r.visible(), r.self_options(seat))
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
                    r.respond(t, ai.decide_claim(r.hands[t], len(r.melds[t]), r.visible(), r.pending[t], r.last[1]))
    assert total_tiles(r) == 108
    return r


@pytest.mark.parametrize("seed", [11, 12])
def test_computer_players_finish_a_round(seed):
    r = simulate(seed)
    assert r.result["type"] in ("win", "draw")
    assert sum(r.result["deltas"]) == 0
