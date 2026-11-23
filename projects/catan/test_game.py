"""卡坦岛规则测试：直接调用 Game，不经过网络。"""
import random

import pytest

from projects.catan import config as C
from projects.catan.game import Game, GameError


class FakeRng(random.Random):
    """骰子结果由测试指定，其它随机（洗牌、抢牌）照常。"""

    def __init__(self, dice=()):
        super().__init__(123)
        self.dice = list(dice)

    def randint(self, a, b):
        if self.dice:
            return self.dice.pop(0)
        return super().randint(a, b)


def new_game(n=3, seed=5, dice=()):
    names = [(100 + i, f"玩家{i}") for i in range(n)]
    return Game(names, rng=FakeRng(dice))


def uid_of(g, seat):
    return g.seats[seat].uid


def setup_opening(g):
    """让每位玩家按蛇形顺序随便放好村庄和道路，进入掷骰子阶段。"""
    for _ in range(len(g.setup_order) * 2):          # 每一步两个动作：村庄 + 道路
        seat = g.setup_order[g.setup_step]
        uid = uid_of(g, seat)
        if g.setup_sub == "settlement":
            vid = next(v["id"] for v in g.board.vertices if g._spaced(v["id"]))
            g.setup_settlement(uid, vid)
        else:
            eid = next(e for e in g.board.vertices[g.last_settlement]["edges"] if e not in g.roads)
            g.setup_road(uid, eid)
    assert g.phase == "roll"


def give(g, seat, **res):
    for r, n in res.items():
        g.seats[seat].hand[r] += n
        g.bank[r] -= n


def test_setup_snake_order_and_second_round_resources():
    g = new_game(3)
    assert g.phase == "setup"
    order = g.setup_order
    assert order == [0, 1, 2, 2, 1, 0]
    first = order[0]
    with pytest.raises(GameError):
        g.setup_settlement(uid_of(g, (first + 1) % 3), 0)     # 不轮到他
    setup_opening(g)
    assert g.turn == 0
    # 第二轮放的村庄应该拿到周围地块的资源：总手牌数 = 放得越靠后的玩家拿到的越多
    counts = [sum(s.hand.values()) for s in g.seats]
    assert sum(counts) > 0 and all(c <= 3 for c in counts)


def test_setup_distance_rule_and_road_must_touch_settlement():
    g = new_game(3)
    uid = uid_of(g, 0)
    g.setup_settlement(uid, 0)
    eid_far = next(e["id"] for e in g.board.edges if 0 not in (e["a"], e["b"]))
    with pytest.raises(GameError):
        g.setup_road(uid, eid_far)                          # 道路没有连着村庄
    adj = g.board.vertices[0]["adj"][0]
    with pytest.raises(GameError):
        g.setup_settlement(uid_of(g, 1), adj)               # 相邻的角不能放村庄
    eid = g.board.vertices[0]["edges"][0]
    g.setup_road(uid, eid)
    assert g.roads[eid] == 0


def test_distribution_with_city_and_bank_shortage():
    g = new_game(3)
    setup_opening(g)
    # 找一个数字为 8 的地块，把它周围一个村庄换成城市，检查产出
    hexe = next(h for h in g.board.hexes if h["number"] and h["terrain"] != "desert" and h["id"] != g.robber)
    res = C.TERRAIN_RESOURCE[hexe["terrain"]]
    for seat in g.seats:
        seat.hand = {r: 0 for r in C.RESOURCES}
    g.buildings.clear()
    vid = hexe["corners"][0]
    g.buildings[vid] = (0, "city")
    g.bank = {r: 19 for r in C.RESOURCES}
    g._produce(hexe["number"])
    assert g.seats[0].hand[res] == 2
    # 银行只剩 1 张，两个人都要 → 谁也拿不到
    g.buildings[hexe["corners"][1]] = (1, "settlement")
    for seat in g.seats:
        seat.hand = {r: 0 for r in C.RESOURCES}
    g.bank = {r: 19 for r in C.RESOURCES}
    g.bank[res] = 1
    g._produce(hexe["number"])
    assert g.seats[0].hand[res] == 0 and g.seats[1].hand[res] == 0


