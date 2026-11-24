"""荒岛求生的规则测试：不启动服务器，直接调用 Game。"""
from __future__ import annotations

import json
import math

import pytest

from . import content as C
from .game import (
    DEEP, GRASS, LAND, SAND, SHALLOW, W, H, Animal, Game, GameError, Resource,
)


def open_spot(g: Game, r: int = 6):
    """找一块 (2r+1)² 的草地，清掉里面的树、石头和动物，方便测试。返回 (x, z) 格子坐标。"""
    for z in range(r + 2, H - r - 2):
        for x in range(r + 2, W - r - 2):
            if all(g.terrain_at(x + dx, z + dz) == GRASS
                   for dx in range(-r, r + 1) for dz in range(-r, r + 1)):
                clear(g, x, z, r)
                return x, z
    raise AssertionError("找不到草地")


def clear(g: Game, x: int, z: int, r: int) -> None:
    """清空一个方块里的所有资源点（树、石头、灌木丛……）和动物。"""
    for res in g.res:
        if res.present and abs(res.x - x) <= r and abs(res.z - z) <= r:
            res.present = False
            res.regrow_at = 1e12                  # 不让它在测试途中长回来
            g.tree_at.pop(res.z * W + res.x, None)
            g.rock_at.pop(res.z * W + res.x, None)
    g.animals = [a for a in g.animals if abs(a.x - x) > r or abs(a.z - z) > r]


def place(p, x: float, z: float) -> None:
    p.x, p.z = x, z


def passed(g: Game, seconds: float) -> None:
    """让时间过去若干秒（不跑 tick，只改时间，方便测试操作冷却和生长）。"""
    g.time += seconds


def build(g: Game, p, kind: str, fx: float = 1.0, fz: float = 0.0) -> None:
    g.act(p, "build", {"kind": kind, "fx": fx, "fz": fz})


def craft(g: Game, p, recipe: str) -> None:
    g.act(p, "craft", {"recipe": recipe})


@pytest.fixture
def g():
    return Game(2026)


@pytest.fixture
def spot(g):
    """一块清空了的草地，玩家站在中间。"""
    x, z = open_spot(g)
    p = g.join(1, "甲", "chef")
    place(p, x + 0.5, z + 0.5)
    return g, p, x, z


# ------------------------------------------------------------ 地图与资源

def test_map_is_a_big_island_and_deterministic():
    a, b = Game(2026), Game(2026)
    assert bytes(a.terrain) == bytes(b.terrain)            # 同一个种子，同一座岛
    assert bytes(Game(7).terrain) != bytes(a.terrain)
    land = sum(1 for t in a.terrain if t in LAND)
    assert 0.2 < land / (W * H) < 0.6
    assert a.terrain_at(0, 0) == DEEP
    assert any(t == SHALLOW for t in a.terrain)


def test_many_kinds_of_resources_exist(g):
    kinds = {r.kind for r in g.res}
    assert {"tree", "bush", "herb", "reed", "rock", "shell", "mushroom"} <= kinds
    assert sum(1 for an in g.animals if an.kind == "rabbit") > 10


def test_player_cannot_walk_into_deep_sea(g):
    spot = next((tx, tz) for tz in range(H) for tx in range(W)
                if g.terrain_at(tx, tz) in (SAND, SHALLOW) and g.terrain_at(tx - 1, tz) == DEEP)
    p = g.join(1, "甲", "chef")
    place(p, spot[0] + 0.5, spot[1] + 0.5)
    g.set_move(p, -1, 0)
    for _ in range(50):
        g.tick()
    assert g.terrain_at(p.x, p.z) != DEEP
    assert p.x >= spot[0] - 0.01


def test_tree_blocks_movement(spot):
    g, p, x, z = spot
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    place(p, x + 0.5, z + 0.5)
    g.set_move(p, 1, 0)
    for _ in range(30):
        g.tick()
    assert p.x < x + 1


# ------------------------------------------------------------ 采集

def test_chop_tree_with_stone_axe_gives_more_wood_then_regrows(spot):
    g, p, x, z = spot
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    p.inv = {"stone_axe": 1}
    for _ in range(3):
        g.act(p, "interact", {})
        passed(g, 1)
    assert p.inv["wood"] == 6                  # 石斧：每下 2 个木材
    assert tree.present is False and (z * W + x + 1) not in g.tree_at
    passed(g, C.RESOURCES["tree"][2] + 1)
    g.tick()
    assert tree.present is True and tree.hp == 3


