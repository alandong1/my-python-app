"""技能：摸完牌之后使用，每局每个只能用一次；偷天换日、锦上添花、妙手回春、釜底抽薪；积分和库存。"""
import random
import secrets

import pytest

from projects.mahjong import rules as R
from projects.mahjong import store
from projects.mahjong.engine import GameError, Round


def items(stock):
    return {"enabled": True, "stock": stock}


def set_after_draw(r, hands, turn=0):
    """把每家的手牌换成指定的牌，并让 turn 这家处于「摸完牌、准备打牌」的状态。"""
    for s in range(3):
        r.hands[s] = R.counts_of(hands[s])
        r.melds[s] = []
        r.discards[s] = []
    r.turn = turn
    r.phase = "discard"
    r.drawn = True
    r.draw_kind = R.expand(r.hands[turn])[-1]
    r.pending = {}
    r.responses = {}
    r.last = None


def total_tiles(r):
    n = sum(sum(h) for h in r.hands) + len(r.wall) + sum(len(d) for d in r.discards)
    for seat in r.melds:
        for m in seat:
            n += 3 if m["type"] == "pong" else 4
    return n


def test_items_are_offered_only_after_drawing():
    r = Round(0, random.Random(1), items([{"swap": 1}, {}, {}]))
    r.drawn = False                                    # 还没有摸牌
    assert r.item_options(0) == []
    r.drawn = True
    r.phase = "discard"
    assert [o["item"] for o in r.item_options(0)] == ["swap"]


def test_no_items_when_disabled_or_opened():
    r = Round(0, random.Random(2), None)
    r.drawn = True
    assert r.item_options(0) == []
    r2 = Round(0, random.Random(3), items([{"swap": 1}, {}, {}]))
    r2.drawn = True
    r2.opened[0] = True
    assert r2.item_options(0) == []                    # 明牌之后不能用技能


def test_swap_exchanges_a_hand_tile_with_a_random_wall_tile_and_is_used_once():
    r = Round(0, random.Random(3), items([{"swap": 2}, {}, {}]))
    r.drawn = True
    r.phase = "discard"
    give = R.expand(r.hands[0])[0]
    before = total_tiles(r)
    r.use_item(0, "swap", kind=give)
    assert total_tiles(r) == before                    # 牌数守恒
    assert r.stock[0]["swap"] == 1 and "swap" in r.used[0]
    assert r.drawn is True and r.turn == 0             # 还要打牌
    assert all(o["item"] != "swap" for o in r.item_options(0))   # 每局只能用一次
    with pytest.raises(GameError):
        r.use_item(0, "swap", kind=R.expand(r.hands[0])[0])


def test_swap_needs_a_tile_you_hold():
    r = Round(0, random.Random(4), items([{"swap": 1}, {}, {}]))
    r.drawn = True
    r.phase = "discard"
    missing = next(k for k in range(R.KINDS) if r.hands[0][k] == 0)
    with pytest.raises(GameError):
        r.use_item(0, "swap", kind=missing)
    assert r.stock[0]["swap"] == 1


def test_lucky_pong_takes_a_discard_you_hold_a_pair_of():
    r = Round(0, random.Random(5), items([{}, {"lucky_pong": 1}, {}]))
    set_after_draw(r, [[18] * 13 + [1], [0, 0] + [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14], [20] * 13], turn=1)
    r.discards[0] = [0]
    r.use_item(1, "lucky_pong", kind=0, src=0)
    assert r.melds[1] == [{"type": "pong", "kind": 0, "from": 0}]
    assert r.discards[0] == []
    assert r.phase == "discard" and r.turn == 1 and r.drawn is False   # 碰之后直接打牌


def test_lucky_pong_needs_a_pair_in_hand():
    r = Round(0, random.Random(6), items([{}, {"lucky_pong": 1}, {}]))
    set_after_draw(r, [[18] * 13 + [1], [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16], [20] * 13], turn=1)
    r.discards[0] = [0]
    with pytest.raises(GameError):
        r.use_item(1, "lucky_pong", kind=0, src=0)