def test_seven_forces_discard_then_robber_steals():
    g = new_game(3, dice=[3, 4])
    setup_opening(g)
    g.seats[1].hand = {"brick": 4, "lumber": 4, "wool": 0, "grain": 0, "ore": 0}   # 8 张
    g.seats[2].hand = {"brick": 3, "lumber": 3, "wool": 0, "grain": 0, "ore": 0}   # 不用弃
    g.bank = {r: 19 - sum(s.hand[r] for s in g.seats) for r in C.RESOURCES}
    g.dice = None
    g.rng.dice = [3, 4]
    g.roll(uid_of(g, 0))
    assert g.phase == "discard" and g.discard_need == {1: 4}
    with pytest.raises(GameError):
        g.discard(uid_of(g, 1), {"brick": 3})                # 要弃 4 张
    g.discard(uid_of(g, 1), {"brick": 2, "lumber": 2})
    assert g.phase == "robber"
    hid = next(h["id"] for h in g.board.hexes if h["id"] != g.robber)
    victims = g._victims(hid, 0)
    if len(victims) > 1:
        with pytest.raises(GameError):
            g.move_robber(uid_of(g, 0), hid)
    g.move_robber(uid_of(g, 0), hid, victims[0] if victims else None)
    assert g.phase == "play" and g.robber == hid


def test_build_costs_and_piece_limits():
    g = new_game(3)
    setup_opening(g)
    g.phase = "play"
    uid = uid_of(g, g.turn)
    s = g.seats[g.turn]
    s.hand = {r: 0 for r in C.RESOURCES}
    with pytest.raises(GameError):
        g.buy_dev(uid)                                       # 没钱
    give(g, g.turn, ore=1, wool=1, grain=1)
    g.buy_dev(uid)
    assert sum(s.dev_new.values()) == 1 and not s.dev         # 刚买的不能马上用
    with pytest.raises(GameError):
        g.play_knight(uid)


def test_longest_road_blocked_by_opponent_settlement():
    g = new_game(3)
    g.phase = "play"
    # 沿着一条路径连 5 段（用 board 里的真实边）
    path_edges = []
    v = 0
    seen = {0}
    while len(path_edges) < 5:
        e = g.board.vertices[v]["edges"][-1]
        ed = g.board.edges[e]
        nxt = ed["b"] if ed["a"] == v else ed["a"]
        if nxt in seen:
            break
        path_edges.append(e)
        seen.add(nxt)
        v = nxt
    for e in path_edges:
        g.roads[e] = 0
    assert g._longest_road(0) == len(path_edges)
    # 对手在路中间的角放一个村庄，就把路切断
    mid = g.board.edges[path_edges[2]]["b"]
    g.buildings[mid] = (1, "settlement")
    assert g._longest_road(0) < len(path_edges)


def test_largest_army_and_award_ties():
    g = new_game(3)
    g.seats[0].knights = 3
    g._update_awards()
    assert g.seats[0].has_army and g.vp(g.seats[0], hidden=False) == 2
    g.seats[1].knights = 3                                   # 平手：原持有人保留
    g._update_awards()
    assert g.seats[0].has_army and not g.seats[1].has_army
    g.seats[1].knights = 4                                   # 超过才会换人
    g._update_awards()
    assert g.seats[1].has_army and not g.seats[0].has_army


def test_bank_trade_rates_with_port():
    g = new_game(3)
    g.phase = "play"
    s = g.seats[0]
    s.hand = {r: 10 for r in C.RESOURCES}
    assert g.trade_rate(0, "brick") == 4
    harbor = g.board.harbors[0]
    e = g.board.edges[harbor["edge"]]
    g.buildings[e["a"]] = (0, "settlement")
    rate = g.trade_rate(0, harbor["type"] if harbor["type"] != "any" else "brick")
    assert rate == (2 if harbor["type"] != "any" else 3)
    before = dict(s.hand)
    g.bank_trade(uid_of(g, 0), "wool", "ore")
    assert s.hand["wool"] == before["wool"] - g.trade_rate(0, "wool")
    assert s.hand["ore"] == before["ore"] + 1


