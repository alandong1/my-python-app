"""大陆争霸的规则测试：不经过网络，直接调用 World。"""
import pytest

from projects.continent import config as C
from projects.continent.game import GameError, World


def rich(p, gold=50000):
    p.gold = gold


def free_land(world, near_x, near_y, radius=6, min_dist=0):
    """找一块离 (near_x, near_y) 不远的空平地（不在矿点上，周围 3×3 都是平地，不靠海）。"""
    for r in range(1, radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                x, y = near_x + dx, near_y + dy
                if max(abs(dx), abs(dy)) < min_dist:
                    continue
                i = world.idx(x, y) if world.in_bounds(x, y) else None
                if i is not None and world.terrain[i] == C.PLAIN and i not in world.occ \
                   and i not in world.ore and all(
                       world.terrain[world.idx(x + ex, y + ey)] == C.PLAIN
                       for ex in (-1, 0, 1) for ey in (-1, 0, 1)
                       if world.in_bounds(x + ex, y + ey)):
                    return x, y
    raise AssertionError("附近找不到空地")


def base_of(world, p):
    return world.buildings[p.hq]


def test_join_creates_base_and_starting_units():
    w = World(1)
    p = w.join(1, "甲")
    hq = base_of(w, p)
    assert hq.kind == "hq" and p.gold == C.START_GOLD
    infantry = [u for u in w.units.values() if u.owner == 1]
    assert len(infantry) == 2 and all(u.kind == "infantry" for u in infantry)
    assert w.join(1, "甲改名") is p and p.name == "甲改名"


def test_bases_are_apart_and_on_buildable_land():
    w = World(2)
    a, b = w.join(1, "甲"), w.join(2, "乙")
    ha, hb = base_of(w, a), base_of(w, b)
    assert max(abs(ha.x - hb.x), abs(ha.y - hb.y)) >= 9
    for h in (ha, hb):
        assert w.terrain[w.idx(h.x, h.y)] in C.BUILDABLE


def test_income_from_base_and_mines():
    w = World(3)
    p = w.join(1, "甲")
    rich(p, 0)
    w.step()
    assert p.gold == C.HQ_INCOME
    # 建一座矿场：必须建在矿点上
    ore = next(i for i in w.ore if w.terrain[i] == C.PLAIN and i not in w.occ)
    ox, oy = ore % w.w, ore // w.w
    # 把基地挪到矿点附近，方便在射程内建造
    hq = base_of(w, p)
    hq.x, hq.y = ox, oy - 2
    w.occ.clear()
    w.occ[w.idx(hq.x, hq.y)] = hq.id
    rich(p, C.BUILDINGS["mine"]["cost"])
    w.command(1, "build", {"kind": "mine", "x": ox, "y": oy})
    before = p.gold
    w.step()
    assert p.gold == before + C.HQ_INCOME + C.MINE_INCOME


def test_build_rules():
    w = World(4)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    x, y = free_land(w, hq.x, hq.y)
    # 工厂要先有兵营
    with pytest.raises(GameError, match="兵营"):
        w.command(1, "build", {"kind": "factory", "x": x, "y": y})
    # 矿场必须建在矿点上
    with pytest.raises(GameError, match="矿点"):
        w.command(1, "build", {"kind": "mine", "x": x, "y": y})
    # 离基地太远（超过 BUILD_RANGE）不能建
    fx, fy = free_land(w, hq.x, hq.y, radius=20, min_dist=C.BUILD_RANGE + 1)
    with pytest.raises(GameError, match="附近"):
        w.command(1, "build", {"kind": "barracks", "x": fx, "y": fy})
    w.command(1, "build", {"kind": "barracks", "x": x, "y": y})
    assert any(b.kind == "barracks" and b.owner == 1 for b in w.buildings.values())
    # 同一格不能建两次
    with pytest.raises(GameError, match="不能建造"):
        w.command(1, "build", {"kind": "pillbox", "x": x, "y": y})


def test_port_needs_shore():
    w = World(5)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    x, y = free_land(w, hq.x, hq.y)     # 周围都是平地，不靠海
    w.command(1, "build", {"kind": "barracks", "x": x, "y": y})
    # 不靠海的地方建港口，应该失败
    with pytest.raises(GameError, match="海边"):
        w.command(1, "build", {"kind": "port", "x": x, "y": y + 1 if y + 1 < w.h else y - 1})


def test_train_queue_cancel_and_spawn():
    w = World(6)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    x, y = free_land(w, hq.x, hq.y)
    w.command(1, "build", {"kind": "barracks", "x": x, "y": y})
    bar = next(b for b in w.buildings.values() if b.kind == "barracks")
    gold = p.gold
    w.command(1, "train", {"building": bar.id, "kind": "mg"})
    assert p.gold == gold - C.UNITS["mg"]["cost"]
    with pytest.raises(GameError, match="造不出"):
        w.command(1, "train", {"building": bar.id, "kind": "tank"})
    # 取消退款
    w.command(1, "cancel", {"building": bar.id, "index": 0})
    assert p.gold == gold
    # 排队生产，直到造出来
    w.command(1, "train", {"building": bar.id, "kind": "infantry"})
    n = len([u for u in w.units.values() if u.owner == 1])
    for _ in range(C.UNITS["infantry"]["time"]):
        w.step()
    assert len([u for u in w.units.values() if u.owner == 1]) == n + 1
    # 队列满了不能再排
    for _ in range(C.QUEUE_MAX):
        w.command(1, "train", {"building": bar.id, "kind": "infantry"})
    with pytest.raises(GameError, match="队列满"):
        w.command(1, "train", {"building": bar.id, "kind": "infantry"})


def test_tech_chain_gating():
    w = World(7)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    x, y = free_land(w, hq.x, hq.y)
    w.command(1, "build", {"kind": "barracks", "x": x, "y": y})
    # 没有工厂不能建机场
    with pytest.raises(GameError, match="工厂"):
        w.command(1, "build", {"kind": "airfield", "x": x, "y": y + 1 if y + 1 < w.h else y - 1})


def test_research_upgrades_levels_and_existing_hp():
    w = World(8)
    p = w.join(1, "甲")
    rich(p)
    inf = next(u for u in w.units.values() if u.owner == 1)
    old_max = inf.maxhp
    gold = p.gold
    w.command(1, "research", {"cls": "infantry"})
    assert p.research["infantry"] == 1
    assert p.gold == gold - C.RESEARCH_COSTS[0]
    assert inf.maxhp > old_max
    for _ in range(C.RESEARCH_MAX - 1):
        w.command(1, "research", {"cls": "infantry"})
    with pytest.raises(GameError, match="满级"):
        w.command(1, "research", {"cls": "infantry"})


def test_research_needs_base():
    w = World(9)
    p = w.join(1, "甲")
    rich(p)
    w.command(1, "research", {"cls": "vehicle"})   # 有基地可以研究
    p.hq = None
    with pytest.raises(GameError, match="基地"):
        w.command(1, "research", {"cls": "vehicle"})


def test_move_walks_over_time_and_blocks_water():
    w = World(10)
    p = w.join(1, "甲")
    inf = next(u for u in w.units.values() if u.owner == 1)
    hq = base_of(w, p)
    tx, ty = free_land(w, hq.x, hq.y, radius=5)
    w.command(1, "move", {"units": [inf.id], "x": tx, "y": ty})
    for _ in range(200):
        w.step()
        if (inf.x, inf.y) == (tx, ty):
            break
    assert (inf.x, inf.y) == (tx, ty)
    # 海里的格子，步兵到不了
    sea = next(i for i in range(w.w * w.h) if w.terrain[i] == C.SEA)
    with pytest.raises(GameError, match="到不了"):
        w.command(1, "move", {"units": [inf.id], "x": sea % w.w, "y": sea // w.w})


def test_carrier_only_moves_on_sea():
    w = World(11)
    p = w.join(1, "甲")
    sea = next(i for i in range(w.w * w.h) if w.terrain[i] == C.SEA)
    car = w._add_unit(1, "carrier", sea % w.w, sea // w.w)
    land = next(i for i in range(w.w * w.h) if w.terrain[i] == C.PLAIN and i not in w.occ)
    with pytest.raises(GameError, match="到不了"):
        w.command(1, "move", {"units": [car.id], "x": land % w.w, "y": land // w.w})


def test_fog_hides_enemy_units_until_seen():
    w = World(12)
    a, b = w.join(1, "甲"), w.join(2, "乙")
    hb = base_of(w, b)
    # 找一个离甲很远的敌方单位位置
    enemy = w._add_unit(2, "infantry", hb.x, hb.y)
    v = w.view(1)
    assert not any(u["id"] == enemy.id for u in v["units"])
    assert not any(bb["id"] == hb.id for bb in v["buildings"])
    # 派一架侦察机飞过去，就能看见了
    ha = base_of(w, a)
    scout = w._add_unit(1, "scout", ha.x, ha.y)
    scout.x, scout.y = hb.x, hb.y         # 直接放到敌人的基地上空
    w._refresh_vision()
    v = w.view(1)
    assert any(u["id"] == enemy.id for u in v["units"])
    assert any(bb["id"] == hb.id for bb in v["buildings"])
    assert v["terrain"][w.idx(hb.x, hb.y)] != "?"


def test_attack_requires_vision_and_kills():
    w = World(13)
    a, b = w.join(1, "甲"), w.join(2, "乙")
    hb = base_of(w, b)
    # 找一个空地放一个敌方单位，在甲的视野里（直接派一个步兵过去）
    inf = next(u for u in w.units.values() if u.owner == 1)
    target = w._add_unit(2, "infantry", inf.x, inf.y)
    target.hp = target.maxhp = 5          # 弱一点，保证是我们打死它，不会双方对射
    w._refresh_vision()
    w.command(1, "attack", {"units": [inf.id], "target": target.id})
    for _ in range(60):
        w.step()
        if target.id not in w.units:
            break
    assert target.id not in w.units
    # 看不见的目标不能攻击
    far = w._add_unit(2, "infantry", hb.x, hb.y)
    with pytest.raises(GameError, match="看不见"):
        w.command(1, "attack", {"units": [inf.id], "target": far.id})


def test_fighter_cannot_attack_ground():
    w = World(14)
    p = w.join(1, "甲")
    ground = w._add_unit(2, "infantry", base_of(w, p).x, base_of(w, p).y)
    fighter = w._add_unit(1, "fighter", base_of(w, p).x, base_of(w, p).y)
    w._refresh_vision()
    with pytest.raises(GameError, match="打不到"):
        w.command(1, "attack", {"units": [fighter.id], "target": ground.id})


def test_relocate_moves_base_after_delay_and_costs():
    w = World(15)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    tx, ty = free_land(w, hq.x, hq.y, radius=8)
    old_gold = p.gold
    w.command(1, "relocate", {"x": tx, "y": ty})
    assert p.gold < old_gold and p.relocating is not None
    with pytest.raises(GameError, match="搬迁中"):
        w.command(1, "relocate", {"x": tx, "y": ty})
    for _ in range(C.RELOCATE_TIME):
        w.step()
    assert p.relocating is None
    new_hq = base_of(w, p)
    assert (new_hq.x, new_hq.y) == (tx, ty)
    # 冷却中不能再搬
    with pytest.raises(GameError, match="冷却"):
        w.command(1, "relocate", {"x": hq.x, "y": hq.y})


def test_relocate_refund_when_target_taken():
    w = World(16)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    tx, ty = free_land(w, hq.x, hq.y, radius=8)
    gold = p.gold
    w.command(1, "relocate", {"x": tx, "y": ty})
    w._add_building(2, "pillbox", tx, ty)   # 别人抢先占了这块地
    for _ in range(C.RELOCATE_TIME):
        w.step()
    assert base_of(w, p) is hq               # 基地没动
    # 退款：最后金币 = 原来的钱 + 这段时间的基地收入（搬迁费用全额退回）
    assert p.gold == pytest.approx(gold + C.HQ_INCOME * C.RELOCATE_TIME)


def test_hq_destroyed_cancels_relocation_and_respawn():
    w = World(17)
    p = w.join(1, "甲")
    rich(p)
    hq = base_of(w, p)
    tx, ty = free_land(w, hq.x, hq.y, radius=8)
    w.command(1, "relocate", {"x": tx, "y": ty})
    cost = p.relocating["cost"]
    gold = p.gold
    hq.hp = 0
    w.step()
    assert p.hq is None
    assert p.relocating is None
    assert p.gold >= gold + cost             # 基地毁了，搬迁费用退回
    with pytest.raises(GameError, match="基地被毁"):
        w.command(1, "relocate", {"x": tx, "y": ty})
    # 出局后可以重建基地
    w.command(1, "respawn", {})
    assert p.hq is not None
    with pytest.raises(GameError, match="不需要"):
        w.command(1, "respawn", {})


def test_unknown_or_bad_commands():
    w = World(18)
    with pytest.raises(GameError, match="请先进入"):
        w.command(99, "move", {})
    p = w.join(1, "甲")
    with pytest.raises(GameError, match="未知"):
        w.command(1, "hack", {})
    with pytest.raises(GameError, match="选中"):
        w.command(1, "move", {"units": [424242], "x": 1, "y": 1})
    with pytest.raises(GameError):
        w.command(1, "move", {"units": [], "x": 1, "y": 1})
    assert p.hq is not None


def test_view_never_leaks_invisible_data():
    w = World(19)
    a, b = w.join(1, "甲"), w.join(2, "乙")
    v = w.view(1)
    # 对方的 gold、队列都不在发给甲的数据里
    assert "gold" not in str([p for p in v["players"]])
    assert all("queue" not in bb or bb["mine"] for bb in v["buildings"])
    assert len(v["terrain"]) == w.w * w.h and len(v["visible"]) == w.w * w.h


def test_advance_to_caps_and_steps():
    w = World(20)
    w.join(1, "甲")
    w.advance_to(0.0)
    w.advance_to(3.0)
    assert w.tick_count == 3
    w.advance_to(1e9)
    assert w.tick_count == 3 + C.MAX_TICKS_PER_CALL