def test_rock_needs_stone_pick(spot):
    g, p, x, z = spot
    rock = Resource(id=g._new_id(), kind="rock", x=x + 1, z=z, hp=3)
    g.res.append(rock)
    g.rock_at[z * W + x + 1] = rock.id
    with pytest.raises(GameError):
        g.act(p, "interact", {})                 # 没有石镐
    passed(g, 1)
    p.inv = {"stone_pick": 1}
    g.act(p, "interact", {})
    assert p.inv["stone"] == 1


def test_gather_small_resources(spot):
    g, p, x, z = spot
    shell = Resource(id=g._new_id(), kind="shell", x=x, z=z, hp=1)
    g.res.append(shell)
    place(p, x + 0.5, z + 0.5)
    g.act(p, "interact", {})
    assert p.inv["shell"] == 1 and shell.present is False


def test_action_cooldown_stops_spam(spot):
    g, p, x, z = spot
    tree = Resource(id=g._new_id(), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    g.act(p, "interact", {})
    g.act(p, "interact", {})
    assert p.inv["wood"] == 1


def test_hunt_rabbit_and_it_flees(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    before = math.hypot(rabbit.x - p.x, rabbit.z - p.z)
    g.tick()
    assert math.hypot(rabbit.x - p.x, rabbit.z - p.z) > before
    rabbit.x, rabbit.z = p.x + 1, p.z
    for _ in range(2):
        g.act(p, "interact", {})
        passed(g, 1)
    assert rabbit not in g.animals and p.inv["raw_meat"] == 1


def test_spear_kills_rabbit_in_one_hit(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    p.inv = {"spear": 1}
    g.act(p, "interact", {})
    assert rabbit not in g.animals


def test_fishing_on_shallow_water(g, monkeypatch):
    spot = next((tx, tz) for tz in range(1, H - 1) for tx in range(1, W - 1)
                if g.terrain_at(tx, tz) == SAND and g.terrain_at(tx - 1, tz) == SHALLOW)
    clear(g, spot[0], spot[1], 3)
    p = g.join(1, "甲", "chef")
    place(p, spot[0] + 0.5, spot[1] + 0.5)
    monkeypatch.setattr(g.rng, "random", lambda: 0.0)
    g.act(p, "interact", {})
    assert p.inv["raw_fish"] == 1
    with pytest.raises(GameError):
        g.act(p, "interact", {})
    passed(g, 2.1)
    g.act(p, "interact", {})
    assert p.inv["raw_fish"] == 2


# ------------------------------------------------------------ 合成

def test_hand_recipes_need_no_station(spot):
    g, p, x, z = spot
    p.inv = {"wood": 1, "fiber": 3}
    craft(g, p, "stick")
    craft(g, p, "rope")
    assert p.inv["stick"] == 2 and p.inv["rope"] == 1


def test_tools_need_a_workbench(spot):
    g, p, x, z = spot
    p.inv = {"stick": 2, "stone": 3, "rope": 1}
    with pytest.raises(GameError):
        craft(g, p, "stone_axe")                 # 旁边没有工作台
    p.inv["wood"] = 6
    p.inv["stone"] += 2
    build(g, p, "workbench")
    craft(g, p, "stone_axe")
    assert p.inv["stone_axe"] == 1


def test_missing_materials_are_named(spot):
    g, p, x, z = spot
    p.inv = {}
    with pytest.raises(GameError) as e:
        craft(g, p, "stick")
    assert "木材" in str(e.value)


def test_medicine_is_doctor_only_and_still_works(spot):
    g, p, x, z = spot
    p.inv = {"herb": 3}
    with pytest.raises(GameError):
        craft(g, p, "medicine")
    p.role = "doctor"
    craft(g, p, "medicine")
    assert p.inv["medicine"] == 1


# ------------------------------------------------------------ 建造与升级

def test_build_workbench_costs_materials_and_is_solid(spot):
    g, p, x, z = spot
    p.inv = {"wood": 6, "stone": 2}
    build(g, p, "workbench")
    assert p.inv.get("wood", 0) == 0 and p.inv.get("stone", 0) == 0
    kinds = [b.kind for b in g.buildings.values()]
    assert kinds == ["workbench"]
    b = next(iter(g.buildings.values()))
    assert g._walkable(b.x + 0.5, b.z + 0.5) is False        # 建筑挡路


def test_build_needs_materials_and_clear_land(spot):
    g, p, x, z = spot
    p.inv = {"wood": 1}
    with pytest.raises(GameError):
        build(g, p, "workbench")
    p.inv = {"wood": 6, "stone": 2}
    tree = Resource(id=g._new_id(), kind="tree", x=x + 2, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 2] = tree.id
    with pytest.raises(GameError):
        build(g, p, "workbench")                 # 面前是树


def test_upgrade_workbench_unlocks_iron_tools(spot):
    g, p, x, z = spot
    p.inv = {"wood": 6, "stone": 2}
    build(g, p, "workbench")
    p.inv = {"wood": 10, "stone": 6, "stick": 2, "iron_ingot": 2, "rope": 1}
    with pytest.raises(GameError):
        craft(g, p, "iron_axe")                  # 工作台还是 1 级
    g.act(p, "upgrade", {})
    b = next(iter(g.buildings.values()))
    assert b.level == 2
    craft(g, p, "iron_axe")
    assert p.inv["iron_axe"] == 1


def test_furnace_smelts_iron(spot):
    g, p, x, z = spot
    p.inv = {"stone": 8}
    build(g, p, "furnace")
    p.inv["iron_ore"] = 2
    craft(g, p, "iron_ingot")
    assert p.inv["iron_ingot"] == 1


def test_campfire_needs_fuel_and_cooks_when_lit(spot):
    g, p, x, z = spot
    p.inv = {"wood": 3, "stone": 1, "raw_fish": 1}
    build(g, p, "campfire")
    with pytest.raises(GameError):
        craft(g, p, "cook_fish")                 # 还没加柴，不烧
    p.inv["wood"] = 1
    g.act(p, "fuel", {})
    assert g.buildings[next(iter(g.buildings))].fuel_until > g.time
    craft(g, p, "cook_fish")
    assert p.inv["cooked_fish"] == 1


def test_chef_gets_extra_satiety_from_cooking_only_chef(spot):
    g, p, x, z = spot
    p.inv = {"wood": 4, "stone": 1, "raw_meat": 1}
    build(g, p, "campfire")                      # 火堆在 (x+2, z)
    p.inv["wood"] = 1
    g.act(p, "fuel", {})
    p.hunger = 40.0
    craft(g, p, "cook_meat")
    assert p.hunger == pytest.approx(40 + 15)    # 厨师做饭，自己额外吃饱
    cook = g.join(2, "普通", "priest")
    place(cook, x + 0.5, z + 0.5)                # 离火堆 2 格，能做饭
    cook.inv = {"raw_meat": 1}
    cook.hunger = 40.0
    craft(g, cook, "cook_meat")
    assert cook.hunger == pytest.approx(40)      # 其他人没有这个加成


def test_level_two_dishes_need_level_two_campfire(spot):
    g, p, x, z = spot
    p.inv = {"wood": 3, "stone": 1, "carrot": 1, "potato": 1, "mushroom": 1}
    build(g, p, "campfire")
    p.inv["wood"] = 1
    g.act(p, "fuel", {})
    with pytest.raises(GameError):
        craft(g, p, "veg_soup")
    p.inv.update({"wood": 4, "stone": 4})
    g.act(p, "upgrade", {})
    craft(g, p, "veg_soup")
    assert p.inv["veg_soup"] == 1


# ------------------------------------------------------------ 种田

def test_farm_till_plant_grow_harvest(spot):
    g, p, x, z = spot
    p.inv = {"hoe": 1, "carrot_seed": 1}
    g.act(p, "farm", {"fx": 1, "fz": 0})         # 翻土
    plot = next(b for b in g.buildings.values() if b.kind == "plot")
    assert plot.kind == "plot" and (plot.x, plot.z) == (x + 1, z)
    g.act(p, "farm", {"fx": 1, "fz": 0})         # 播种（面前是农田）
    assert plot.crop == "carrot" and p.inv.get("carrot_seed", 0) == 0
    with pytest.raises(GameError):
        g.act(p, "farm", {"fx": 1, "fz": 0})     # 还没成熟
    passed(g, C.CROPS["carrot"]["grow"] + 1)
    g.act(p, "farm", {"fx": 1, "fz": 0})         # 收获
    assert plot.crop is None
    assert p.inv["carrot"] >= 2


def test_farm_needs_hoe(spot):
    g, p, x, z = spot
    with pytest.raises(GameError):
        g.act(p, "farm", {"fx": 1, "fz": 0})


def test_plot_state_shows_growth_stage(spot):
    g, p, x, z = spot
    p.inv = {"hoe": 1, "potato_seed": 1}
    g.act(p, "farm", {"fx": 1, "fz": 0})
    g.act(p, "farm", {"fx": 1, "fz": 0})
    row = next(r for r in g.view(p, False)["buildings"] if r[1] == "plot")
    assert row[5] == "potato:0"
    passed(g, C.CROPS["potato"]["grow"] * 0.6)
    row = next(r for r in g.view(p, False)["buildings"] if r[1] == "plot")
    assert row[5] == "potato:1"


# ------------------------------------------------------------ 房子

def build_house(g, p):
    p.inv = {"wood": 20, "stone": 6, "rope": 2}
    build(g, p, "house", fx=0.0, fz=1.0)
    return next(b for b in g.buildings.values() if b.kind == "house")


def test_build_house_enter_place_furniture_and_leave(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    assert house.kind == "house"
    place(p, house.x + 1.5, house.z + 3.6)       # 站在门口
    g.act(p, "enter", {})
    assert p.house == house.id
    p.inv = {"bed": 1, "lamp": 1}
    g.act(p, "place", {"item": "bed", "fx": 0, "fz": -1})
    g.act(p, "place", {"item": "lamp", "fx": 1, "fz": 0})
    assert {f["kind"] for f in house.furniture} == {"bed", "lamp"}
    g.act(p, "exit", {})
    assert p.house is None


def test_inside_view_is_room_and_hides_outside(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    view = g.view(p, True)
    assert view["room"]["size"] == C.ROOM_SIZE[1]
    assert view["animals"] == [] and view["buildings"] == [] and "res" not in view


def test_players_only_see_players_in_the_same_house(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    friend = g.join(2, "乙", "doctor")
    place(friend, x + 0.5, z + 0.5)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    assert [q[0] for q in g.view(p, False)["players"]] == [p.id]
    assert [q[0] for q in g.view(friend, False)["players"]] == [friend.id, ]


def test_bed_restores_sanity_inside(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    house.furniture.append({"id": g._new_id(), "kind": "bed", "x": p.x, "z": p.z})
    p.sanity = 50.0
    for _ in range(50):
        g.tick()
    assert p.sanity > 50 - 0.02 * 5 + 1


def test_pickup_furniture_returns_it(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    p.inv = {"chair": 1}
    g.act(p, "place", {"item": "chair", "fx": 0, "fz": -1})
    g.act(p, "interact", {})
    assert house.furniture == [] and p.inv["chair"] == 1


def test_interact_enters_house_when_close(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "interact", {})
    assert p.house == house.id


def test_house_upgrade_makes_room_bigger(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    p.inv = {"wood": 20, "stone": 10, "rope": 4}
    g.act(p, "upgrade", {})
    assert house.level == 2 and C.ROOM_SIZE[2] == 8


def test_outdoor_actions_refused_inside(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    with pytest.raises(GameError):
        g.act(p, "farm", {"fx": 1, "fz": 0})


# ------------------------------------------------------------ 生存数值、牧师、医生

def test_low_stats_drain_health_and_death_then_respawn(g):
    p = g.join(1, "甲", "chef")
    p.hunger = 0.0
    p.sanity = 100.0
    start = p.health
    for _ in range(10):
        g.tick()
    assert p.health == pytest.approx(start - 1, abs=0.2)
    p.health = 0.05
    g.tick()
    assert p.dead is True and p.health == 0
    with pytest.raises(GameError):
        g.act(p, "interact", {})
    g.act(p, "respawn", {})
    assert p.dead is False and p.health == 100 and p.hunger == 100


def test_priest_blessing_only_reaches_nearby_outdoor_teammates(spot):
    g, p, x, z = spot
    priest = g.join(3, "牧", "priest")
    chef = g.join(4, "厨", "chef")
    place(priest, x + 0.5, z + 0.5)
    place(chef, x + 2.5, z + 0.5)
    chef.sanity = priest.sanity = 50.0
    for _ in range(100):
        g.tick()
    assert chef.sanity > 50 - 0.2 + 5
    assert priest.sanity == pytest.approx(50 - 0.1, abs=0.05)


def test_doctor_heals_nearby_teammate(spot):
    g, p, x, z = spot
    doc = g.join(5, "医", "doctor")
    pal = g.join(6, "伙伴", "chef")
    place(p, x + 5.5, z + 5.5)                   # 测试里的第一个玩家走远，免得抢走治疗对象
    place(doc, x + 0.5, z + 0.5)
    place(pal, x + 1.5, z + 0.5)
    pal.health, pal.sick = 40.0, True
    doc.inv = {"medicine": 1}
    g.act(doc, "heal", {})
    assert pal.health == pytest.approx(70.0) and pal.sick is False


def test_raw_food_can_make_you_sick_cooked_does_not(g, monkeypatch):
    p = g.join(1, "甲", "chef")
    p.inv = {"raw_meat": 1, "cooked_meat": 1}
    monkeypatch.setattr(g.rng, "random", lambda: 0.0)
    g.act(p, "use", {"item": "cooked_meat"})
    assert p.sick is False
    g.act(p, "use", {"item": "raw_meat"})
    assert p.sick is True


# ------------------------------------------------------------ 存档与下线

def test_world_survives_save_and_reload(spot):
    g, p, x, z = spot
    p.inv = {"wood": 20, "stone": 6, "rope": 2, "hoe": 1, "carrot_seed": 1}
    build(g, p, "workbench")
    g.act(p, "farm", {"fx": 0, "fz": 1})
    g.act(p, "farm", {"fx": 0, "fz": 1})
    house = build_house(g, p)
    for _ in range(10):
        g.tick()
    data = json.loads(json.dumps(g.to_dict()))
    g2 = Game.from_dict(data)
    assert g2.tick_no == g.tick_no
    assert sorted(g2.buildings) == sorted(g.buildings)
    assert g2.build_at == g.build_at
    assert g2.buildings[house.id].kind == "house"
    assert [(r.kind, r.hp, r.present) for r in g2.res] == [(r.kind, r.hp, r.present) for r in g.res]


def test_rejoin_resumes_inside_the_house(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    g.leave(p.id)
    q = g.join(1, "甲", "chef")
    assert q.house == house.id and q.role == "chef"


def test_leave_keeps_character_while_world_runs(g):
    p = g.join(9, "丙", "chef")
    p.hunger = 60.0
    g.leave(p.id)
    frozen = dict(g.saved[9])
    for _ in range(100):
        g.tick()
    assert g.time > 9
    assert g.saved[9] == frozen
    assert g.join(9, "丙", "chef").hunger == pytest.approx(60.0)


def test_rejoin_with_another_role_starts_fresh(g):
    p = g.join(8, "乙", "chef")
    p.inv = {"wood": 9}
    g.leave(p.id)
    q = g.join(8, "乙", "priest")
    assert q.role == "priest" and q.inv == {}


def test_wrong_save_version_is_rejected(g):
    d = g.to_dict()
    with pytest.raises(ValueError):
        Game.from_dict({**d, "version": 1})


# ------------------------------------------------------------ 视野

def test_view_only_sends_nearby_things(g):
    p = g.join(1, "甲", "chef")
    view = g.view(p, with_resources=True)
    assert view["me"]["id"] == p.id
    for _, _, x, z, _ in view["res"]:
        assert (x + 0.5 - p.x) ** 2 + (z + 0.5 - p.z) ** 2 <= 32 ** 2
    for _, _, x, z, _ in view["animals"]:
        assert (x - p.x) ** 2 + (z - p.z) ** 2 <= 32 ** 2
    assert len(view["players"]) == 1
    p.events.append("测试消息")
    assert g.view(p, False)["me"]["events"] == ["测试消息"]
    assert g.view(p, False)["me"]["events"] == []