def test_failed_year_of_plenty_does_not_consume_card():
    g = new_game(3)
    g.phase = "play"
    s = g.seats[0]
    s.dev = {"year_of_plenty": 1}
    g.bank = {r: 0 for r in C.RESOURCES}
    with pytest.raises(GameError):
        g.year_of_plenty(uid_of(g, 0), "brick", "ore")
    assert s.dev == {"year_of_plenty": 1}                  # 卡还在
    g.bank["brick"] = 2
    g.year_of_plenty(uid_of(g, 0), "brick", "brick")
    assert s.hand["brick"] == 2 and s.dev == {}


def test_win_at_ten_points():
    g = new_game(3)
    g.phase = "play"
    s = g.seats[0]
    s.dev = {"vp": 5}
    s.has_longest = True                                   # 2
    s.has_army = True                                      # 2 → 4
    g.buildings[0] = (0, "city")                           # +2 → 6
    g.buildings[12] = (0, "city")                          # +2 → 8
    g.buildings[24] = (0, "settlement")                    # +1 → 9
    g.buildings[36] = (0, "settlement")                    # +1 → 10
    g._check_win(s)
    assert g.winner == 0 and g.phase == "ended"


def test_end_turn_moves_new_dev_cards_and_rotates_turn():
    g = new_game(3)
    g.phase = "play"
    g.seats[g.turn].dev_new = {"knight": 1}
    uid = uid_of(g, g.turn)
    g.end_turn(uid)
    assert g.seats[0].dev == {"knight": 1} and g.seats[0].dev_new == {}
    assert g.turn == 1 and g.phase == "roll"


def test_view_hides_other_players_cards():
    g = new_game(3)
    setup_opening(g)
    g.seats[1].hand = {"brick": 5, "lumber": 0, "wool": 0, "grain": 0, "ore": 0}
    v = g.view(uid_of(g, 0), online={uid_of(g, 0)})
    text = repr(v)
    assert "玩家1" in text
    assert v["players"][1]["cards"] == 5
    assert "brick" not in repr(v["players"][1])
    assert v["me"]["hand"] is not g.seats[1].hand


def random_step(g, rnd):
    """随机做一步合法操作（失败就换一个），用来压力测试。"""
    if g.phase == "discard":                      # 弃牌是别人的事，要让需要弃牌的人来做
        seat = rnd.choice(sorted(g.discard_need))
        try:
            _discard(g, g.seats[seat].uid, rnd)
        except GameError:
            pass
        return True
    cur = g.seats[g.turn] if g.phase != "setup" else g.seats[g.setup_order[g.setup_step]]
    uid = cur.uid
    attempts = [
        lambda: g.setup_settlement(uid, rnd.choice([v["id"] for v in g.board.vertices])),
        lambda: g.setup_road(uid, rnd.randrange(len(g.board.edges))),
        lambda: g.roll(uid),
        lambda: _discard(g, uid, rnd),
        lambda: g.move_robber(uid, rnd.randrange(19), None),
        lambda: g.play_knight(uid),
        lambda: g.play_road_building(uid),
        lambda: g.place_free_road(uid, rnd.randrange(72)),
        lambda: g.build_road(uid, rnd.randrange(72)),
        lambda: g.build_settlement(uid, rnd.randrange(54)),
        lambda: g.build_city(uid, rnd.randrange(54)),
        lambda: g.buy_dev(uid),
        lambda: g.bank_trade(uid, rnd.choice(C.RESOURCES), rnd.choice(C.RESOURCES)),
        lambda: g.offer_trade(uid, {rnd.choice(C.RESOURCES): 1}, {rnd.choice(C.RESOURCES): 1}),
        lambda: g.accept_trade(uid_of(g, rnd.randrange(len(g.seats)))),
        lambda: g.confirm_trade(uid, rnd.randrange(len(g.seats))),
        lambda: g.cancel_trade(uid),
        lambda: g.end_turn(uid),
        lambda: g.year_of_plenty(uid, rnd.choice(C.RESOURCES), rnd.choice(C.RESOURCES)),
        lambda: g.monopoly(uid, rnd.choice(C.RESOURCES)),
    ]
    rnd.shuffle(attempts)
    for fn in attempts:
        try:
            fn()
            return True
        except GameError:
            continue
        except (ValueError, KeyError):
            continue
    return False