def test_miracle_hu_needs_tenpai_and_replaces_the_drawn_tile():
    r = Round(0, random.Random(7), items([{}, {}, {"miracle_hu": 1}]))
    # 听发的屁胡：123万 789万 111条 中中中 + 发，摸到一张不要的 6 筒（18 之外的散牌）
    hand = [0, 1, 2, 6, 7, 8, 9, 9, 9, 27, 27, 27, 28, 25]
    set_after_draw(r, [[18] * 13, [13] * 13, hand], turn=2)
    r.draw_kind = 25
    assert "miracle_hu" in [o["item"] for o in r.item_options(2)]
    r.discards[1] = [28]                               # 别人打出了发
    r.use_item(2, "miracle_hu", kind=28, src=1)
    assert r.discards[2] == [25]                       # 摸到的那张打出去
    assert r.hands[2][28] == 2 and r.hands[2][25] == 0
    assert r.discards[1] == []


def test_miracle_hu_not_available_when_not_tenpai():
    r = Round(0, random.Random(8), items([{}, {}, {"miracle_hu": 1}]))
    far = [18, 20, 22, 24, 26, 19, 21, 23, 25, 27, 28, 29, 1, 3]
    set_after_draw(r, [[18] * 13, [13] * 13, far], turn=2)
    assert all(o["item"] != "miracle_hu" for o in r.item_options(2))


def test_steal_swaps_with_a_concealed_tile_of_an_unopened_opponent():
    r = Round(0, random.Random(9), items([{}, {}, {"steal": 1}]))
    set_after_draw(r, [[18] * 13, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], [20] * 13 + [27]], turn=2)
    before = total_tiles(r)
    give = 27
    r.use_item(2, "steal", kind=give, opp=1)
    assert total_tiles(r) == before
    assert r.hands[2][27] == 0 and sum(r.hands[2]) == 14
    assert sum(r.hands[1]) == 13


def test_steal_refused_against_opened_opponent():
    r = Round(0, random.Random(10), items([{}, {}, {"steal": 1}]))
    set_after_draw(r, [[18] * 13, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], [20] * 13 + [27]], turn=2)
    r.opened[1] = True
    with pytest.raises(GameError):
        r.use_item(2, "steal", kind=27, opp=1)


def test_store_new_players_start_with_ten_thousand_and_steal_costs_thirty(client):
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    uid = r.json()["id"]
    w = store.wallet(uid)
    assert w["points"] == store.START_POINTS == 10000
    assert store.buy(uid, "steal") is True
    assert store.wallet(uid)["points"] == 10000 - 30
    assert store.wallet(uid)["items"]["steal"] == 1
    assert store.consume(uid, "steal") is True
    assert store.consume(uid, "steal") is False
    store.refund(uid, "steal")
    assert store.wallet(uid)["items"]["steal"] == 1
    board = store.leaderboard()
    assert board[0]["points"] >= 10000 - 30


def test_opened_player_can_only_discard_the_drawn_tile():
    r = Round(0, random.Random(30))
    set_after_draw(r, [[18] * 13 + [1], [13] * 13, [14] * 13], turn=0)
    r.opened[0] = True
    other = next(k for k in range(R.KINDS) if r.hands[0][k] and k != r.draw_kind)
    with pytest.raises(GameError):
        r.discard(0, other)
    r.discard(0, r.draw_kind)                 # 摸到的那张可以打
    assert r.phase in ("discard", "claim", "over")


def test_drawn_tile_is_noted_privately():
    r = Round(0, random.Random(31))
    r.wall = [5, 6, 7]
    r.turn = 1
    r._draw_for(1)
    assert r.notes[1][-1] == "摸到：" + R.kind_name(r.draw_kind)


def test_steal_notes_both_players_about_their_own_tiles():
    r = Round(0, random.Random(32), items([{}, {}, {"steal": 1}]))
    set_after_draw(r, [[18] * 13, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], [20] * 13 + [27]], turn=2)
    r.use_item(2, "steal", kind=27, opp=1)
    assert any("釜底抽薪" in t and "给出" in t for t in r.notes[2])
    assert any("釜底抽薪" in t and "失去" in t for t in r.notes[1])
    assert not any("釜底抽薪" in t for t in r.notes[0])
