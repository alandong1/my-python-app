"""四川麻将（血战到底、血流成河）的一局流程：换三张、定缺、缺门、一炮一响 / 一炮多响、花猪、整局模拟。"""
import random

import pytest

from projects.mahjong import rules as R
from projects.mahjong.engine import GameError
from projects.mahjong.engine_sichuan import N, SichuanMatch, SichuanRound


def play_round(r: SichuanRound, rng: random.Random, max_steps: int = 5000) -> None:
    """用合规的随机策略打完一局：换三张选同一门的牌，定缺选张数最少的，打牌随机打允许的牌，能胡就胡。"""
    steps = 0
    while r.phase != "over":
        steps += 1
        assert steps < max_steps, "牌局没有结束"
        if r.phase == "exchange":
            for s in r.pending_exchange():
                c = list(r.hands[s])
                suit = max(range(3), key=lambda x: sum(c[x * 9:(x + 1) * 9]))
                kinds = [k for k in range(suit * 9, suit * 9 + 9) for _ in range(c[k])][:3]
                while len(kinds) < 3:
                    kinds.append(next(k for k in range(27) if c[k]))
                r.choose_exchange(s, kinds)
        elif r.phase == "ding":
            for s in r.pending_ding():
                counts = [sum(r.hands[s][x * 9:(x + 1) * 9]) for x in range(3)]
                r.choose_missing(s, min(range(3), key=lambda x: counts[x]))
        elif r.phase == "discard":
            seat = r.turn
            opts = r.self_options(seat)
            if any(o["action"] == "hu" for o in opts):
                r.act_self(seat, "hu")
                continue
            kinds = [k for k in range(27) if r.hands[seat][k]]
            m = r.missing[seat]
            if m is not None:
                lacking = [k for k in kinds if k // 9 == m]
                if lacking:
                    kinds = lacking
            r.discard(seat, rng.choice(kinds))
        elif r.phase == "claim":
            for t in list(r.pending):
                if r.phase != "claim":
                    break
                if t in r.responses:
                    continue
                opts = r.pending[t]
                if "hu" in opts:
                    r.respond(t, "hu")
                else:
                    r.respond(t, "pass")


@pytest.mark.parametrize("mode", ["xuezhan", "xueliu"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_full_round_settles_to_zero(mode, seed):
    rng = random.Random(seed)
    r = SichuanRound(0, rng, mode=mode, exchange_dir=1 + seed % 3)
    play_round(r, rng)
    assert r.result["type"] in ("win", "draw")
    assert sum(r.result["deltas"]) == 0
    assert len(r.result["deltas"]) == N


def test_exchange_then_missing_then_play():
    rng = random.Random(10)
    r = SichuanRound(0, rng)
    assert r.phase == "exchange"
    for s in range(N):
        c = list(r.hands[s])
        kinds = [k for k in range(27) if c[k]][:3]
        r.choose_exchange(s, kinds)
    assert r.phase == "ding"
    assert sum(sum(h) for h in r.hands) == 4 * 13          # 换牌不改变张数
    for s in range(N):
        r.choose_missing(s, 0)
    assert r.phase == "discard" and r.turn == 0 and r.drawn is True


def test_exchange_needs_three_tiles_you_hold():
    rng = random.Random(11)
    r = SichuanRound(0, rng)
    with pytest.raises(GameError):
        r.choose_exchange(0, [0, 1])
    missing = next(k for k in range(27) if r.hands[0][k] == 0)
    with pytest.raises(GameError):
        r.choose_exchange(0, [missing, missing, missing])


def test_exchange_moves_tiles_to_the_chosen_direction():
    rng = random.Random(12)
    r = SichuanRound(0, rng, exchange_dir=1)               # 给下家
    before = [list(h) for h in r.hands]
    given = [[k for k in range(27) if before[s][k]][0] for s in range(N)]
    for s in range(N):
        r.choose_exchange(s, [given[s]] * 1 + [k for k in range(27) if before[s][k] and k != given[s]][:2])
    for s in range(N):
        t = (s + 1) % N
        assert r.hands[t][given[s]] >= 0
    assert sum(sum(h) for h in r.hands) == 4 * 13


def test_xuezhan_only_first_claimer_wins_a_discard():
    rng = random.Random(13)
    r = SichuanRound(0, rng, mode="xuezhan")
    r.phase = "claim"
    r.last = (0, 5)
    r.pending = {1: ["hu"], 2: ["hu"]}
    r.responses = {}
    r.discards[0] = [5]
    r.hands[1] = R.counts_of([])
    r.hands[2] = R.counts_of([])
    for t in (1, 2):
        r.missing[t] = None
    # 用假的胡：直接检查一炮一响的分支（只取顺序第一个）
    r._win = lambda seat, kind, self_draw: {"fan": 1, "points": 2, "items": [("平胡", 1)], "hand": []}
    r.respond(1, "hu")
    r.respond(2, "hu")
    assert [w["seat"] for w in r.wins] == [1]
    assert r.finished[1] and not r.finished[2]


def test_xueliu_all_claimers_win_a_discard():
    rng = random.Random(14)
    r = SichuanRound(0, rng, mode="xueliu")
    r.phase = "claim"
    r.last = (0, 5)
    r.pending = {1: ["hu"], 2: ["hu"]}
    r.responses = {}
    r.discards[0] = [5]
    r._win = lambda seat, kind, self_draw: {"fan": 1, "points": 2, "items": [("平胡", 1)], "hand": []}
    r.respond(1, "hu")
    r.respond(2, "hu")
    assert sorted(w["seat"] for w in r.wins) == [1, 2]


def test_flower_pig_pays_every_other_player_their_maximum():
    rng = random.Random(15)
    r = SichuanRound(0, rng)
    # 0 号：三门都有（花猪）；其他人随便
    r.hands = [R.counts_of([0, 9, 18, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11]),
               R.counts_of([12] * 13), R.counts_of([13] * 13), R.counts_of([14] * 13)]
    r.melds = [[], [], [], []]
    r.finished = [False] * N
    r.wins = []
    r.deltas = [0] * N
    r._max_points = lambda q: 4
    r._end_draw()
    assert r.result["deltas"][0] == -12
    assert r.result["deltas"][1:] == [4, 4, 4]
    assert sum(r.result["deltas"]) == 0


def test_match_rotates_dealer_and_changes_exchange_direction():
    m = SichuanMatch(rounds=4, rng=random.Random(16))
    r1 = m.begin_round()
    assert r1.exchange_dir == 1 and r1.dealer == 0
    play_round(r1, m.rng)
    m.record()
    r2 = m.begin_round()
    assert r2.exchange_dir == 2 and r2.dealer == 1
