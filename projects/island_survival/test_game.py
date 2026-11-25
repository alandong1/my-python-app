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


def interact_and_wait(g: Game, p, max_ticks: int = 400) -> None:
    """按一下互动，然后让时间走，直到进度条走完（或者动作被取消）。"""
    g.act(p, "interact", {})
    for _ in range(max_ticks):
        if p.work is None:
            return
        g.tick()
    raise AssertionError("动作一直没有完成")


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
    tree = Resource(id=len(g.res), kind="tree", x=x + 1, z=z, hp=3)
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
    tree = Resource(id=len(g.res), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    p.inv = {"stone_axe": 1}
    interact_and_wait(g, p)                      # 砍一次就倒下：木材随机 5–9，石斧再 +1
    assert 6 <= p.inv["wood"] <= 10
    assert tree.present is False and (z * W + x + 1) not in g.tree_at
    passed(g, C.RESOURCES["tree"][2] + 1)
    g.tick()
    assert tree.present is True and tree.hp == 3


def test_rock_gives_stone_by_hand_and_stone_pick_is_not_needed(spot):
    g, p, x, z = spot
    rock = Resource(id=len(g.res), kind="rock", x=x + 1, z=z, hp=3)
    g.res.append(rock)
    g.rock_at[z * W + x + 1] = rock.id
    interact_and_wait(g, p)                      # 空手也能挖：石头 4–6 个，一次拿完
    assert 4 <= p.inv["stone"] <= 6
    assert rock.present is False


def test_gather_small_resources(spot):
    g, p, x, z = spot
    shell = Resource(id=len(g.res), kind="shell", x=x, z=z, hp=1)
    g.res.append(shell)
    place(p, x + 0.5, z + 0.5)
    interact_and_wait(g, p)
    assert p.inv["shell"] == 1 and shell.present is False


def test_pressing_interact_twice_does_not_stack_work(spot):
    g, p, x, z = spot
    tree = Resource(id=len(g.res), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    g.act(p, "interact", {})
    g.act(p, "interact", {})                     # 正在砍，再按不会多砍一棵
    for _ in range(400):
        if p.work is None:
            break
        g.tick()
    assert 5 <= p.inv["wood"] <= 9


def test_hunt_rabbit_and_it_flees(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    before = math.hypot(rabbit.x - p.x, rabbit.z - p.z)
    g.tick()
    assert math.hypot(rabbit.x - p.x, rabbit.z - p.z) > before
    rabbit.x, rabbit.z = p.x + 1, p.z
    for _ in range(2):
        interact_and_wait(g, p)
        passed(g, 1)
    assert rabbit not in g.animals and p.inv["raw_meat"] == 1


def test_spear_kills_rabbit_in_one_hit(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    p.inv = {"spear": 1}
    interact_and_wait(g, p)
    assert rabbit not in g.animals


def test_fishing_on_shallow_water(g, monkeypatch):
    spot = next((tx, tz) for tz in range(1, H - 1) for tx in range(1, W - 1)
                if g.terrain_at(tx, tz) == SAND and g.terrain_at(tx - 1, tz) == SHALLOW)
    clear(g, spot[0], spot[1], 3)
    p = g.join(1, "甲", "chef")
    place(p, spot[0] + 0.5, spot[1] + 0.5)
    monkeypatch.setattr(g.rng, "random", lambda: 0.0)
    interact_and_wait(g, p)
    assert p.inv["raw_fish"] == 1
    interact_and_wait(g, p)                      # 钓鱼之间有冷却，但进度条本身会等够时间
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
    tree = Resource(id=len(g.res), kind="tree", x=x + 2, z=z, hp=3)
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
    interact_and_wait(g, p)
    assert house.furniture == [] and p.inv["chair"] == 1


def test_interact_enters_house_when_close(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    interact_and_wait(g, p)
    assert p.house == house.id


def test_house_upgrade_makes_room_bigger(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    p.inv = {"wood": 20, "stone": 10, "rope": 4}
    g.act(p, "upgrade", {})
    assert house.level == 2 and C.ROOM_SIZE[2] == 12


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
        interact_and_wait(g, p)
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


# ------------------------------------------------------------ 防死循环：从空背包出发，能不能拿到一切

def _spot_for_resource(g, kind):
    """在一块清空的草地上放一个指定种类的资源点，玩家站在旁边。"""
    x, z = open_spot(g)
    p = g.join(20 + len(g.players), "探", "chef")
    place(p, x + 0.5, z + 0.5)
    r = Resource(id=len(g.res), kind=kind, x=x + 1, z=z, hp=C.RESOURCES[kind][1])
    g.res.append(r)
    if kind == "rock":
        g.rock_at[z * W + x + 1] = r.id
    if kind == "tree":
        g.tree_at[z * W + x + 1] = r.id
    return p


@pytest.mark.parametrize("kind, item", [
    ("tree", "wood"), ("bush", "berry"), ("herb", "herb"), ("reed", "fiber"),
    ("rock", "stone"), ("shell", "shell"), ("mushroom", "mushroom"),
])
def test_every_resource_can_be_gathered_with_empty_hands(g, kind, item):
    """空手也能采到每一种资源（不需要工具），否则会出现「要工具 → 要材料 → 要工具」的死循环。"""
    p = _spot_for_resource(g, kind)
    assert p.inv == {}
    interact_and_wait(g, p)
    assert p.inv.get(item, 0) >= 1, f"空手采{C.RESOURCES[kind][0]}拿不到{C.ITEMS[item]}"


def test_bare_hands_can_hunt_rabbit(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    interact_and_wait(g, p)
    passed(g, 1)
    interact_and_wait(g, p)
    assert p.inv.get("raw_meat", 0) == 1


def test_bare_hands_can_get_iron_ore_eventually(g):
    """没有铁镐也有机会挖到铁矿石，否则「铁镐要铁锭，铁锭要铁矿石，铁矿石要铁镐」就是死循环。"""
    p = g.join(30, "矿", "chef")
    got = 0
    for _ in range(300):
        rock = Resource(id=len(g.res), kind="rock", x=10, z=10, hp=3)
        g._gather(p, rock)
        got = p.inv.get("iron_ore", 0)
        if got:
            break
    assert got >= 1


def _reachable_from_empty():
    """从空背包出发，按照配方和建造规则，算出能拿到哪些东西、能建哪些建筑（不管位置）。"""
    have = {"wood", "coconut", "berry", "herb", "mushroom", "shell", "fiber", "stone", "iron_ore",
            "raw_fish", "raw_meat"}                    # 空手能采到的（见上面的测试）
    built = {}                                         # 建筑 → 能达到的最高等级
    station_kind = {"workbench": "workbench", "furnace": "furnace", "fire": "campfire"}
    changed = True
    while changed:
        changed = False

        def add(items):
            nonlocal changed
            for i in items:
                if i not in have:
                    have.add(i)
                    changed = True

        add(C.SEEDS)                                   # 草本植物偶尔掉种子
        for spec in C.CROPS.values():                  # 有种子和锄头，就能种出作物
            if spec["seed"] in have and "hoe" in have:
                add(spec["yield"].keys())
        for kind, b in C.BUILDS.items():               # 材料齐了，就能建
            if kind not in built and all(k in have for k, n in b["cost"].items()):
                built[kind] = 1
                changed = True
        for kind, levels in C.UPGRADES.items():        # 材料齐了，就能升级
            for lv, cost in sorted(levels.items()):
                if built.get(kind, 0) == lv - 1 and all(k in have for k in cost):
                    built[kind] = lv
                    changed = True
        for r in C.RECIPES.values():                   # 材料齐了、设施也有，就能做出来
            need = r.get("in_other", r["in"])
            if not all(k in have for k in need):
                continue
            if r["station"] and built.get(station_kind[r["station"]], 0) < r["level"]:
                continue
            add(r["out"].keys())
    return have, built


def test_every_item_and_building_is_reachable_from_nothing():
    have, built = _reachable_from_empty()
    missing = sorted(C.ITEMS[i] for i in C.ITEMS if i not in have)
    assert not missing, "这些东西永远拿不到：" + "、".join(missing)
    for kind, spec in C.BUILDS.items():
        assert built.get(kind, 0) == spec["max_level"], f"{spec['name']}升不到最高级 {spec['max_level']}"


def test_medicine_costs_more_for_non_doctors(spot):
    g, p, x, z = spot
    p.inv = {"herb": 3}
    with pytest.raises(GameError):
        craft(g, p, "medicine")                  # 厨师要 6 个
    p.inv = {"herb": 6}
    craft(g, p, "medicine")
    assert p.inv["medicine"] == 1 and p.inv.get("herb", 0) == 0
    doc = g.join(40, "医", "doctor")
    place(doc, x + 0.5, z + 0.5)
    doc.inv = {"herb": 3}
    craft(g, doc, "medicine")                    # 医生只要 3 个
    assert doc.inv["medicine"] == 1


def test_entering_house_beats_chopping_nearby_tree(spot):
    g, p, x, z = spot
    p.inv = {"wood": 20, "stone": 6, "rope": 2}
    build(g, p, "house", fx=0.0, fz=1.0)
    house = next(b for b in g.buildings.values() if b.kind == "house")
    tree = Resource(id=len(g.res), kind="tree", x=int(house.x) + 4, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + int(house.x) + 4] = tree.id
    place(p, house.x + 1.5, house.z + 3.6)       # 站在门口，旁边有树
    p.x = house.x + 3.2
    interact_and_wait(g, p)
    assert p.house == house.id and tree.present is True


def test_cooking_uses_a_lit_campfire_even_if_an_unlit_one_is_closer(spot):
    g, p, x, z = spot
    p.inv = {"wood": 3, "stone": 1}
    build(g, p, "campfire")                       # 近的那个，灭着
    p.inv = {"wood": 1, "stone": 1, "raw_fish": 1}
    place(p, x + 0.5, z + 0.5)
    from .game import Building
    lit = Building(id=g._new_id(), kind="campfire", x=x - 2, z=z, fuel_until=g.time + 60)
    g.buildings[lit.id] = lit
    g.build_at[z * W + x - 2] = lit.id
    craft(g, p, "cook_fish")                      # 能用那个烧着的火堆做饭
    assert p.inv["cooked_fish"] == 1


def test_cannot_build_on_top_of_a_resource(spot):
    g, p, x, z = spot
    p.inv = {"wood": 6, "stone": 2}
    bush = Resource(id=len(g.res), kind="bush", x=x + 2, z=z, hp=2)
    g.res.append(bush)
    with pytest.raises(GameError):
        build(g, p, "workbench")                  # 面前是浆果丛


# ------------------------------------------------------------ 进度条：要走完才成功，走开就取消

def test_work_takes_time_and_gives_nothing_until_done(spot):
    g, p, x, z = spot
    tree = Resource(id=len(g.res), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    g.act(p, "interact", {})
    assert p.work is not None and p.inv.get("wood", 0) == 0
    for _ in range(10):                          # 过了 1 秒，还没砍完
        g.tick()
    assert p.work is not None and p.inv.get("wood", 0) == 0
    assert 0.2 < g.view(p, False)["me"]["work"]["progress"] < 0.5


def test_moving_cancels_the_work(spot):
    g, p, x, z = spot
    tree = Resource(id=len(g.res), kind="tree", x=x + 1, z=z, hp=3)
    g.res.append(tree)
    g.tree_at[z * W + x + 1] = tree.id
    g.act(p, "interact", {})
    g.set_move(p, 0, 1)
    g.tick()
    assert p.work is None and p.inv.get("wood", 0) == 0
    assert any("走开" in m for m in p.events)


def test_axes_make_chopping_faster(spot):
    g, p, x, z = spot
    base = g._work_time(p, "tree")
    p.inv = {"stone_axe": 1}
    assert g._work_time(p, "tree") < base
    p.inv = {"iron_axe": 1}
    assert g._work_time(p, "tree") < g._work_time(p, "bush") * 3   # 铁斧砍树比普通更快
    assert g._work_time(p, "tree") < base * 0.6


def test_chopping_is_slower_than_gathering_berries(spot):
    g, p, x, z = spot
    assert g._work_time(p, "tree") > g._work_time(p, "bush")


def test_working_on_a_target_stops_it_fleeing(spot):
    g, p, x, z = spot
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    g.act(p, "interact", {})
    for _ in range(5):                            # 半秒：不被打的兔子会跑得远远的
        g.tick()
    assert math.hypot(rabbit.x - p.x, rabbit.z - p.z) < 1.8


# ------------------------------------------------------------ 批量采集：一次采附近同类的好几个

def _add_res(g, kind, x, z):
    r = Resource(id=len(g.res), kind=kind, x=x, z=z, hp=C.RESOURCES[kind][1])
    g.res.append(r)
    if kind == "tree":
        g.tree_at[z * W + x] = r.id
    if kind == "rock":
        g.rock_at[z * W + x] = r.id
    return r


def test_one_press_chops_three_trees_at_once(spot):
    g, p, x, z = spot
    trees = [_add_res(g, "tree", x + 1, z), _add_res(g, "tree", x + 1, z - 1), _add_res(g, "tree", x, z - 1)]
    g.act(p, "interact", {})
    assert p.work["n"] == 3
    assert p.work["dur"] == pytest.approx(C.WORK_TIME["tree"] * (1 + C.BATCH_TIME_STEP * 2))
    for _ in range(400):
        if p.work is None:
            break
        g.tick()
    assert all(t.present is False for t in trees)  # 三棵一起倒下
    assert 15 <= p.inv["wood"] <= 27               # 每棵 5–9 个木材


def test_batch_takes_longer_than_one_but_less_than_three_separately(spot):
    g, p, x, z = spot
    _add_res(g, "tree", x + 1, z)
    _add_res(g, "tree", x + 1, z - 1)
    _add_res(g, "tree", x, z - 1)
    g.act(p, "interact", {})
    batch = p.work["dur"]
    assert C.WORK_TIME["tree"] < batch < 3 * C.WORK_TIME["tree"]


def test_three_rocks_at_once_with_stone_pick(spot):
    g, p, x, z = spot
    p.inv = {"stone_pick": 1}
    for dx, dz in [(1, 0), (1, -1), (0, -1)]:
        _add_res(g, "rock", x + dx, z + dz)
    interact_and_wait(g, p)
    assert 12 <= p.inv["stone"] <= 18            # 三块一起挖，每块 4–6 个石头


def test_batch_only_takes_the_same_kind(spot):
    g, p, x, z = spot
    _add_res(g, "tree", x + 1, z)
    _add_res(g, "bush", x, z - 1)
    g.act(p, "interact", {})
    assert p.work["kind"] == "tree" and p.work["n"] == 1


def test_batch_skips_targets_that_are_gone(spot):
    g, p, x, z = spot
    a = _add_res(g, "tree", x + 1, z)
    b = _add_res(g, "tree", x + 1, z - 1)
    g.act(p, "interact", {})
    a.present = False                             # 中途有一棵没了（不让它在测试中长回来）
    a.regrow_at = 1e12
    g.tree_at.pop(z * W + x + 1, None)
    for _ in range(400):
        if p.work is None:
            break
        g.tick()
    assert b.present is False and 5 <= p.inv["wood"] <= 9   # 只结算还在的那一棵




# ------------------------------------------------------------ 第三阶段第一批：自动合成、篝火、昼夜、随机产量

def test_auto_craft_rope_for_house_when_fiber_is_enough(spot):
    g, p, x, z = spot
    p.inv = {"wood": 20, "stone": 6, "fiber": 6}      # 没有绳子，但纤维够 2 根绳子
    build(g, p, "house", fx=0.0, fz=1.0)
    assert any(b.kind == "house" for b in g.buildings.values())
    assert p.inv.get("rope", 0) == 0 and p.inv.get("fiber", 0) == 0
    assert any("自动合成" in m for m in p.events)


def test_auto_craft_changes_nothing_if_not_enough(spot):
    g, p, x, z = spot
    p.inv = {"wood": 20, "stone": 6, "fiber": 3}      # 纤维只够 1 根绳子，房子要 2 根
    with pytest.raises(GameError) as e:
        build(g, p, "house", fx=0.0, fz=1.0)
    assert "绳子" in str(e.value)
    assert p.inv == {"wood": 20, "stone": 6, "fiber": 3}   # 什么都没有被消耗


def test_campfire_burn_time_by_level(spot):
    g, p, x, z = spot
    for level in (1, 2, 3):
        b = g._place_building("campfire", x - 2, z + level * 0, level=level)   # 只是为了测试时间
        g.build_at.pop(z * W + x - 2, None)
        p.inv = {"wood": 1}
        p.x, p.z = x + 0.5, z + 0.5
        b.fuel_until = 0.0
        g.act(p, "fuel", {})
        assert b.fuel_until - g.time == pytest.approx(C.FUEL_SECONDS[level])
        g.buildings.pop(b.id)


def test_campfire_light_radius_grows_with_level():
    assert C.LIGHT_RADIUS[1] < C.LIGHT_RADIUS[2] < C.LIGHT_RADIUS[3]
    assert C.FUEL_SECONDS[1] == 180 and C.FUEL_SECONDS[2] == 360 and C.FUEL_SECONDS[3] == 600


def test_day_is_18_minutes_and_night_is_6_minutes():
    g = Game(2026)
    g.time = 0.0
    assert g.clock()["night"] is False and g.clock()["left"] == pytest.approx(18 * 60)
    g.time = 17 * 60 + 59
    assert g.clock()["night"] is False
    g.time = 18 * 60 + 1
    assert g.clock()["night"] is True
    assert g.clock()["left"] == pytest.approx(6 * 60 - 1, abs=0.5)
    g.time = 24 * 60 + 5
    assert g.clock() == {"day": 2, "night": False, "left": pytest.approx(18 * 60 - 5, abs=0.5)}


def test_view_sends_the_clock(g):
    p = g.join(1, "甲", "chef")
    assert "clock" in g.view(p, False) and "night" in g.view(p, False)["clock"]


def test_yields_are_random_around_the_middle_value(g):
    vals = [g._roll(7, 2) for _ in range(800)]
    assert min(vals) == 5 and max(vals) == 9
    assert 6.7 < sum(vals) / len(vals) < 7.3


# ------------------------------------------------------------ 第三阶段第二批：武器、防具、狼群

def test_weapons_and_armor_recipes_and_equip(spot):
    g, p, x, z = spot
    p.inv = {"stick": 2, "wood": 9, "stone": 2}
    build(g, p, "workbench")                           # 花掉 6 个木材
    craft(g, p, "wood_sword")                          # 剩下的 3 个木材 + 2 根木棍
    assert p.inv["wood_sword"] == 1
    g.act(p, "equip", {"item": "wood_sword"})
    assert p.equip == {"weapon": "wood_sword"}
    g.act(p, "equip", {"item": "wood_sword"})          # 再点一次就脱下
    assert p.equip == {}
    assert p.inv["wood_sword"] == 1                    # 装备不消耗


def test_cannot_equip_what_you_do_not_have(spot):
    g, p, x, z = spot
    with pytest.raises(GameError):
        g.act(p, "equip", {"item": "iron_sword"})
    with pytest.raises(GameError):
        g.act(p, "equip", {"item": "wood"})


def test_sword_kills_rabbit_in_one_hit(spot):
    g, p, x, z = spot
    p.inv = {"wood_sword": 1}
    g.act(p, "equip", {"item": "wood_sword"})
    rabbit = Animal(id=g._new_id(), kind="rabbit", x=x + 1.5, z=z + 0.5, hp=2)
    g.animals.append(rabbit)
    interact_and_wait(g, p)
    assert rabbit not in g.animals


def test_wolves_only_come_out_at_night(g):
    g.time = 0.0                                       # 白天
    g.tick()
    assert not any(a.kind == "wolf" for a in g.animals)
    g.time = 18 * 60 + 5                               # 夜里
    g.tick()
    assert sum(1 for a in g.animals if a.kind == "wolf") == C.WOLF_NIGHT_COUNT
    g.time = 24 * 60 + 1                               # 天亮
    g.tick()
    assert not any(a.kind == "wolf" for a in g.animals)


def test_wolf_bites_and_armor_reduces_the_damage(spot):
    g, p, x, z = spot
    g.time = 18 * 60 + 5
    wolf = Animal(id=g._new_id(), kind="wolf", x=x + 1.2, z=z + 0.5, hp=12)
    g.animals.append(wolf)
    p.health = 100.0
    g.tick()
    assert p.health == pytest.approx(100 - C.WOLF_DAMAGE, abs=0.5)
    p.health = 100.0
    p.inv = {"iron_armor": 1}
    g.equip(p, "iron_armor")
    wolf.turn_at = 0.0
    g.tick()
    assert p.health == pytest.approx(100 - max(1, C.WOLF_DAMAGE - 5), abs=0.5)


def test_campfire_light_keeps_wolves_out(spot):
    g, p, x, z = spot
    g.time = 18 * 60 + 5
    fire = g._place_building("campfire", x - 3, z, level=2)
    fire.fuel_until = g.time + 600
    place(p, x - 2.5, z + 0.5)                          # 站在篝火旁边
    wolf = Animal(id=g._new_id(), kind="wolf", x=x + 6.5, z=z + 0.5, hp=12)
    g.animals.append(wolf)
    p.health = 100.0
    for _ in range(600):
        g.tick()
        assert not g._in_light(wolf.x, wolf.z)          # 狼从来没有进到光里
    assert p.health == 100.0


def test_house_is_safe_from_wolves(spot):
    g, p, x, z = spot
    g.time = 18 * 60 + 5
    p.inv = {"wood": 20, "stone": 6, "rope": 2}
    build(g, p, "house", fx=0.0, fz=1.0)
    house = next(b for b in g.buildings.values() if b.kind == "house")
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    wolf = Animal(id=g._new_id(), kind="wolf", x=house.x + 1.5, z=house.z + 6.0, hp=12)
    g.animals.append(wolf)
    p.health = 100.0
    for _ in range(50):
        g.tick()
    assert p.health == 100.0


def test_wolf_night_state_is_saved(g):
    g.time = 18 * 60 + 5
    g.tick()
    d = json.loads(json.dumps(g.to_dict()))
    g2 = Game.from_dict(d)
    assert g2.wolf_night is True


# ------------------------------------------------------------ 第三阶段第三批：房间更大、更多家具

def test_rooms_get_bigger_with_each_upgrade():
    assert [C.ROOM_SIZE[1], C.ROOM_SIZE[2], C.ROOM_SIZE[3]] == [10, 12, 14]


def test_fireplace_and_bookshelf_are_furniture_and_recipes_exist():
    assert "fireplace" in C.FURNITURE and "bookshelf" in C.FURNITURE
    assert C.RECIPES["fireplace"]["station"] == "workbench" and C.RECIPES["fireplace"]["level"] == 2
    assert C.RECIPES["bookshelf"]["in"] == {"wood": 5}


def test_fireplace_warms_and_bookshelf_calms_inside_the_house(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    house.furniture.append({"id": g._new_id(), "kind": "fireplace", "x": p.x, "z": p.z})
    p.sanity = 50.0
    p.health = 80.0
    for _ in range(50):
        g.tick()
    assert p.sanity > 50 - 0.02 * 5 + 0.2 * 5 * 0.9
    assert p.health > 80


def test_place_furniture_in_the_bigger_room_corners(spot):
    g, p, x, z = spot
    house = build_house(g, p)
    place(p, house.x + 1.5, house.z + 3.6)
    g.act(p, "enter", {})
    size = C.ROOM_SIZE[house.level]
    p.x, p.z = size - 0.7, size - 1.3
    p.inv = {"fireplace": 1, "bookshelf": 1}
    g.act(p, "place", {"item": "fireplace", "fx": 0, "fz": -1})
    assert len(house.furniture) == 1
    g.act(p, "place", {"item": "bookshelf", "fx": -1, "fz": 0})
    assert {f["kind"] for f in house.furniture} == {"fireplace", "bookshelf"}


# ------------------------------------------------------------ 装备：手里的工具

def test_tool_can_be_equipped_in_the_tool_slot_and_shown_to_others(g):
    p = g.join(70, "甲", "chef")
    q = g.join(71, "乙", "doctor")
    p.inv = {"stone_axe": 1}
    g.act(p, "equip", {"item": "stone_axe"})
    assert p.equip == {"tool": "stone_axe"}
    g.act(p, "equip", {"item": "stone_axe"})            # 再点一次就拿下来
    assert p.equip == {}
    g.act(p, "equip", {"item": "stone_axe"})
    row = next(r for r in g.view(q, False)["players"] if r[0] == p.id)
    assert row[8] == "stone_axe"                        # 别人能看到你手里拿的东西


def test_weapon_is_shown_when_no_tool_is_held(g):
    p = g.join(72, "甲", "chef")
    p.inv = {"wood_sword": 1, "stone_axe": 1}
    g.act(p, "equip", {"item": "stone_axe"})
    g.act(p, "equip", {"item": "wood_sword"})
    row = next(r for r in g.view(p, False)["players"] if r[0] == p.id)
    assert row[8] == "wood_sword"                       # 有武器就显示武器
