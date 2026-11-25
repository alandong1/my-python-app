"""湖北卡五星的规则计算：胡牌、向听数、番数。"""
from projects.mahjong import rules as R


def win14():
    """一手完整的和牌：123万 456万 789万 111条 22条（共 14 张）。"""
    c = R.counts_of([])
    for k in range(9):          # 一万~九万各一张
        c[k] += 1
    c[9] = 3                    # 一条三张
    c[10] = 2                   # 二条两张
    return c


def test_kind_names():
    assert R.kind_name(0) == "1万"
    assert R.kind_name(4) == "5万"
    assert R.kind_name(13) == "5条"
    assert R.kind_name(22) == "5筒"


def test_complete_hand_is_win():
    assert R.is_win(win14(), 0)
    assert R.shanten(win14(), 0) == -1


def test_thirteen_tiles_waiting_on_one_tile():
    c = win14()
    c[10] = 1                   # 少一张二条：听二条，一张就能和
    assert sum(c) == 13
    assert R.shanten(c, 0) == 0
    assert not R.is_win(c, 0)   # 13 张还不能和
    c[10] = 2                   # 补上二条，就和了
    assert R.is_win(c, 0)


def test_wait_on_middle_of_sequence():
    c = R.counts_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 11])  # 花色混在一起的不规则手牌
    assert R.shanten(c, 0) >= 1           # 这手牌离听牌还有距离


def test_seven_pairs_win():
    c = R.counts_of([0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10, 12, 12])
    assert R.is_win(c, 0)
    assert R.shanten(c, 0) == -1


def test_pong_melds_reduce_concealed_count():
    # 一组碰（明牌）+ 三组顺子/刻子 + 一对将，暗牌 11 张
    c = R.counts_of([0, 1, 2, 3, 4, 5, 9, 9, 9, 13, 13])
    assert R.is_win(c, 1)
    assert not R.is_win(c, 0)  # 没有明牌时张数不对


def test_win_needs_exact_tile_count():
    c = win14()
    c[0] += 1
    assert not R.is_win(c, 0)  # 15 张不算和牌


def test_score_five_stars_and_self_draw():
    c = win14()                 # 含一张五万（编号 4）
    fan, items = R.score_win(c, [], False)
    assert ("平胡", 1) in items
    assert ("五星", 1) in items
    assert fan == 2
    fan_self, _ = R.score_win(c, [], True)
    assert fan_self == 3        # 多了自摸 1 番


def test_score_counts_five_in_melds():
    c = R.counts_of([9, 9, 9, 0, 1, 2, 6, 7, 8, 18, 18])
    melds = [{"type": "gang_ming", "kind": 4, "from": 1}]   # 明杠五万：4 张五星
    fan, items = R.score_win(c, melds, False)
    assert ("五星", 4) in items
    assert fan == 5


def test_expand_round_trip():
    c = R.counts_of([3, 3, 7])
    assert R.expand(c) == [3, 3, 7]
