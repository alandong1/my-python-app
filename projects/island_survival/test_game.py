"""荒岛求生的规则测试：不启动服务器，直接调用 Game。"""
from __future__ import annotations

import math

import pytest

from .game import (
    DEEP, GRASS, LAND, PLANT_REGROW, SAND, SHALLOW, TREE_REGROW, W, H,
    Animal, Fire, Game, GameError, Resource,
)


def open_spot(g: Game, r: int = 5):
    """找一块 (2r+1)² 的草地，清掉里面的树和动物，方便测试。返回 (x, z) 格子坐标。"""
    for z in range(r + 2, H - r - 2):
        for x in range(r + 2, W - r - 2):
            if all(g.terrain_at(x + dx, z + dz) == GRASS
                   for dx in range(-r, r + 1) for dz in range(-r, r + 1)):
                clear(g, x, z, r)
                return x, z
    raise AssertionError("找不到草地")


def clear(g: Game, x: int, z: int, r: int) -> None:
    for idx in list(g.tree_at):
        tx, tz = idx % W, idx // W
        if abs(tx - x) <= r and abs(tz - z) <= r:
            g.res[g.tree_at.pop(idx)].present = False
    g.animals = [a for a in g.animals if abs(a.x - x) > r or abs(a.z - z) > r]


def place(g: Game, p, x: float, z: float) -> None:
    p.x, p.z = x, z


def passed(g: Game, seconds: float) -> None:
    """让时间过去若干秒（不跑 tick，只改时间，方便测试操作冷却）。"""
    g.time += seconds


@pytest.fixture
def g():
    return Game(2026)


def test_map_is_a_big_island_and_deterministic():
    a, b = Game(2026), Game(2026)
    assert bytes(a.terrain) == bytes(b.terrain)            # 同一个种子，同一座岛
    assert bytes(Game(7).terrain) != bytes(a.terrain)     # 换种子，换一座岛
    land = sum(1 for t in a.terrain if t in LAND)
    assert 0.2 < land / (W * H) < 0.6                     # 岛占地图的一部分，四周是海
    assert a.terrain_at(0, 0) == DEEP                     # 角落一定是深海
    assert any(t == SHALLOW for t in a.terrain)           # 海岸边有浅海
    kinds = {r.kind for r in a.res}
    assert {"tree", "bush", "herb"} <= kinds              # 有树、灌木丛、草本植物
    assert sum(1 for an in a.animals if an.kind == "rabbit") > 10
    assert sum(1 for an in a.animals if an.kind == "crab") > 5


def test_players_spawn_on_land_apart_from_each_other(g):
    first = g.join(1, "甲", "chef")
    second = g.join(2, "乙", "doctor")
    assert g.terrain_at(first.x, first.z) in LAND
    assert g.terrain_at(second.x, second.z) in LAND
    assert math.hypot(first.x - second.x, first.z - second.z) > 10   # 不会出生在一起


def test_join_rejects_unknown_role(g):
    with pytest.raises(GameError):
        g.join(1, "甲", "warrior")


def test_player_cannot_walk_into_deep_sea(g):
    # 找一块靠近深海的陆地
    spot = next((tx, tz) for tz in range(H) for tx in range(W)
                if g.terrain_at(tx, tz) in (SAND, SHALLOW) and g.terrain_at(tx - 1, tz) == DEEP)
    p = g.join(1, "甲", "chef")
    place(g, p, spot[0] + 0.5, spot[1] + 0.5)
    g.set_move(p, -1, 0)                                   # 往深海走
    for _ in range(50):
        g.tick()
    assert g.terrain_at(p.x, p.z) != DEEP
    assert p.x >= spot[0] - 0.01                          # 没走进海里


def test_tree_blocks_movement(g):
    x, z = open_spot(g)
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    g.set_move(p, 1, 0)
    for _ in range(30):
        g.tick()
    assert p.x < x + 1                                     # 撞到树停下


def test_chop_tree_gives_wood_then_regrows(g, monkeypatch):
    x, z = open_spot(g)
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    for _ in range(3):
        g.act(p, "interact", {})
        passed(g, 1)
    assert p.inv["wood"] == 3
    assert tree.present is False                           # 砍倒了
    assert (z * W + x + 1) not in g.tree_at               # 不再挡路
    passed(g, TREE_REGROW + 1)
    g.tick()
    assert tree.present is True and tree.hp == 3          # 树长回来了