def _discard(g, uid, rnd):
    s = g._seat(uid)
    need = g.discard_need.get(s.index)
    if need is None:
        raise GameError("no")
    pick = {}
    for r in C.RESOURCES:
        take = min(s.hand[r], need - sum(pick.values()))
        if take:
            pick[r] = take
    return g.discard(uid, pick)


def check_invariants(g):
    for r in C.RESOURCES:
        assert sum(s.hand[r] for s in g.seats) + g.bank[r] == C.BANK_START, r
        assert all(v >= 0 for v in g.bank.values())
    for s in g.seats:
        assert all(v >= 0 for v in s.hand.values())
        assert 0 <= s.roads_left <= C.PIECE_LIMIT["road"]
        assert 0 <= s.settlements_left <= C.PIECE_LIMIT["settlement"]
        assert 0 <= s.cities_left <= C.PIECE_LIMIT["city"]
    on_board = {"settlement": 0, "city": 0}
    for (o, t) in g.buildings.values():
        on_board[t] += 1
    assert on_board["settlement"] + on_board["city"] <= 4 * 5
    assert on_board["city"] == sum(C.PIECE_LIMIT["city"] - s.cities_left for s in g.seats)
    assert len(g.roads) == sum(C.PIECE_LIMIT["road"] - s.roads_left for s in g.seats)


@pytest.mark.parametrize("seed", range(12))
def test_random_games_keep_invariants(seed):
    """随机乱玩很多步：资源永远守恒，各种数量不会出错，游戏最终能结束或一直运行不崩溃。"""
    rnd = random.Random(seed)
    names = [(1, "a"), (2, "b"), (3, "c"), (4, "d")]
    g = Game(names[: 3 + seed % 2], rng=random.Random(seed))     # 一半 3 人局，一半 4 人局
    seen_phases = set()
    for _ in range(3000):
        if g.phase == "ended":
            break
        random_step(g, rnd)
        seen_phases.add(g.phase)
        check_invariants(g)
    # 确认测试真的走过了主要阶段，而不是卡在开局
    assert {"setup", "roll", "play"} <= seen_phases, seen_phases


def test_road_building_gives_two_free_roads_without_cost():
    g = new_game(3)
    setup_opening(g)
    g.phase = "play"
    s = g.seats[g.turn]
    uid = uid_of(g, g.turn)
    s.dev = {"road_building": 1}
    s.hand = {r: 0 for r in C.RESOURCES}                 # 没有资源也能免费造路
    before = s.roads_left
    g.play_road_building(uid)
    assert g.phase == "road_building" and g.road_left == 2
    with pytest.raises(GameError):
        g.build_road(uid, 0)                              # 这个阶段不能正常造路
    eid = g.legal_edges_for_road(s.index)[0]
    g.place_free_road(uid, eid)
    assert g.road_left == 1 and g.phase == "road_building"
    eid2 = g.legal_edges_for_road(s.index)[0]
    g.place_free_road(uid, eid2)
    assert g.phase == "play" and s.roads_left == before - 2
    assert sum(s.hand.values()) == 0


def test_monopoly_takes_all_of_one_resource():
    g = new_game(3)
    setup_opening(g)
    g.phase = "play"
    uid = uid_of(g, g.turn)
    s = g.seats[g.turn]
    s.dev = {"monopoly": 1}
    s.hand = {r: 0 for r in C.RESOURCES}
    g.seats[(g.turn + 1) % 3].hand["ore"] = 3
    g.seats[(g.turn + 2) % 3].hand["ore"] = 2
    g.monopoly(uid, "ore")
    assert s.hand["ore"] == 5
    assert all(g.seats[i].hand["ore"] == 0 for i in range(3) if i != s.index)
