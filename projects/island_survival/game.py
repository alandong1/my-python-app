"""荒岛求生的游戏规则：地图、玩家、资源、动物、合成、建造、种田、房屋、生存数值。

这个文件只管「规则」，不碰网络。服务器（server.py）每 0.1 秒调用一次 tick()，
再把结果发给每个玩家。内容（有哪些东西、配方是什么）在 content.py。
规则的说明见 REQUIREMENTS.md，测试在 test_game.py。

服务器是「权威」的：所有判断都在这里做，浏览器只负责显示和发送按键。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import content as C

W = 200                  # 地图宽（格）
H = 200                  # 地图高（格）
DT = 0.1                 # 每次 tick 经过的秒数（和服务器的节奏一致）
VIEW_RADIUS = 32         # 玩家能看到多远（格），远处的东西不发给他
PLAYER_SPEED = 4.0       # 走路速度：格/秒

# 地形编号。服务器把整张地图编码成一串数字字符发给浏览器。
DEEP, SHALLOW, SAND, GRASS, FOREST = range(5)
LAND = (SAND, GRASS, FOREST)
WALK = (SHALLOW, SAND, GRASS, FOREST)   # 玩家能走的地形（深海不能走）

ROLES = {"chef": "厨师", "doctor": "医生", "priest": "牧师"}

ACTION_COOLDOWN = 0.4    # 互动之间至少间隔多少秒（防止连点刷资源）
FISH_COOLDOWN = 2.0
FISH_CHANCE = 0.4
LOW = 30                 # 数值低于这个值会开始扣血
SAFE = 60                # 三项都不低于这个值，健康才会慢慢恢复
SICK_DRAIN = 0.3         # 生病时每秒额外扣的血
CHEF_COOK_BONUS = 15     # 厨师做饭时，自己额外获得的饱食度
DOCTOR_HEAL = 30         # 医生治疗队友恢复的健康
MEDICINE_HEAL = 25       # 自己用草药恢复的健康
PRIEST_RANGE = 8.0       # 牧师的祈福范围（格）
PRIEST_GAIN = 0.8        # 每秒给队友恢复的精神
FLEE_RANGE = 5.0         # 玩家距离兔子多近时，兔子开始逃
FLEE_SPEED = 2.4
REACH = 3.5              # 站在设施旁边多远算「在旁边」（格）
PLANT_REACH = 1.6        # 碰到农田、家具的距离（格）

Hook = Optional[int]


class GameError(Exception):
    """玩家的操作不成立（材料不够、位置不对……）。错误信息直接显示给玩家。"""


@dataclass
class Player:
    id: int
    account_id: int
    name: str
    role: str
    x: float = 0.0           # 在屋里时，这是房间里的坐标
    z: float = 0.0
    hunger: float = 100.0    # 饱食
    health: float = 100.0    # 健康（血量）
    sanity: float = 100.0    # 精神
    sick: bool = False
    dead: bool = False
    inv: Dict[str, int] = field(default_factory=dict)
    move_x: float = 0.0      # 客户端上报的移动方向（长度不超过 1）
    move_z: float = 0.0
    next_action: float = 0.0
    next_fish: float = 0.0
    events: List[str] = field(default_factory=list)
    house: Hook = None       # 在哪间屋子里（房子的编号），None 表示在室外
    ox: float = 0.0          # 进屋前在室外的位置，出屋时回到这里
    oz: float = 0.0


@dataclass
class Resource:
    id: int
    kind: str
    x: int
    z: int
    hp: int
    present: bool = True
    regrow_at: float = 0.0


@dataclass
class Animal:
    id: int
    kind: str
    x: float
    z: float
    hp: int
    heading: float = 0.0
    turn_at: float = 0.0


@dataclass
class Building:
    """建筑和农田。kind 是 content.BUILDS 里的一种，或者 'plot'（农田）。"""
    id: int
    kind: str
    x: int                   # 左上角的格子（占多格的建筑从这里往右、往下）
    z: int
    level: int = 1
    owner: int = 0           # 建的人的账户编号（只用来显示，目前谁都能用）
    fuel_until: float = 0.0  # 火堆：烧到什么时候
    crop: Optional[str] = None
    planted_at: float = 0.0
    furniture: List[dict] = field(default_factory=list)   # 房子里的家具


def size_of(kind: str) -> int:
    return C.BUILDS[kind]["size"] if kind in C.BUILDS else 1


def _player_to_dict(p: Player) -> dict:
    return {
        "account_id": p.account_id, "name": p.name, "role": p.role,
        "x": p.x, "z": p.z, "hunger": p.hunger, "health": p.health, "sanity": p.sanity,
        "sick": p.sick, "dead": p.dead, "inv": dict(p.inv), "house": p.house,
        "ox": p.ox, "oz": p.oz,
    }


def _player_from_dict(d: dict, pid: int) -> Player:
    return Player(
        id=pid, account_id=int(d["account_id"]), name=str(d["name"]), role=str(d["role"]),
        x=float(d["x"]), z=float(d["z"]), hunger=float(d["hunger"]), health=float(d["health"]),
        sanity=float(d["sanity"]), sick=bool(d["sick"]), dead=bool(d["dead"]),
        inv={str(k): int(v) for k, v in d["inv"].items()},
        house=d.get("house"), ox=float(d.get("ox", 0)), oz=float(d.get("oz", 0)),
    )


class Game:
    SAVE_VERSION = 2

    def __init__(self, seed: int = 2026):
        self.seed = seed
        self.rng = random.Random(seed)   # 地图和游戏过程里的随机都用它，同一个种子结果相同
        self.time = 0.0
        self.tick_no = 0
        self.terrain = bytearray(W * H)
        self.res: List[Resource] = []
        self.tree_at: Dict[int, int] = {}        # 格子编号 → 还立着的树的编号（树会挡路）
        self.rock_at: Dict[int, int] = {}        # 格子编号 → 还在的石头的编号（石头也挡路）
        self.buildings: Dict[int, Building] = {}
        self.build_at: Dict[int, int] = {}       # 格子编号 → 占着这个格子的建筑编号
        self.animals: List[Animal] = []
        self.players: Dict[int, Player] = {}
        self.saved: Dict[int, dict] = {}         # 下线玩家的角色：账户编号 → 数据
        self._next_id = 1
        self._generate_map()
        self._populate()

    # ------------------------------------------------------------ 基础

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _idx(self, x: float, z: float) -> int:
        return int(z) * W + int(x)

    def terrain_at(self, x: float, z: float) -> int:
        tx, tz = int(x), int(z)
        if not (0 <= tx < W and 0 <= tz < H):
            return DEEP
        return self.terrain[tz * W + tx]

    # ------------------------------------------------------------ 地图

    def _generate_map(self) -> None:
        """做一座不规则的岛：海岸线用几组正弦曲线决定，森林用另一组曲线决定。"""
        rng = self.rng
        ph = [rng.uniform(0, 2 * math.pi) for _ in range(6)]
        cx, cz, radius = W / 2, H / 2, 88.0
        for z in range(H):
            for x in range(W):
                dx, dz = x + 0.5 - cx, z + 0.5 - cz
                dist = math.hypot(dx, dz) / radius
                ang = math.atan2(dz, dx)
                coast = (0.78 + 0.10 * math.sin(3 * ang + ph[0])
                         + 0.06 * math.sin(7 * ang + ph[1]) + 0.03 * math.sin(13 * ang + ph[2]))
                if dist > coast:
                    t = DEEP
                elif dist > coast - 0.08:
                    t = SAND
                else:
                    forest = (math.sin(x * 0.07 + ph[3]) * math.sin(z * 0.09 + ph[4])
                              + 0.4 * math.sin((x + z) * 0.05 + ph[5]))
                    t = FOREST if forest > 0.25 else GRASS
                self.terrain[z * W + x] = t
        # 陆地外面 2 格以内的深海变成浅海（可以涉水、钓鱼）
        edge = [z * W + x for z in range(H) for x in range(W)
                if self.terrain[z * W + x] == DEEP and self._near_land(x, z)]
        for i in edge:
            self.terrain[i] = SHALLOW

    def _near_land(self, x: int, z: int, r: int = 2) -> bool:
        return any(self.terrain_at(x + dx, z + dz) in LAND
                   for dz in range(-r, r + 1) for dx in range(-r, r + 1))

    def _near_water(self, x: float, z: float, r: int = 1) -> bool:
        tx, tz = int(x), int(z)
        return any(self.terrain_at(tx + dx, tz + dz) == SHALLOW
                   for dz in range(-r, r + 1) for dx in range(-r, r + 1))

    def _free_tile(self, i: int) -> bool:
        """这个格子没有树、石头、建筑挡着。"""
        return i not in self.tree_at and i not in self.rock_at and i not in self.build_at

    def _resource_on(self, tx: int, tz: int) -> bool:
        """这个格子上有没有还在的资源点（浆果丛、草本植物……）。"""
        return any(r.present and r.x == tx and r.z == tz for r in self.res)

    def _random_tile(self, kinds: Tuple[int, ...], tries: int = 2000) -> Optional[Tuple[int, int]]:
        """随机找一个指定地形、没有东西挡着的格子。"""
        for _ in range(tries):
            x, z = self.rng.randrange(W), self.rng.randrange(H)
            if self.terrain[z * W + x] in kinds and self._free_tile(z * W + x):
                return x, z
        return None

    def _populate(self) -> None:
        """放上资源点和动物。"""
        for z in range(H):
            for x in range(W):
                t = self.terrain[z * W + x]
                roll = self.rng.random()
                if t == FOREST:
                    if roll < 0.4:
                        self._add_resource("tree", x, z)
                    elif roll < 0.42:
                        self._add_resource("mushroom", x, z)
                elif t == GRASS:
                    if roll < 0.03:
                        self._add_resource("tree", x, z)
                    elif roll < 0.05:
                        self._add_resource("herb", x, z)
                    elif roll < 0.065:
                        self._add_resource("bush", x, z)
                    elif roll < 0.07:
                        self._add_resource("rock", x, z)
                elif t == SAND:
                    if roll < 0.012:
                        self._add_resource("rock", x, z)
                    elif roll < 0.03:
                        self._add_resource("shell", x, z)
                    elif roll < 0.12 and self._near_water(x, z):
                        self._add_resource("reed", x, z)
        for kind, spec in C.ANIMALS.items():
            for _ in range(spec[5]):
                self._spawn_animal(kind)

    def _add_resource(self, kind: str, x: int, z: int) -> None:
        r = Resource(id=len(self.res), kind=kind, x=x, z=z, hp=C.RESOURCES[kind][1])
        self.res.append(r)
        if kind == "tree":
            self.tree_at[z * W + x] = r.id
        elif kind == "rock":
            self.rock_at[z * W + x] = r.id

    def _spawn_animal(self, kind: str) -> None:
        _, hp, kinds, _, _, _ = C.ANIMALS[kind]
        tile = self._random_tile(kinds)
        if tile:
            x, z = tile
            self.animals.append(Animal(
                id=self._new_id(), kind=kind, x=x + 0.5, z=z + 0.5, hp=hp,
                heading=self.rng.uniform(0, 2 * math.pi), turn_at=self.time))

    # ------------------------------------------------------------ 玩家进出

    def join(self, account_id: int, name: str, role: str) -> Player:
        """上线。如果这个账户之前下线时留下了同一个角色，就接着原来的位置和数值玩；否则随机落在岛上。"""
        if role not in ROLES:
            raise GameError("请先选择一个角色")
        old = self.saved.get(account_id)
        if old and old.get("role") == role:
            self.saved.pop(account_id)
            p = _player_from_dict(old, self._new_id())
            p.name = name[:12] or "幸存者"
            if p.house is not None and p.house not in self.buildings:
                p.house, p.x, p.z = None, p.ox, p.oz          # 房子不见了，回到室外
            if p.dead:
                p.events.append("你还是倒在岛上，点「重新开始」站起来")
        else:
            p = Player(id=self._new_id(), account_id=account_id, name=name[:12] or "幸存者", role=role)
            p.x, p.z = self._spawn_point()
        self.players[p.id] = p
        return p

    def leave(self, pid: int) -> None:
        """下线：角色留在存档里，世界继续运行（它不会行动，数值也不变）。"""
        p = self.players.pop(pid, None)
        if p is not None:
            self.saved[p.account_id] = _player_to_dict(p)

    def respawn(self, p: Player) -> None:
        if not p.dead:
            return
        p.hunger, p.health, p.sanity = 100.0, 100.0, 100.0
        p.sick, p.dead, p.inv = False, False, {}
        p.move_x = p.move_z = 0.0
        p.house = None
        p.x, p.z = self._spawn_point(exclude=p)
        p.events.append("你在岛上的另一个地方醒来了")

    def _spawn_point(self, exclude: Optional[Player] = None) -> Tuple[float, float]:
        """随机选几个陆地位置，挑离其他室外、活着的玩家最远的那个。"""
        others = [(q.x, q.z) for q in self.players.values()
                  if not q.dead and q.house is None and q is not exclude]
        best, best_d = None, -1.0
        for _ in range(30):
            tile = self._random_tile(LAND)
            if not tile:
                break
            x, z = tile[0] + 0.5, tile[1] + 0.5
            d = min((math.hypot(x - ox, z - oz) for ox, oz in others), default=1e9)
            if d > best_d:
                best, best_d = (x, z), d
        return best or (W / 2, H / 2)

    # ------------------------------------------------------------ 玩家操作

    def set_move(self, p: Player, dx: float, dz: float) -> None:
        length = math.hypot(dx, dz)
        if length > 1:
            dx, dz = dx / length, dz / length
        p.move_x, p.move_z = dx, dz

    def act(self, p: Player, action: str, payload: Dict) -> None:
        if p.dead:
            if action == "respawn":
                self.respawn(p)
                return
            raise GameError("你已经死了，点「重新开始」")
        fx, fz = _facing(payload, p)
        handlers = {
            "interact": lambda: self.interact(p),
            "craft": lambda: self.craft(p, str(payload.get("recipe", ""))),
            "build": lambda: self.build(p, str(payload.get("kind", "")), fx, fz),
            "upgrade": lambda: self.upgrade(p),
            "fuel": lambda: self.fuel(p),
            "farm": lambda: self.farm(p, fx, fz),
            "enter": lambda: self.enter(p),
            "exit": lambda: self.exit_house(p),
            "place": lambda: self.place(p, str(payload.get("item", "")), fx, fz),
            "use": lambda: self.use(p, str(payload.get("item", ""))),
            "heal": lambda: self.heal(p),
        }
        fn = handlers.get(action)
        if fn is None:
            raise GameError("不认识的操作")
        fn()

    def _dist(self, p: Player, x: float, z: float) -> float:
        return math.hypot(p.x - x, p.z - z)

    def _outdoor_only(self, p: Player) -> None:
        if p.house is not None:
            raise GameError("在屋里不能这样做，先出屋")

    # ------------------------------------------------------------ 互动（E）

    def interact(self, p: Player) -> None:
        """E 键：自动选最近的目标。屋里：拿家具；室外：动物、树、其他资源、房子、钓鱼。"""
        if self.time < p.next_action:
            return
        if p.house is not None:
            return self._pickup_furniture(p)
        animal = min((a for a in self.animals if self._dist(p, a.x, a.z) <= 2.0),
                     key=lambda a: self._dist(p, a.x, a.z), default=None)
        if animal:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._hit_animal(p, animal)
        if self._nearest_building(p, ("house",), 2.2):      # 站在门口，优先进屋
            return self.enter(p)
        tree = self._nearest_resource(p, ("tree",), 2.5)
        if tree:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._chop(p, tree)
        plant = self._nearest_resource(p, tuple(k for k in C.RESOURCES if k != "tree"), 2.0)
        if plant:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._gather(p, plant)
        house = self._nearest_building(p, ("house",), 3.0)
        if house:
            return self.enter(p)
        if self._near_water(p.x, p.z):
            return self._fish(p)
        raise GameError("附近没有可以互动的东西。树、石头、动物、房子，或者浅海边")

    def _nearest_resource(self, p: Player, kinds: Tuple[str, ...], reach: float) -> Optional[Resource]:
        best, best_d = None, reach
        for r in self.res:
            if r.present and r.kind in kinds:
                d = self._dist(p, r.x + 0.5, r.z + 0.5)
                if d <= best_d:
                    best, best_d = r, d
        return best

    def _nearest_building(self, p: Player, kinds: Tuple[str, ...], reach: float,
                          lit_only: bool = False) -> Optional[Building]:
        best, best_d = None, reach
        for b in self.buildings.values():
            if lit_only and b.fuel_until <= self.time:
                continue
            if b.kind in kinds:
                s = size_of(b.kind)
                d = self._dist(p, b.x + s / 2, b.z + s / 2)
                if d <= best_d:
                    best, best_d = b, d
        return best

    def _tool_bonus_axe(self, p: Player) -> int:
        for tool in ("iron_axe", "stone_axe"):
            if p.inv.get(tool, 0) > 0:
                return C.AXE_BONUS[tool]
        return 0

    def _hit_animal(self, p: Player, a: Animal) -> None:
        name = C.ANIMALS[a.kind][0]
        damage = 2 if p.inv.get("spear", 0) > 0 else 1
        a.hp -= damage
        if a.hp > 0:
            self._msg(p, f"攻击了{name}")
            return
        self.animals.remove(a)
        p.inv["raw_meat"] = p.inv.get("raw_meat", 0) + 1
        self._msg(p, f"打死了{name}，得到一块生肉")

    def _chop(self, p: Player, r: Resource) -> None:
        r.hp -= 1
        gain = 1 + self._tool_bonus_axe(p)
        p.inv["wood"] = p.inv.get("wood", 0) + gain
        if r.hp > 0:
            self._msg(p, f"砍了一下树，得到 {gain} 木材")
            return
        r.present = False
        r.regrow_at = self.time + C.RESOURCES["tree"][2]
        self.tree_at.pop(r.z * W + r.x, None)
        msg = f"砍倒了一棵树，得到 {gain} 木材"
        if self.rng.random() < 0.5:
            p.inv["coconut"] = p.inv.get("coconut", 0) + 1
            msg += "，还掉下一个椰子"
        self._msg(p, msg)

    def _gather(self, p: Player, r: Resource) -> None:
        if r.kind == "rock":
            # 空手也能掰下石头（1 块），有石镐 2 块；空手也有几率挖到铁矿石，有铁镐更高。
            # 这样不会出现「要石镐 → 要工作台 → 要石头」「要铁镐 → 要铁锭 → 要铁矿石」的死循环。
            stone = 2 if p.inv.get("stone_pick", 0) + p.inv.get("iron_pick", 0) > 0 else 1
            self._add(p, "stone", stone)
            ore_chance = 0.25 if p.inv.get("iron_pick", 0) > 0 else 0.08
            if self.rng.random() < ore_chance:
                self._add(p, "iron_ore", 1)
                self._msg(p, f"采到了 {stone} 块石头，还有一块铁矿石")
            else:
                self._msg(p, f"采到了 {stone} 块石头")
        elif r.kind == "reed":
            self._add(p, "fiber", 1)
            self._msg(p, "割了一把芦苇，得到纤维")
        elif r.kind == "herb":
            self._add(p, "herb", 1)
            msg = "采集到 1 个草本植物"
            if self.rng.random() < C.WILD_SEED_CHANCE:
                seed = self.rng.choice(C.SEEDS)
                self._add(p, seed, 1)
                msg += f"，还掉下一颗{C.ITEMS[seed]}"
            self._msg(p, msg)
        elif r.kind == "bush":
            self._add(p, "berry", 1)
            self._msg(p, "采到 1 个浆果")
        elif r.kind == "shell":
            self._add(p, "shell", 1)
            self._msg(p, "捡到一个贝壳")
        elif r.kind == "mushroom":
            self._add(p, "mushroom", 1)
            self._msg(p, "采到一朵蘑菇")
        r.hp -= 1
        if r.hp <= 0:
            r.present = False
            r.regrow_at = self.time + C.RESOURCES[r.kind][2]
            if r.kind == "rock":
                self.rock_at.pop(r.z * W + r.x, None)

    def _add(self, p: Player, item: str, n: int) -> None:
        p.inv[item] = p.inv.get(item, 0) + n

    def _fish(self, p: Player) -> None:
        if self.time < p.next_fish:
            raise GameError("鱼还没上钩，稍等一下")
        p.next_fish = self.time + FISH_COOLDOWN
        if self.rng.random() < FISH_CHANCE:
            self._add(p, "raw_fish", 1)
            self._msg(p, "钓到一条生鱼")
        else:
            self._msg(p, "什么也没钓到")

    # ------------------------------------------------------------ 合成

    def _station_ok(self, p: Player, station: Optional[str], level: int) -> None:
        """检查设施：工作台、石炉在身边 3.5 格内；火堆要在身边、并且正在烧。"""
        if station is None:
            return
        if station == "fire":
            b = self._nearest_building(p, ("campfire",), REACH, lit_only=True)
            if b is None:
                raise GameError("要在一个正在烧着的火堆旁边（3 格内）才能做这个")
            if b.level < level:
                raise GameError(f"火堆要升到 {level} 级才能做这个")
            return
        b = self._nearest_building(p, (station,), REACH)
        if b is None:
            raise GameError(f"要在{C.BUILDS[station]['name']}旁边（3 格内）才能做这个")
        if b.level < level:
            raise GameError(f"{C.BUILDS[station]['name']}要升到 {level} 级才能做这个")

    def craft(self, p: Player, recipe_id: str) -> None:
        self._outdoor_only(p)
        r = C.RECIPES.get(recipe_id)
        if r is None:
            raise GameError("没有这个配方")
        # 有的配方对不同角色要的材料不一样（比如草药：医生 3 个，其他人 6 个）
        inputs = r["in"] if not r.get("role") or r["role"] == p.role else r.get("in_other", r["in"])
        self._station_ok(p, r["station"], r["level"])
        missing = [C.ITEMS[k] for k, n in inputs.items() if p.inv.get(k, 0) < n]
        if missing:
            raise GameError("材料不够：还缺 " + "、".join(missing))
        for k, n in inputs.items():
            p.inv[k] -= n
        mult = 1
        if r["station"] == "furnace":
            mult = self._nearest_building(p, ("furnace",), REACH).level
        for k, n in r["out"].items():
            self._add(p, k, n * mult)
        made = "、".join(f"{C.ITEMS[k]} × {n * mult}" for k, n in r["out"].items())
        self._msg(p, f"做好了{made}")
        if r["station"] == "fire" and p.role == "chef":
            p.hunger = min(100.0, p.hunger + CHEF_COOK_BONUS)
            self._msg(p, f"厨艺让你额外吃饱了 {CHEF_COOK_BONUS} 点")

    # ------------------------------------------------------------ 建造

    def build(self, p: Player, kind: str, fx: float, fz: float) -> None:
        self._outdoor_only(p)
        spec = C.BUILDS.get(kind)
        if spec is None:
            raise GameError("不能建这个")
        if kind == "house" and self._nearest_building(p, ("house",), 6.0):
            raise GameError("附近已经有房子了，离远一点再建")
        missing = [C.ITEMS[k] for k, n in spec["cost"].items() if p.inv.get(k, 0) < n]
        if missing:
            raise GameError("材料不够：还缺 " + "、".join(missing))
        size = spec["size"]
        tx = int(math.floor(p.x + fx * 2.0))
        tz = int(math.floor(p.z + fz * 2.0))
        tiles = [(tx + dx, tz + dz) for dz in range(size) for dx in range(size)]
        for tx2, tz2 in tiles:
            if not (0 <= tx2 < W and 0 <= tz2 < H):
                raise GameError("这里不能建，地图边缘")
            if self.terrain[tz2 * W + tx2] not in LAND:
                raise GameError("只能建在陆地上")
            if not self._free_tile(tz2 * W + tx2) or self._resource_on(tx2, tz2):
                raise GameError("这里已经有东西了")
        if self._dist(p, tx + size / 2, tz + size / 2) > 3.5 + size:
            raise GameError("离得太远了")
        for k, n in spec["cost"].items():
            p.inv[k] -= n
        b = self._place_building(kind, tx, tz, owner=p.account_id)
        self._msg(p, f"建好了{spec['name']}")
        return b

    def _place_building(self, kind: str, x: int, z: int, owner: int = 0, level: int = 1) -> Building:
        b = Building(id=self._new_id(), kind=kind, x=x, z=z, level=level, owner=owner)
        self.buildings[b.id] = b
        for dz in range(size_of(kind)):
            for dx in range(size_of(kind)):
                self.build_at[(z + dz) * W + (x + dx)] = b.id
        return b

    def upgrade(self, p: Player) -> None:
        if p.house is not None:
            b = self.buildings.get(p.house)
        else:
            b = self._nearest_building(p, ("workbench", "campfire", "furnace", "house"), REACH)
        if b is None or b.kind == "plot":
            raise GameError("附近没有可以升级的建筑")
        spec = C.BUILDS[b.kind]
        if b.level >= spec["max_level"]:
            raise GameError(f"{spec['name']}已经是最高级了")
        cost = C.UPGRADES[b.kind][b.level + 1]
        missing = [C.ITEMS[k] for k, n in cost.items() if p.inv.get(k, 0) < n]
        if missing:
            raise GameError("升级材料不够：还缺 " + "、".join(missing))
        for k, n in cost.items():
            p.inv[k] -= n
        b.level += 1
        self._msg(p, f"{spec['name']}升到了 {b.level} 级")

    def fuel(self, p: Player) -> None:
        self._outdoor_only(p)
        b = self._nearest_building(p, ("campfire",), REACH)
        if b is None:
            raise GameError("要在火堆旁边才能加柴")
        if p.inv.get("wood", 0) < 1:
            raise GameError("没有木材可以当柴")
        p.inv["wood"] -= 1
        base = max(self.time, b.fuel_until)
        b.fuel_until = min(self.time + C.FUEL_MAX, base + C.FUEL_SECONDS[b.level])
        self._msg(p, "加了一根柴，火烧得更旺了")

    # ------------------------------------------------------------ 种田

    def farm(self, p: Player, fx: float, fz: float) -> None:
        """G 键：面前有农田就收获或播种；面前是草地且有锄头，就翻土。"""
        self._outdoor_only(p)
        tx = int(math.floor(p.x + fx * 1.2))
        tz = int(math.floor(p.z + fz * 1.2))
        plot = self._plot_at(tx, tz) or self._nearest_plot(p)
        if plot is None:
            return self._till(p, tx, tz)
        if plot.crop:
            spec = C.CROPS[plot.crop]
            if self.time < plot.planted_at + spec["grow"]:
                raise GameError(f"{spec['name']}还没成熟")
            self._harvest(p, plot)
            return
        seed = next((s for s in C.SEEDS if p.inv.get(s, 0) > 0), None)
        if seed is None:
            raise GameError("农田是空的，需要种子（草本植物偶尔会掉种子）")
        p.inv[seed] -= 1
        plot.crop = seed.replace("_seed", "")
        plot.planted_at = self.time
        self._msg(p, f"种下了{C.CROPS[plot.crop]['name']}")

    def _till(self, p: Player, tx: int, tz: int) -> None:
        if p.inv.get("hoe", 0) < 1:
            raise GameError("没有锄头，先去工作台做一把")
        if not (0 <= tx < W and 0 <= tz < H) or self.terrain[tz * W + tx] != GRASS:
            raise GameError("只能在草地上翻土")
        if not self._free_tile(tz * W + tx) or self._resource_on(tx, tz):
            raise GameError("这里有东西挡着，没法翻土")
        self._place_building("plot", tx, tz, owner=p.account_id)
        self._msg(p, "翻好了一块地，可以播种了")

    def _plot_at(self, tx: int, tz: int) -> Optional[Building]:
        bid = self.build_at.get(tz * W + tx) if 0 <= tx < W and 0 <= tz < H else None
        b = self.buildings.get(bid) if bid is not None else None
        return b if b and b.kind == "plot" else None

    def _nearest_plot(self, p: Player) -> Optional[Building]:
        best, best_d = None, PLANT_REACH
        for b in self.buildings.values():
            if b.kind == "plot":
                d = self._dist(p, b.x + 0.5, b.z + 0.5)
                if d <= best_d:
                    best, best_d = b, d
        return best

    def _harvest(self, p: Player, plot: Building) -> None:
        spec = C.CROPS[plot.crop]
        got = []
        for item, (lo, hi) in spec["yield"].items():
            n = self.rng.randint(lo, hi)
            self._add(p, item, n)
            got.append(f"{C.ITEMS[item]} × {n}")
        if self.rng.random() < C.SEED_CHANCE:
            self._add(p, spec["seed"], 1)
            got.append(C.ITEMS[spec["seed"]] + " × 1")
        plot.crop = None
        self._msg(p, f"收获了{spec['name']}：" + "、".join(got))

    # ------------------------------------------------------------ 房子

    def enter(self, p: Player) -> None:
        if p.house is not None:
            raise GameError("你已经在屋里了")
        house = self._nearest_building(p, ("house",), 3.0)
        if house is None:
            raise GameError("要走到房子门口附近（3 格内）才能进去")
        size = C.ROOM_SIZE[house.level]
        p.ox, p.oz = p.x, p.z
        p.house = house.id
        p.x, p.z = size / 2, size - 1.2
        p.move_x = p.move_z = 0.0
        self._msg(p, "进屋了。按 Q 出屋")

    def exit_house(self, p: Player) -> None:
        if p.house is None:
            raise GameError("你不在屋里")
        b = self.buildings.get(p.house)
        p.house = None
        if b is not None:
            p.x, p.z = b.x + 1.5, b.z + 3.6          # 门口的外面
        else:
            p.x, p.z = p.ox, p.oz
        p.move_x = p.move_z = 0.0
        self._msg(p, "出屋了")

    def place(self, p: Player, item: str, fx: float, fz: float) -> None:
        if p.house is None:
            raise GameError("要进屋才能布置家具")
        if item not in C.FURNITURE:
            raise GameError("这个东西不能放在屋里")
        if p.inv.get(item, 0) < 1:
            raise GameError(f"背包里没有{C.ITEMS[item]}")
        b = self.buildings[p.house]
        size = C.ROOM_SIZE[b.level]
        x = min(size - 0.6, max(0.6, p.x + fx * 1.2))
        z = min(size - 0.6, max(0.6, p.z + fz * 1.2))
        for f in b.furniture:
            if (f["x"] - x) ** 2 + (f["z"] - z) ** 2 < 0.8 ** 2:
                raise GameError("这里已经放了东西，换个地方")
        p.inv[item] -= 1
        b.furniture.append({"id": self._new_id(), "kind": item, "x": round(x, 2), "z": round(z, 2)})
        self._msg(p, f"放好了{C.ITEMS[item]}")

    def _pickup_furniture(self, p: Player) -> None:
        b = self.buildings[p.house]
        f = min(b.furniture, key=lambda f: (f["x"] - p.x) ** 2 + (f["z"] - p.z) ** 2, default=None)
        if f is None or (f["x"] - p.x) ** 2 + (f["z"] - p.z) ** 2 > PLANT_REACH ** 2:
            raise GameError("附近没有可以拿的家具")
        b.furniture.remove(f)
        self._add(p, f["kind"], 1)
        self._msg(p, f"拿回了{C.ITEMS[f['kind']]}")

    # ------------------------------------------------------------ 吃药、治疗

    def use(self, p: Player, item: str) -> None:
        if p.inv.get(item, 0) < 1:
            raise GameError("背包里没有这个东西")
        if item == "medicine":
            p.inv["medicine"] -= 1
            p.health = min(100.0, p.health + MEDICINE_HEAL)
            p.sick = False
            self._msg(p, f"用了草药：健康 +{MEDICINE_HEAL}，疾病好了")
            return
        if item not in C.FOOD:
            raise GameError("这个东西不能吃")
        p.inv[item] -= 1
        hunger, sanity, health, sick_chance = C.FOOD[item]
        p.hunger = min(100.0, p.hunger + hunger)
        p.sanity = min(100.0, p.sanity + sanity)
        p.health = min(100.0, p.health + health)
        if sick_chance and self.rng.random() < sick_chance:
            p.sick = True
            self._msg(p, f"吃了{C.ITEMS[item]}，肚子坏了，生病了！")
        else:
            self._msg(p, f"吃了{C.ITEMS[item]}：饱食 +{hunger}")

    def heal(self, p: Player) -> None:
        if p.role != "doctor":
            raise GameError("只有医生会治疗队友")
        if p.inv.get("medicine", 0) < 1:
            raise GameError("没有草药可以治疗")
        target = min((q for q in self.players.values()
                      if q is not p and not q.dead and q.house == p.house and self._dist(p, q.x, q.z) <= 3.0),
                     key=lambda q: self._dist(p, q.x, q.z), default=None)
        if target is None:
            raise GameError("附近 3 格内没有需要治疗的队友")
        p.inv["medicine"] -= 1
        target.health = min(100.0, target.health + DOCTOR_HEAL)
        target.sick = False
        self._msg(p, f"用草药治好了 {target.name}")
        self._msg(target, f"{p.name} 用草药治疗了你，健康 +{DOCTOR_HEAL}，疾病好了")

    def _msg(self, p: Player, text: str) -> None:
        p.events.append(text)
        del p.events[:-6]          # 每个玩家最多保留最近 6 条消息

    # ------------------------------------------------------------ 每个 tick 的世界变化

    def tick(self) -> None:
        self.time += DT
        self.tick_no += 1
        for r in self.res:
            if not r.present and r.regrow_at <= self.time:
                r.present = True
                r.hp = C.RESOURCES[r.kind][1]
                if r.kind == "tree":
                    self.tree_at[r.z * W + r.x] = r.id
                elif r.kind == "rock":
                    self.rock_at[r.z * W + r.x] = r.id
        self._update_animals()
        alive = [p for p in self.players.values() if not p.dead]
        for p in alive:
            self._move(p)
            self._update_stats(p)
        self._priest_blessing(alive)
        self._respawn_animals()

    # 走路：室外看地形和东西；屋里看房间和家具
    def _walkable(self, x: float, z: float) -> bool:
        tx, tz = int(x), int(z)
        if not (0 <= tx < W and 0 <= tz < H):
            return False
        i = tz * W + tx
        if self.terrain[i] not in WALK or i in self.tree_at or i in self.rock_at:
            return False
        bid = self.build_at.get(i)
        return bid is None or self.buildings[bid].kind == "plot"

    def _room_ok(self, b: Building, x: float, z: float) -> bool:
        size = C.ROOM_SIZE[b.level]
        if not (0.5 <= x <= size - 0.5 and 0.5 <= z <= size - 0.5):
            return False
        for f in b.furniture:
            r = C.FURNITURE_BLOCK.get(f["kind"])
            if r and (x - f["x"]) ** 2 + (z - f["z"]) ** 2 < (r + 0.3) ** 2:
                return False
        return True

    def _move(self, p: Player) -> None:
        if p.move_x == 0 and p.move_z == 0:
            return
        if p.house is not None:
            ok = lambda x, z: self._room_ok(self.buildings[p.house], x, z)
            speed = PLAYER_SPEED * DT
        else:
            ok = self._walkable
            speed = PLAYER_SPEED * DT * (0.6 if self.terrain_at(p.x, p.z) == SHALLOW else 1.0)
        nx, nz = p.x + p.move_x * speed, p.z + p.move_z * speed
        # 先试着斜着走；撞到东西就只沿 x 或 z 方向滑过去
        if ok(nx, nz):
            p.x, p.z = nx, nz
        elif ok(nx, p.z):
            p.x = nx
        elif ok(p.x, nz):
            p.z = nz

    def _update_stats(self, p: Player) -> None:
        p.hunger = max(0.0, p.hunger - 0.04 * DT)
        p.sanity = max(0.0, p.sanity - (0.01 if p.role == "priest" else 0.02) * DT)
        # 屋里的床和油灯：让人睡得好、心里亮堂
        if p.house is not None:
            for f in self.buildings[p.house].furniture:
                eff = C.FURNITURE_EFFECT.get(f["kind"])
                if eff and (f["x"] - p.x) ** 2 + (f["z"] - p.z) ** 2 <= eff[2] ** 2:
                    p.sanity = min(100.0, p.sanity + eff[0] * DT)
                    p.health = min(100.0, p.health + eff[1] * DT)
        # 饱食或精神低于 30 时扣血：越低扣得越快，0 的时候每秒扣 1 点
        drain = 0.0
        for v in (p.hunger, p.sanity):
            if v < LOW:
                drain += (LOW - v) / LOW * DT
        if p.sick:
            drain += SICK_DRAIN * DT
        if p.hunger >= SAFE and p.sanity >= SAFE and not p.sick:
            p.health = min(100.0, p.health + 0.3 * DT)
        p.health -= drain
        if p.health <= 0:
            p.health = 0.0
            p.dead = True
            p.move_x = p.move_z = 0.0
            self._msg(p, "你倒下了……点「重新开始」再来一次")

    def _priest_blessing(self, alive: List[Player]) -> None:
        priests = [p for p in alive if p.role == "priest"]
        for pr in priests:
            for q in alive:
                if q is pr or q.role == "priest" or q.house != pr.house:
                    continue
                if self._dist(pr, q.x, q.z) <= PRIEST_RANGE:
                    q.sanity = min(100.0, q.sanity + PRIEST_GAIN * DT)

    def _update_animals(self) -> None:
        outdoor = [p for p in self.players.values() if not p.dead and p.house is None]
        for a in self.animals:
            name, _, kinds, speed, flee, _ = C.ANIMALS[a.kind]
            near = None
            if flee and outdoor:
                near = min(outdoor, key=lambda q: math.hypot(q.x - a.x, q.z - a.z))
                if math.hypot(near.x - a.x, near.z - a.z) > FLEE_RANGE:
                    near = None
            if near:
                a.heading = math.atan2(a.z - near.z, a.x - near.x)
                step = FLEE_SPEED * DT
            else:
                if self.time >= a.turn_at:
                    a.heading = self.rng.uniform(0, 2 * math.pi)
                    a.turn_at = self.time + self.rng.uniform(2, 5)
                step = speed * DT
            nx = a.x + math.cos(a.heading) * step
            nz = a.z + math.sin(a.heading) * step
            if self._animal_ok(nx, nz, kinds):
                a.x, a.z = nx, nz
            else:
                a.heading += math.pi      # 撞墙了就掉头
                a.turn_at = self.time + 1

    def _animal_ok(self, x: float, z: float, kinds: Tuple[int, ...]) -> bool:
        tx, tz = int(x), int(z)
        if not (0 <= tx < W and 0 <= tz < H):
            return False
        i = tz * W + tx
        return self.terrain[i] in kinds and self._free_tile(i)

    def _respawn_animals(self) -> None:
        for kind, spec in C.ANIMALS.items():
            count = sum(1 for a in self.animals if a.kind == kind)
            if count < spec[5] and self.rng.random() < 0.03:
                self._spawn_animal(kind)

    # ------------------------------------------------------------ 存档

    def to_dict(self) -> dict:
        """整个世界的快照。服务器每隔一段时间存一次，关闭前也存一次。"""
        saved = dict(self.saved)
        for p in self.players.values():
            saved[p.account_id] = _player_to_dict(p)
        return {
            "version": self.SAVE_VERSION,
            "seed": self.seed,
            "time": self.time,
            "tick": self.tick_no,
            "next_id": self._next_id,
            "res": [[r.id, r.kind, r.x, r.z, r.hp, r.present, r.regrow_at] for r in self.res],
            "animals": [[a.id, a.kind, a.x, a.z, a.hp, a.heading, a.turn_at] for a in self.animals],
            "buildings": [[b.id, b.kind, b.x, b.z, b.level, b.owner, b.fuel_until, b.crop, b.planted_at,
                           b.furniture] for b in self.buildings.values()],
            "saved": {str(k): v for k, v in saved.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        if d.get("version") != cls.SAVE_VERSION:
            raise ValueError(f"存档版本 {d.get('version')} 与当前版本 {cls.SAVE_VERSION} 不一致")
        g = cls(int(d["seed"]))          # 地形由种子决定，直接重新生成
        g.time = float(d["time"])
        g.tick_no = int(d["tick"])
        g._next_id = int(d["next_id"])
        g.res = [Resource(id=i, kind=k, x=x, z=z, hp=hp, present=pr, regrow_at=ra)
                 for i, k, x, z, hp, pr, ra in d["res"]]
        g.tree_at = {r.z * W + r.x: r.id for r in g.res if r.kind == "tree" and r.present}
        g.rock_at = {r.z * W + r.x: r.id for r in g.res if r.kind == "rock" and r.present}
        g.animals = [Animal(id=i, kind=k, x=x, z=z, hp=hp, heading=h, turn_at=t)
                     for i, k, x, z, hp, h, t in d["animals"]]
        g.buildings, g.build_at = {}, {}
        for i, kind, x, z, level, owner, fuel, crop, planted, furniture in d["buildings"]:
            b = Building(id=i, kind=kind, x=x, z=z, level=level, owner=owner, fuel_until=fuel,
                         crop=crop, planted_at=planted, furniture=furniture)
            g.buildings[b.id] = b
            for dz in range(size_of(kind)):
                for dx in range(size_of(kind)):
                    g.build_at[(z + dz) * W + (x + dx)] = b.id
        g.saved = {int(k): v for k, v in d["saved"].items()}
        return g

    # ------------------------------------------------------------ 发给客户端的数据

    def static_info(self) -> Dict:
        """开局时发一次：地图、名字表、配方、常量。之后不再变。"""
        return {
            "w": W, "h": H, "seed": self.seed,
            "terrain": "".join(str(t) for t in self.terrain),
            "roles": ROLES, "items": C.ITEMS,
            "viewRadius": VIEW_RADIUS,
            "animalNames": {k: v[0] for k, v in C.ANIMALS.items()},
            "resourceNames": {k: v[0] for k, v in C.RESOURCES.items()},
            "recipes": {k: {"name": v["name"], "in": v["in"], "in_other": v.get("in_other"), "out": v["out"],
                            "station": v["station"], "level": v["level"], "role": v.get("role")}
                        for k, v in C.RECIPES.items()},
            "stationNames": C.STATION_NAMES,
            "builds": {k: {"name": v["name"], "cost": v["cost"], "size": v["size"],
                           "maxLevel": v["max_level"]} for k, v in C.BUILDS.items()},
            "upgrades": {k: {str(lv): cost for lv, cost in v.items()} for k, v in C.UPGRADES.items()},
            "crops": {k: {"name": v["name"], "grow": v["grow"]} for k, v in C.CROPS.items()},
            "roomSize": {str(k): v for k, v in C.ROOM_SIZE.items()},
            "furniture": list(C.FURNITURE),
            "tools": list(C.TOOLS),
        }

    def view(self, p: Player, with_resources: bool) -> Dict:
        """给一个玩家的状态快照。只包含他附近的东西（服务器裁剪，客户端看不到远处的）。"""
        cx, cz = p.x, p.z
        r2 = VIEW_RADIUS * VIEW_RADIUS

        def near(x: float, z: float) -> bool:
            return (x - cx) ** 2 + (z - cz) ** 2 <= r2

        msgs, p.events = p.events, []
        data = {
            "t": round(self.time, 1),
            "me": {
                "id": p.id, "name": p.name, "role": p.role,
                "x": round(p.x, 2), "z": round(p.z, 2),
                "hunger": round(p.hunger, 1), "health": round(p.health, 1),
                "sanity": round(p.sanity, 1), "sick": p.sick, "dead": p.dead,
                "inv": {k: v for k, v in p.inv.items() if v > 0},
                "events": msgs, "house": p.house,
            },
            "players": [[q.id, q.name, q.role, round(q.x, 2), round(q.z, 2), q.dead, q.sick]
                        for q in self.players.values() if q.house == p.house],
        }
        if p.house is not None:
            b = self.buildings[p.house]
            data["room"] = {"id": b.id, "size": C.ROOM_SIZE[b.level], "level": b.level,
                            "furniture": [[f["id"], f["kind"], f["x"], f["z"]] for f in b.furniture]}
            data["animals"], data["fires"], data["buildings"] = [], [], []
            return data
        data["animals"] = [[a.id, a.kind, round(a.x, 2), round(a.z, 2), a.hp]
                           for a in self.animals if near(a.x, a.z)]
        data["buildings"] = [self._building_row(b) for b in self.buildings.values()
                             if near(b.x + size_of(b.kind) / 2, b.z + size_of(b.kind) / 2)]
        if with_resources:
            data["res"] = [[r.id, r.kind, r.x, r.z, r.hp] for r in self.res
                           if r.present and near(r.x + 0.5, r.z + 0.5)]
        return data

    def _building_row(self, b: Building) -> list:
        """[编号, 种类, 中心 x, 中心 z, 等级, 状态]。状态：农田是 作物:阶段，火堆是 lit/out，房子是房间大小。"""
        s = size_of(b.kind)
        state = ""
        if b.kind == "plot":
            if b.crop:
                progress = (self.time - b.planted_at) / C.CROPS[b.crop]["grow"]
                state = f"{b.crop}:{0 if progress < 0.4 else 1 if progress < 1 else 2}"
            else:
                state = "empty"
        elif b.kind == "campfire":
            state = "lit" if b.fuel_until > self.time else "out"
        elif b.kind == "house":
            state = str(C.ROOM_SIZE[b.level])
        return [b.id, b.kind, round(b.x + s / 2, 2), round(b.z + s / 2, 2), b.level, state]


def _facing(payload: Dict, p: Player) -> Tuple[float, float]:
    """客户端告诉服务器「我面朝哪边」（单位向量）。没有就看最近移动的方向，再没有就朝南。"""
    try:
        fx, fz = float(payload.get("fx", 0)), float(payload.get("fz", 0))
    except (TypeError, ValueError):
        fx = fz = 0.0
    length = math.hypot(fx, fz)
    if length > 0.01:
        return fx / length, fz / length
    length = math.hypot(p.move_x, p.move_z)
    if length > 0.01:
        return p.move_x / length, p.move_z / length
    return 0.0, 1.0