def test_action_cooldown_stops_spam(g):
    x, z = open_spot(g)
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    g.act(p, "interact", {})
    g.act(p, "interact", {})                               # 同一时刻再按，不计
    assert p.inv["wood"] == 1


def test_gather_bush_and_herb(g):
    x, z = open_spot(g)
    bush = Resource(id=g._new_id(), kind="bush", x=x, z=z, hp=2)
    g.res.append(bush)
    p = g.join(1, "甲", "doctor")
    place(g, p, x + 0.5, z + 0.5)
    g.act(p, "interact", {})
    assert p.inv["berry"] == 1
    passed(g, 1)
    g.act(p, "interact", {})
    assert p.inv["berry"] == 2 and bush.present is False
    passed(g, PLANT_REGROW + 1)
    g.tick()
    assert bush.present is True


def test_hunt_rabbit_and_it_flees(g):
    x, z = open_spot(g)
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    before = math.hypot(rabbit.x - p.x, rabbit.z - p.z)
    g.tick()
    assert math.hypot(rabbit.x - p.x, rabbit.z - p.z) > before   # 兔子看到人就跑
    rabbit.x, rabbit.z = p.x + 1, p.z
    for _ in range(2):
        g.act(p, "interact", {})
        passed(g, 1)
    assert rabbit not in g.animals and p.inv["raw_meat"] == 1


def test_fishing_on_shallow_water(g, monkeypatch):
    spot = next((tx, tz) for tz in range(1, H - 1) for tx in range(1, W - 1)
                if g.terrain_at(tx, tz) == SAND and g.terrain_at(tx - 1, tz) == SHALLOW)
    clear(g, spot[0], spot[1], 3)                          # 螃蟹和树不能抢了钓鱼的机会
    p = g.join(1, "甲", "chef")
    place(g, p, spot[0] + 0.5, spot[1] + 0.5)
    monkeypatch.setattr(g.rng, "random", lambda: 0.0)     # 每次都钓到
    g.act(p, "interact", {})
    assert p.inv["raw_fish"] == 1
    with pytest.raises(GameError):                         # 2 秒内不能再钓
        g.act(p, "interact", {})
    passed(g, 2.1)
    g.act(p, "interact", {})
    assert p.inv["raw_fish"] == 2


def test_nothing_to_interact_with(g):
    x, z = open_spot(g)
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    with pytest.raises(GameError):
        g.act(p, "interact", {})


def test_build_fire_needs_wood_and_cooking_needs_fire(g):
    x, z = open_spot(g)
    p = g.join(1, "甲", "chef")
    place(g, p, x + 0.5, z + 0.5)
    p.inv = {"raw_fish": 1}
    with pytest.raises(GameError):
        g.act(p, "build_fire", {})                         # 没有木材
    with pytest.raises(GameError):
        g.act(p, "cook", {})                               # 没有火
    p.inv = {"wood": 3, "raw_fish": 1}
    g.act(p, "build_fire", {})
    assert p.inv.get("wood", 0) == 0 and len(g.fires) == 1
    g.act(p, "cook", {})
    assert p.inv["cooked_fish"] == 1 and p.inv["raw_fish"] == 0


def test_chef_gets_extra_satiety_from_cooking(g):
    x, z = open_spot(g)
    chef = g.join(1, "厨", "chef")
    cook = g.join(2, "普通", "priest")
    for p in (chef, cook):
        place(g, p, x + 0.5, z + 0.5)
    g.fires.append(Fire(id=g._new_id(), x=x + 0.5, z=z + 0.5, until=g.time + 300))
    chef.hunger = cook.hunger = 40.0
    chef.inv = {"raw_meat": 1}
    cook.inv = {"raw_meat": 1}
    g.act(chef, "cook", {})
    g.act(cook, "cook", {})
    assert chef.hunger == pytest.approx(40 + 15)            # 厨师做饭，自己额外吃饱
    assert cook.hunger == pytest.approx(40)                 # 其他人没有这个加成
    assert chef.inv["cooked_meat"] == 1 and cook.inv["cooked_meat"] == 1


