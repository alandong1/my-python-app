"""游戏逻辑测试：不经过网络，直接调用 Game。"""
import pytest

from projects.lordwar.game import Game, GameError


def rich(game, p):
    p.res = {"gold": 50000.0, "wood": 50000.0}


def expand_until_plains(game, p, need):
    for _ in range(30):
        for c in list(p.tiles):
            for n in game.neighbors4(*c):
                try:
                    game.expand(p, *n)
                except GameError:
                    pass
        free = [c for c in p.tiles if game.tile(*c).terrain == "plains" and not game.tile(*c).building]
        if len(free) >= need:
            return free
    raise AssertionError("拓展不到足够的平原")


def test_same_account_same_player():
    g = Game(1)
    a = g.join(1, "甲")
    assert g.join(1, "甲") is a
    assert g.join(2, "乙") is not a
    assert a.alive and len(a.tiles) >= 5 and a.hq


def test_expand_rules():
    g = Game(2)
    a = g.join(1, "甲")
    x, y = a.hq
    with pytest.raises(GameError):
        g.expand(a, x + 5, y + 5)          # 不相邻
    a.res["gold"] = 0
    target = next(n for c in a.tiles for n in g.neighbors4(*c)
                  if not g.tile(*n).owner and g.tile(*n).terrain not in ("water", "mountain")
                  and not g.tile(*n).npc)
    with pytest.raises(GameError):
        g.expand(a, *target)               # 金币不足


def test_build_research_and_train_gating():
    g = Game(3)
    a = g.join(1, "甲")
    rich(g, a)
    with pytest.raises(GameError):
        g.train(a, "infantry", 1)          # 没有兵营
    free = expand_until_plains(g, a, 2)
    g.build(a, *free[0], "barracks")
    g.build(a, *free[1], "smithy")
    with pytest.raises(GameError):
        g.train(a, "cavalry", 1)           # 兵营等级不够
    g.research(a, "weapon")
    with pytest.raises(GameError):
        g.research(a, "weapon")            # 铁匠铺等级不够
    for _ in range(3):
        g.upgrade(a, *free[0])
    g.train(a, "cavalry", 5)
    for _ in range(100):
        g.tick()
    assert sum(ar.units.get("cavalry", 0) for ar in g.armies.values() if ar.owner == a.id) == 5


def test_conquest_and_respawn():
    g = Game(42)
    a = g.join(1, "甲")
    b = g.join(2, "乙")
    rich(g, a)
    free = expand_until_plains(g, a, 1)
    g.build(a, *free[0], "barracks")
    for _ in range(3):
        g.upgrade(a, *free[0])
    g.train(a, "cavalry", 20)
    g.train(a, "catapult", 10)
    for _ in range(400):
        g.tick()
    army = max((x for x in g.armies.values() if x.owner == a.id), key=lambda x: x.size())
    a.explored |= {(x, y) for x in range(g.w) for y in range(g.h)}
    g.move(a, army.id, *b.hq)
    for _ in range(800):
        g.tick()
    assert not b.alive and not b.tiles
    g.respawn(b)
    assert b.alive and b.hq


def test_view_hides_fog():
    g = Game(5)
    a = g.join(1, "甲")
    b = g.join(2, "乙")
    view = g.view_for(a)
    visible = {(t[0], t[1]) for t in view["tiles"]}
    assert b.hq not in visible
    assert all(ar["owner"] == a.id for ar in view["armies"])


def test_maps_always_have_room_and_reachable_center():
    """回归测试：曾经中央被湖泊包围时，整张地图几乎都变成了高山，玩家无法出生（seed 7）。"""
    from projects.lordwar import config as C
    for seed in list(range(40)) + [7]:
        g = Game(seed)
        walkable = sum(1 for row in g.tiles for t in row if t.terrain not in C.IMPASSABLE)
        assert walkable > g.w * g.h // 3, f"seed {seed} 可走地块只有 {walkable}"
        assert g.tile(g.w // 2, g.h // 2).terrain not in C.IMPASSABLE
        players = [g.join(i, f"p{i}") for i in range(4)]
        assert all(p.alive for p in players)
