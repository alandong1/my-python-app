"""道具：偷天换日、锦上添花、妙手回春（摸牌前使用），以及积分和库存的数据库操作。"""
import random
import secrets

import pytest

from projects.mahjong import rules as R
from projects.mahjong import store
from projects.mahjong.engine import GameError, Round


def items(stock):
    return {"enabled": True, "stock": stock}


def set_hands(r, hands):
    for s in range(3):
        r.hands[s] = R.counts_of(hands[s])
        r.melds[s] = []
        r.discards[s] = []
    r.pending = {}
    r.responses = {}
    r.last = None


def test_predraw_stops_before_drawing_when_items_are_owned():
    r = Round(0, random.Random(1), items([{"swap": 1}, {}, {}]))
    assert r.phase == "predraw" and r.turn == 0
    assert len(r.hands[0]) and sum(r.hands[0]) == 13
    actions = [o["action"] for o in r.predraw_options(0)]
    assert actions == ["skip", "item"]
    r.act_predraw(0, "skip")
    assert r.phase == "discard" and r.drawn is True and sum(r.hands[0]) == 14


def test_no_predraw_when_items_disabled():
    r = Round(0, random.Random(2))
    assert r.phase == "discard" and r.drawn is True


def test_swap_exchanges_a_hand_tile_with_a_random_wall_tile():
    r = Round(0, random.Random(3), items([{"swap": 1}, {}, {}]))
    give = R.expand(r.hands[0])[0]
    before = sum(sum(h) for h in r.hands) + len(r.wall)
    wall_before = len(r.wall)
    r.act_predraw(0, "item", item="swap", kind=give)
    assert r.stock[0]["swap"] == 0
    assert sum(sum(h) for h in r.hands) + len(r.wall) == before   # 牌数守恒
    assert len(r.wall) == wall_before - 1                           # 换完之后照常摸了一张
    assert sum(r.hands[0]) == 14 and r.phase == "discard" and r.drawn is True


def test_swap_needs_a_tile_you_hold():
    r = Round(0, random.Random(4), items([{"swap": 1}, {}, {}]))
    missing = next(k for k in range(R.KINDS) if r.hands[0][k] == 0)
    with pytest.raises(GameError):
        r.act_predraw(0, "item", item="swap", kind=missing)
    assert r.phase == "predraw" and r.stock[0]["swap"] == 1


def test_lucky_pong_takes_a_discard_that_makes_a_triplet():
    r = Round(0, random.Random(5), items([{}, {"lucky_pong": 1}, {}]))
    set_hands(r, [[18] * 13, [0, 0] + [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14], [20] * 13])
    r.discards[0] = [0]
    r.turn = 1
    r.phase = "predraw"
    r.act_predraw(1, "item", item="lucky_pong", kind=0, src=0)
    assert r.melds[1] == [{"type": "pong", "kind": 0, "from": 0}]
    assert r.discards[0] == []
    assert r.phase == "discard" and r.turn == 1 and r.drawn is False   # 碰之后直接打牌


def test_lucky_pong_cannot_pick_a_tile_without_a_pair():
    r = Round(0, random.Random(6), items([{}, {"lucky_pong": 1}, {}]))
    set_hands(r, [[18] * 13, [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16], [20] * 13])
    r.discards[0] = [0]
    r.turn = 1
    r.phase = "predraw"
    with pytest.raises(GameError):
        r.act_predraw(1, "item", item="lucky_pong", kind=0, src=0)


def test_miracle_hu_takes_a_discard_and_wins_by_self_draw():
    r = Round(0, random.Random(7), items([{}, {}, {"miracle_hu": 1}]))
    # 屁胡听发：123万 789万 111条 中中中 + 发，缺的那张发打在牌河里
    set_hands(r, [[18] * 13, [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [0, 1, 2, 6, 7, 8, 9, 9, 9, 27, 27, 27, 28]])
    r.discards[1] = [28]
    r.turn = 2
    r.phase = "predraw"
    r.act_predraw(2, "item", item="miracle_hu", kind=28, src=1)
    res = r.result
    assert res["type"] == "win" and res["winners"][0]["selfDraw"] is True
    assert res["winners"][0]["points"] == 2                 # 屁胡 + 自摸
    assert sum(res["deltas"]) == 0


def test_miracle_hu_refused_when_it_does_not_win():
    r = Round(0, random.Random(8), items([{}, {}, {"miracle_hu": 1}]))
    set_hands(r, [[18] * 13, [13, 14, 15, 16, 17, 9, 10, 11, 12, 13, 14, 15, 16],
                  [0, 1, 2, 6, 7, 8, 9, 9, 9, 27, 27, 27, 28]])
    r.discards[1] = [13]
    r.turn = 2
    r.phase = "predraw"
    with pytest.raises(GameError):
        r.act_predraw(2, "item", item="miracle_hu", kind=13, src=1)
    assert r.phase == "predraw"


def test_store_points_items_and_shop(client):
    from app.auth import SESSION_COOKIE  # noqa: F401  (确保认证模块已加载)
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    uid = r.json()["id"]
    assert store.wallet(uid)["points"] == 0
    assert store.buy(uid, "swap") is False                    # 积分不够
    store.add_points(uid, 80)
    assert store.buy(uid, "swap") is True
    assert store.buy(uid, "miracle_hu") is True               # 50 分
    w = store.wallet(uid)
    assert w["points"] == 80 - 20 - 50 and w["items"]["swap"] == 1 and w["items"]["miracle_hu"] == 1
    assert store.consume(uid, "swap") is True
    assert store.consume(uid, "swap") is False
    store.refund(uid, "swap")
    assert store.wallet(uid)["items"]["swap"] == 1
    board = store.leaderboard()
    assert board[0]["points"] == w["points"] and isinstance(board[0]["name"], str)
