"""电脑玩家：能和就和，并且会选择打掉不影响听牌的那张。"""
from projects.mahjong import ai
from projects.mahjong import rules as R


def win14():
    return [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10]


def test_always_wins_when_possible():
    h = R.counts_of(win14())
    assert ai.decide_self(h, 0, [0] * 30, [{"action": "hu", "kind": None}]) == ("hu", -1)


def test_discards_the_stray_tile_and_keeps_tenpai():
    # 听一万的 13 张，再摸一张孤立的一筒
    h = R.counts_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10, 18])
    kind = ai.choose_discard(h, 0, [0] * 30)
    assert kind == 18
    h[kind] -= 1
    assert R.shanten(h, 0) == 0


def test_only_discards_tiles_it_holds_and_keeps_shanten_low():
    h = R.counts_of([0, 0, 5, 9, 12, 13, 14, 20, 21, 22, 23, 24, 26, 27])
    start = R.shanten(h, 0)
    for _ in range(4):
        kind = ai.choose_discard(h, 0, [0] * 30)
        assert h[kind] > 0
        h[kind] -= 1
    assert R.shanten(h, 0) <= start + 1


def test_claims_hu_first():
    h = R.counts_of(win14())
    assert ai.decide_claim(h, 0, [0] * 30, ["hu", "pong"], 0) == "hu"


def test_pong_only_when_it_helps():
    h = R.counts_of([0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 23, 25])
    now = R.shanten(h, 0)
    act = ai.decide_claim(h, 0, [0] * 30, ["pong"], 0)
    h2 = list(h)
    h2[0] -= 2
    expected = "pong" if ai._best_discard_shanten(h2, 1) < now else "pass"
    assert act == expected
