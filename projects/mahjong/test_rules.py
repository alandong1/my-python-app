"""湖北卡五星的规则计算：牌种、胡牌、向听数、番数。"""
from projects.mahjong import rules as R


def win14():
    """一手完整的和牌：123万 456万 789万 111条 22条（共 14 张，含一张五万）。"""
    c = R.counts_of([])
    for k in range(9):
        c[k] += 1
    c[9] = 3
    c[10] = 2
    return c


def pinghu14():
    """没有五、没有七对的平胡：123万 789万 111条 222筒 中中（共 14 张）。"""
    return R.counts_of([0, 1, 2, 6, 7, 8, 9, 9, 9, 19, 19, 19, 27, 27])


def test_kind_names():
    assert R.kind_name(0) == "1万"
    assert R.kind_name(4) == "5万"
    assert R.kind_name(13) == "5条"
    assert R.kind_name(22) == "5筒"
    assert R.kind_name(27) == "中"
    assert R.kind_name(29) == "白"


def test_wind_names_are_defined_for_other_rules():
    assert R.kind_name(30) == "东"
    assert R.kind_name(33) == "北"
    assert R.ALL_KINDS == 34 and R.WIND_START == 30


def test_honor_triplet_and_pair_can_win():
    c = R.counts_of([0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 27, 27, 28, 28])   # 字牌刻子 + 对子
    assert R.is_win(c, 0)


def test_honors_cannot_form_sequences():
    # 中、发、白各一张不能组成顺子，所以这手牌和不了
    c = R.counts_of([0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 28, 29, 9, 9])
    assert not R.is_win(c, 0)


def test_complete_hand_is_win():
    assert R.is_win(win14(), 0)
    assert R.shanten(win14(), 0) == -1


def test_thirteen_tiles_waiting_on_one_tile():
    c = win14()
    c[10] = 1                   # 少一张二条：听二条
    assert sum(c) == 13
    assert R.shanten(c, 0) == 0
    assert not R.is_win(c, 0)
    c[10] = 2
    assert R.is_win(c, 0)


def test_seven_pairs_win():
    c = R.counts_of([0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10, 27, 27])
    assert R.is_win(c, 0)
    assert R.shanten(c, 0) == -1


def test_pong_melds_reduce_concealed_count():
    c = R.counts_of([0, 1, 2, 3, 4, 5, 9, 9, 9, 13, 13])
    assert R.is_win(c, 1)
    assert not R.is_win(c, 0)


def test_win_needs_exact_tile_count():
    c = win14()
    c[0] += 1
    assert not R.is_win(c, 0)


def test_pinghu_is_zero_fan():
    fan, items, pattern = R.score_win(pinghu14(), [], False)
    assert fan == 0 and items == [] and pattern == 0


def test_pinghu_self_draw_is_one_fan():
    fan, items, pattern = R.score_win(pinghu14(), [], True)
    assert fan == 1 and ("自摸", 1) in items and pattern == 0


def test_opened_adds_one_fan():
    fan, items, pattern = R.score_win(pinghu14(), [], False, opened=True)
    assert fan == 1 and ("明牌", 1) in items and pattern == 0


def test_seven_pairs_is_two_fan():
    c = R.counts_of([0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10, 27, 27])
    fan, items, pattern = R.score_win(c, [], False)
    assert ("七对", 2) in items and fan == 2 and pattern == 2


def test_one_suit_is_two_fan():
    c = R.counts_of([0, 1, 2, 3, 4, 5, 6, 7, 8, 0, 0, 1, 1, 2])   # 只有万
    c = R.counts_of([0, 1, 2, 3, 4, 5, 6, 7, 8, 0, 1, 2, 3, 4])
    fan, items, pattern = R.score_win(c, [], False)
    assert ("清一色", 2) in items and pattern == 2


def test_honor_breaks_one_suit():
    c = R.counts_of([0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 27, 27, 0, 0])
    fan, items, pattern = R.score_win(c, [], False)
    assert all(name != "清一色" for name, _ in items)


def test_quad_in_seven_pairs_counts_as_four_kind():
    # 七对，其中 0（一万）有 4 张，都要组成两对
    c = R.counts_of([0, 0, 0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10])
    fan, items, pattern = R.score_win(c, [], False, win_kind=2)   # 胡的不是那张第 4 张
    assert ("七对", 2) in items and ("暗四归一", 2) in items
    assert fan == 4 and pattern == 4


def test_quad_completed_by_discard_is_ming_four_kind():
    c = R.counts_of([0, 0, 0, 0, 2, 2, 4, 4, 6, 6, 8, 8, 10, 10])
    fan, items, pattern = R.score_win(c, [], False, win_kind=0)   # 胡的正好是第 4 张
    assert ("明四归一", 1) in items and ("暗四归一", 2) not in items
    assert fan == 4 - 1 and pattern == 3


def test_two_quads_is_double_dragon_seven_pairs():
    c = R.counts_of([0, 0, 0, 0, 2, 2, 2, 2, 4, 4, 6, 6, 8, 8])
    fan, items, pattern = R.score_win(c, [], True)
    assert ("双龙七对", 1) in items
    assert [name for name, _ in items].count("暗四归一") == 2


def test_expand_round_trip():
    c = R.counts_of([3, 3, 7, 27])
    assert R.expand(c) == [3, 3, 7, 27]