def test_raw_food_can_make_you_sick_cooked_does_not(g, monkeypatch):
    p = g.join(1, "甲", "chef")
    p.inv = {"raw_meat": 1, "cooked_meat": 1}
    monkeypatch.setattr(g.rng, "random", lambda: 0.0)      # 每次都“倒霉”
    g.act(p, "use", {"item": "cooked_meat"})
    assert p.sick is False
    g.act(p, "use", {"item": "raw_meat"})
    assert p.sick is True


def test_doctor_makes_medicine_and_heals_teammate(g):
    x, z = open_spot(g)
    doc = g.join(1, "医", "doctor")
    pal = g.join(2, "伙伴", "chef")
    place(g, doc, x + 0.5, z + 0.5)
    place(g, pal, x + 1.5, z + 0.5)
    doc.inv = {"herb": 3}
    with pytest.raises(GameError):
        g.act(pal, "craft", {})                             # 厨师不会制药
    g.act(doc, "craft", {})
    assert doc.inv["medicine"] == 1 and doc.inv["herb"] == 0
    pal.health, pal.sick = 40.0, True
    g.act(doc, "heal", {})
    assert pal.health == pytest.approx(70.0) and pal.sick is False
    with pytest.raises(GameError):
        g.act(doc, "heal", {})                              # 草药用完了


def test_medicine_cures_yourself(g):
    p = g.join(1, "甲", "chef")
    p.health, p.sick, p.inv = 50.0, True, {"medicine": 1}
    g.act(p, "use", {"item": "medicine"})
    assert p.health == pytest.approx(75.0) and p.sick is False


def test_priest_slows_sanity_and_blesses_nearby_teammates(g):
    x, z = open_spot(g)
    priest = g.join(1, "牧", "priest")
    chef = g.join(2, "厨", "chef")
    far = g.join(3, "远", "chef")
    place(g, priest, x + 0.5, z + 0.5)
    place(g, chef, x + 2.5, z + 0.5)
    place(g, far, x + 0.5 + 20, z + 0.5)
    chef.sanity = far.sanity = 50.0
    priest.sanity = 50.0
    for _ in range(100):                                    # 10 秒
        g.tick()
    base_chef_loss = 0.02 * 10                              # 普通人每秒 0.02
    assert chef.sanity > 50 - base_chef_loss + 5            # 牧师光环：队友恢复精神
    assert far.sanity < 50 - base_chef_loss + 5             # 太远，没有光环
    assert priest.sanity == pytest.approx(50 - 0.01 * 10, abs=0.05)   # 牧师自己慢慢掉


def test_low_stats_drain_health_and_death_then_respawn(g):
    p = g.join(1, "甲", "chef")
    p.hunger = 0.0
    p.sanity = 100.0
    start = p.health
    for _ in range(10):                                     # 1 秒
        g.tick()
    assert p.health == pytest.approx(start - 1, abs=0.2)     # 饱食为 0：每秒扣 1 点
    p.health = 0.05
    g.tick()
    assert p.dead is True and p.health == 0
    with pytest.raises(GameError):
        g.act(p, "interact", {})
    g.act(p, "respawn", {})
    assert p.dead is False and p.health == 100 and p.hunger == 100


def test_healthy_player_slowly_recovers(g):
    p = g.join(1, "甲", "chef")
    p.health = 80.0
    for _ in range(100):
        g.tick()
    assert p.health > 80


def test_view_only_sends_nearby_things(g):
    p = g.join(1, "甲", "chef")
    view = g.view(p, with_resources=True)
    assert view["me"]["id"] == p.id
    for _, _, x, z, _ in view["res"]:
        assert (x + 0.5 - p.x) ** 2 + (z + 0.5 - p.z) ** 2 <= 32 ** 2
    for _, _, x, z, _ in view["animals"]:
        assert (x - p.x) ** 2 + (z - p.z) ** 2 <= 32 ** 2
    assert len(view["players"]) == 1
    # 事件只发一次
    p.events.append("测试消息")
    assert g.view(p, False)["me"]["events"] == ["测试消息"]
    assert g.view(p, False)["me"]["events"] == []
