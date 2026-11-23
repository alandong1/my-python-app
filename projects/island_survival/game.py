"""荒岛求生的游戏规则：地图、玩家、资源、动物、生存数值。

这个文件只管「规则」，不碰网络。服务器（server.py）每 0.1 秒调用一次 tick()，
再把结果发给每个玩家。规则的说明见 REQUIREMENTS.md，测试在 test_game.py。

服务器是「权威」的：所有判断都在这里做，浏览器只负责显示和发送按键。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

W = 200                  # 地图宽（格）
H = 200                  # 地图高（格）
DT = 0.1                 # 每次 tick 经过的秒数（和服务器的节奏一致）
VIEW_RADIUS = 32         # 玩家能看到多远（格），远处的东西不发给他
PLAYER_SPEED = 4.0       # 走路速度：格/秒
TREE_REGROW = 90         # 树砍倒后多少秒长回来
PLANT_REGROW = 60        # 灌木丛、草本植物多少秒再长

# 地形编号。服务器把整张地图编码成一串数字字符发给浏览器。
DEEP, SHALLOW, SAND, GRASS, FOREST = range(5)
LAND = (SAND, GRASS, FOREST)
WALK = (SHALLOW, SAND, GRASS, FOREST)   # 玩家能走的地形（深海不能走）

ROLES = {"chef": "厨师", "doctor": "医生", "priest": "牧师"}

# 物品：(中文名, 饱食, 精神, 生病几率)。草药和熟食的效果写在下面的函数里。
ITEMS = {
    "wood": "木材",
    "coconut": "椰子",
    "berry": "浆果",
    "herb": "草本植物",
    "raw_fish": "生鱼",
    "raw_meat": "生肉",
    "cooked_fish": "熟鱼",
    "cooked_meat": "熟肉",
    "medicine": "草药",
}
FOOD = {
    # 物品: (饱食增加, 精神增加, 吃了生病的几率)
    "coconut": (12, 2, 0.0),
    "berry": (10, 0, 0.0),
    "raw_fish": (15, 0, 0.25),
    "raw_meat": (20, 0, 0.25),
    "cooked_fish": (35, 3, 0.0),
    "cooked_meat": (40, 3, 0.0),
}
COOK = {"raw_fish": "cooked_fish", "raw_meat": "cooked_meat"}

# 资源：kind -> (中文名, 最多能采几次)。树 3 次、灌木丛和草本植物 2 次。
RESOURCES = {"tree": ("树", 3), "bush": ("灌木丛", 2), "herb": ("草本植物", 2)}

# 动物：kind -> (中文名, 血量, 能待的地形, 基础速度, 靠近玩家会不会逃, 目标数量)
ANIMALS = {
    "rabbit": ("兔子", 2, (GRASS, FOREST), 0.6, True, 70),
    "crab": ("螃蟹", 1, (SAND,), 0.3, False, 25),
}
FLEE_RANGE = 5.0         # 玩家距离兔子多近时，兔子开始逃
FLEE_SPEED = 2.4

CHEF_COOK_BONUS = 15     # 厨师做饭时，自己额外获得的饱食度
DOCTOR_HEAL = 30         # 医生治疗队友恢复的健康
MEDICINE_HEAL = 25       # 自己用草药恢复的健康
PRIEST_RANGE = 8.0       # 牧师的祈福范围（格）
PRIEST_GAIN = 0.8        # 每秒给队友恢复的精神
FIRE_LIFETIME = 300      # 火堆能烧多少秒
ACTION_COOLDOWN = 0.4    # 互动之间至少间隔多少秒（防止连点刷资源）
LOW = 30                 # 数值低于这个值会开始扣血
SAFE = 60                # 三项都不低于这个值，健康才会慢慢恢复


class GameError(Exception):
    """玩家的操作不成立（材料不够、位置不对……）。错误信息直接显示给玩家。"""


@dataclass
class Player:
    id: int
    account_id: int
    name: str
    role: str
    x: float = 0.0
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
class Fire:
    id: int
    x: float
    z: float
    until: float


def _player_to_dict(p: Player) -> dict:
    return {
        "account_id": p.account_id, "name": p.name, "role": p.role,
        "x": p.x, "z": p.z, "hunger": p.hunger, "health": p.health, "sanity": p.sanity,
        "sick": p.sick, "dead": p.dead, "inv": dict(p.inv),
    }


def _player_from_dict(d: dict, pid: int) -> Player:
    return Player(
        id=pid, account_id=int(d["account_id"]), name=str(d["name"]), role=str(d["role"]),
        x=float(d["x"]), z=float(d["z"]), hunger=float(d["hunger"]), health=float(d["health"]),
        sanity=float(d["sanity"]), sick=bool(d["sick"]), dead=bool(d["dead"]),
        inv={str(k): int(v) for k, v in d["inv"].items()},
    )


class Game:
    def __init__(self, seed: int = 2026):
        self.seed = seed
        self.rng = random.Random(seed)   # 地图和游戏过程里的随机都用它，同一个种子结果相同
        self.time = 0.0
        self.tick_no = 0
        self.terrain = bytearray(W * H)
        self.res: List[Resource] = []
        self.tree_at: Dict[int, int] = {}          # 格子编号 → 还立着的那棵树的编号（树会挡路）
        self.animals: List[Animal] = []
        self.fires: List[Fire] = []
        self.players: Dict[int, Player] = {}
        self.saved: Dict[int, dict] = {}           # 下线玩家的角色：账户编号 → 数据，再次上线时接着玩
        self._next_id = 1
        self._generate_map()
        self._populate()

    # ------------------------------------------------------------ 地图

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _index(self, x: float, z: float) -> int:
        return int(z) * W + int(x)

    def terrain_at(self, x: float, z: float) -> int:
        tx, tz = int(x), int(z)
        if not (0 <= tx < W and 0 <= tz < H):
            return DEEP
        return self.terrain[tz * W + tx]

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
        land_edge = []
        for z in range(H):
            for x in range(W):
                if self.terrain[z * W + x] == DEEP and self._near_land(x, z):
                    land_edge.append(z * W + x)
        for i in land_edge:
            self.terrain[i] = SHALLOW

    def _near_land(self, x: int, z: int, r: int = 2) -> bool:
        for dz in range(-r, r + 1):
            for dx in range(-r, r + 1):
                tx, tz = x + dx, z + dz
                if 0 <= tx < W and 0 <= tz < H and self.terrain[tz * W + tx] in LAND:
                    return True
        return False

    def _random_tile(self, kinds: Tuple[int, ...], tries: int = 2000) -> Optional[Tuple[int, int]]:
        """随机找一个指定地形、没有树挡着的格子。"""
        for _ in range(tries):
            x, z = self.rng.randrange(W), self.rng.randrange(H)
            if self.terrain[z * W + x] in kinds and (z * W + x) not in self.tree_at:
                return x, z
        return None

    def _populate(self) -> None:
        """放上树、灌木丛、草本植物和动物。"""
        for z in range(H):
            for x in range(W):
                t = self.terrain[z * W + x]
                roll = self.rng.random()
                if t == FOREST and roll < 0.4:
                    self._add_resource("tree", x, z)
                elif t == GRASS and roll < 0.03:
                    self._add_resource("tree", x, z)
                elif t == GRASS and roll < 0.05:
                    self._add_resource("herb", x, z)
                elif t == GRASS and roll < 0.065:
                    self._add_resource("bush", x, z)
        for kind, spec in ANIMALS.items():
            for _ in range(spec[5]):
                self._spawn_animal(kind)

    def _add_resource(self, kind: str, x: int, z: int) -> None:
        hp = RESOURCES[kind][1]
        r = Resource(id=len(self.res), kind=kind, x=x, z=z, hp=hp)
        self.res.append(r)
        if kind == "tree":
            self.tree_at[z * W + x] = r.id

    def _spawn_animal(self, kind: str) -> None:
        _, hp, kinds, _, _, _ = ANIMALS[kind]
        tile = self._random_tile(kinds)
        if tile:
            x, z = tile
            a = Animal(id=self._new_id(), kind=kind, x=x + 0.5, z=z + 0.5, hp=hp,
                       heading=self.rng.uniform(0, 2 * math.pi), turn_at=self.time)
            self.animals.append(a)

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
            if p.dead:
                p.events.append("你还是倒在岛上，点「重新开始」站起来")
        else:
            p = Player(id=self._new_id(), account_id=account_id, name=name[:12] or "幸存者", role=role)
            p.x, p.z = self._spawn_point()
        self.players[p.id] = p
        return p

    def leave(self, pid: int) -> None:
        """下线：角色留在存档里，世界继续运行（别人还可以在岛上找到它的位置，但它不会行动）。"""
        p = self.players.pop(pid, None)
        if p is not None:
            self.saved[p.account_id] = _player_to_dict(p)

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
            "fires": [[f.id, f.x, f.z, f.until] for f in self.fires],
            "saved": {str(k): v for k, v in saved.items()},
        }

    SAVE_VERSION = 1

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
        g.animals = [Animal(id=i, kind=k, x=x, z=z, hp=hp, heading=h, turn_at=t)
                     for i, k, x, z, hp, h, t in d["animals"]]
        g.fires = [Fire(id=i, x=x, z=z, until=u) for i, x, z, u in d["fires"]]
        g.saved = {int(k): v for k, v in d["saved"].items()}
        return g

    def respawn(self, p: Player) -> None:
        if not p.dead:
            return
        p.hunger, p.health, p.sanity = 100.0, 100.0, 100.0
        p.sick, p.dead, p.inv = False, False, {}
        p.move_x = p.move_z = 0.0
        p.x, p.z = self._spawn_point(exclude=p)
        p.events.append("你在岛上的另一个地方醒来了")

    def _spawn_point(self, exclude: Optional[Player] = None) -> Tuple[float, float]:
        """随机选几个陆地位置，挑离其他活着的玩家最远的那个。"""
        others = [(q.x, q.z) for q in self.players.values() if not q.dead and q is not exclude]
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
        fn = {
            "interact": self.interact,
            "build_fire": self.build_fire,
            "cook": lambda q: self.cook(q, payload.get("item")),
            "craft": self.craft_medicine,
            "heal": self.heal,
            "use": lambda q: self.use(q, str(payload.get("item", ""))),
        }.get(action)
        if fn is None:
            raise GameError("不认识的操作")
        fn(p)

    def _dist(self, p: Player, x: float, z: float) -> float:
        return math.hypot(p.x - x, p.z - z)

    def interact(self, p: Player) -> None:
        """E 键：自动选最近的目标——动物、树、灌木丛/草本植物，或者钓鱼。"""
        if self.time < p.next_action:
            return
        animal = min((a for a in self.animals if self._dist(p, a.x, a.z) <= 2.0),
                     key=lambda a: self._dist(p, a.x, a.z), default=None)
        if animal:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._hit_animal(p, animal)
        tree = self._nearest_resource(p, ("tree",), 2.5)
        if tree:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._chop(p, tree)
        plant = self._nearest_resource(p, ("bush", "herb"), 2.0)
        if plant:
            p.next_action = self.time + ACTION_COOLDOWN
            return self._gather(p, plant)
        if self._near_water(p):
            return self._fish(p)
        raise GameError("附近没有可以互动的东西。树、灌木丛、动物，或者浅海边")

    def _nearest_resource(self, p: Player, kinds: Tuple[str, ...], reach: float) -> Optional[Resource]:
        best, best_d = None, reach
        for r in self.res:
            if r.present and r.kind in kinds:
                d = self._dist(p, r.x + 0.5, r.z + 0.5)
                if d <= best_d:
                    best, best_d = r, d
        return best

    def _near_water(self, p: Player) -> bool:
        tx, tz = int(p.x), int(p.z)
        return any(self.terrain_at(tx + dx, tz + dz) == SHALLOW
                   for dx in (-1, 0, 1) for dz in (-1, 0, 1))

    def _hit_animal(self, p: Player, a: Animal) -> None:
        name = ANIMALS[a.kind][0]
        a.hp -= 1
        if a.hp > 0:
            self._msg(p, f"攻击了{name}")
            return
        self.animals.remove(a)
        p.inv["raw_meat"] = p.inv.get("raw_meat", 0) + 1
        self._msg(p, f"打死了{name}，得到一块生肉")

    def _chop(self, p: Player, r: Resource) -> None:
        r.hp -= 1
        p.inv["wood"] = p.inv.get("wood", 0) + 1
        if r.hp > 0:
            self._msg(p, "砍了一下树，得到 1 木材")
            return
        r.present = False
        r.regrow_at = self.time + TREE_REGROW
        self.tree_at.pop(r.z * W + r.x, None)
        msg = "砍倒了一棵树，得到 1 木材"
        if self.rng.random() < 0.5:
            p.inv["coconut"] = p.inv.get("coconut", 0) + 1
            msg += "，还掉下一个椰子"
        self._msg(p, msg)

    def _gather(self, p: Player, r: Resource) -> None:
        item = "berry" if r.kind == "bush" else "herb"
        p.inv[item] = p.inv.get(item, 0) + 1
        r.hp -= 1
        if r.hp <= 0:
            r.present = False
            r.regrow_at = self.time + PLANT_REGROW
        self._msg(p, f"采集到 1 个{ITEMS[item]}")

    def _fish(self, p: Player) -> None:
        if self.time < p.next_fish:
            raise GameError("鱼还没上钩，稍等一下")
        p.next_fish = self.time + 2.0
        if self.rng.random() < 0.4:
            p.inv["raw_fish"] = p.inv.get("raw_fish", 0) + 1
            self._msg(p, "钓到一条生鱼")
        else:
            self._msg(p, "什么也没钓到")

    def build_fire(self, p: Player) -> None:
        if p.inv.get("wood", 0) < 3:
            raise GameError("木材不够，生火需要 3 个木材")
        p.inv["wood"] -= 3
        self.fires.append(Fire(id=self._new_id(), x=p.x, z=p.z, until=self.time + FIRE_LIFETIME))
        self._msg(p, "生了一堆火（能烧 5 分钟）")

    def _fire_near(self, p: Player, reach: float = 3.0) -> bool:
        return any(math.hypot(p.x - f.x, p.z - f.z) <= reach and f.until > self.time for f in self.fires)

    def cook(self, p: Player, item: Optional[str] = None) -> None:
        if not self._fire_near(p):
            raise GameError("要在火堆旁边 3 格以内才能做饭")
        if item is None:
            item = next((k for k in COOK if p.inv.get(k, 0) > 0), None)
        if item not in COOK or p.inv.get(item, 0) < 1:
            raise GameError("背包里没有可以做的生食（生鱼、生肉）")
        p.inv[item] -= 1
        p.inv[COOK[item]] = p.inv.get(COOK[item], 0) + 1
        self._msg(p, f"做好了{ITEMS[COOK[item]]}")
        if p.role == "chef":
            p.hunger = min(100.0, p.hunger + CHEF_COOK_BONUS)
            self._msg(p, f"厨艺让你额外吃饱了 {CHEF_COOK_BONUS} 点")

    def craft_medicine(self, p: Player) -> None:
        if p.role != "doctor":
            raise GameError("只有医生会制药")
        if p.inv.get("herb", 0) < 3:
            raise GameError("草药植物不够，制药需要 3 个草本植物")
        p.inv["herb"] -= 3
        p.inv["medicine"] = p.inv.get("medicine", 0) + 1
        self._msg(p, "制成了 1 份草药")

    def heal(self, p: Player) -> None:
        if p.role != "doctor":
            raise GameError("只有医生会治疗队友")
        if p.inv.get("medicine", 0) < 1:
            raise GameError("没有草药可以治疗")
        target = min((q for q in self.players.values()
                      if q is not p and not q.dead and self._dist(p, q.x, q.z) <= 3.0),
                     key=lambda q: self._dist(p, q.x, q.z), default=None)
        if target is None:
            raise GameError("附近 3 格内没有需要治疗的队友")
        p.inv["medicine"] -= 1
        target.health = min(100.0, target.health + DOCTOR_HEAL)
        target.sick = False
        self._msg(p, f"用草药治好了 {target.name}")
        self._msg(target, f"{p.name} 用草药治疗了你，健康 +{DOCTOR_HEAL}，疾病好了")

    def use(self, p: Player, item: str) -> None:
        if p.inv.get(item, 0) < 1:
            raise GameError("背包里没有这个东西")
        if item == "medicine":
            p.inv["medicine"] -= 1
            p.health = min(100.0, p.health + MEDICINE_HEAL)
            p.sick = False
            self._msg(p, f"用了草药：健康 +{MEDICINE_HEAL}，疾病好了")
            return
        if item not in FOOD:
            raise GameError("这个东西不能吃")
        p.inv[item] -= 1
        hunger, sanity, sick_chance = FOOD[item]
        p.hunger = min(100.0, p.hunger + hunger)
        p.sanity = min(100.0, p.sanity + sanity)
        if sick_chance and self.rng.random() < sick_chance:
            p.sick = True
            self._msg(p, f"吃了{ITEMS[item]}，肚子坏了，生病了！")
        else:
            self._msg(p, f"吃了{ITEMS[item]}：饱食 +{hunger}")

    def _msg(self, p: Player, text: str) -> None:
        p.events.append(text)
        del p.events[:-6]          # 每个玩家最多保留最近 6 条消息

    # ------------------------------------------------------------ 每个 tick 的世界变化

    def tick(self) -> None:
        self.time += DT
        self.tick_no += 1
        self.fires = [f for f in self.fires if f.until > self.time]
        for r in self.res:
            if not r.present and r.regrow_at <= self.time:
                r.present = True
                r.hp = RESOURCES[r.kind][1]
                if r.kind == "tree":
                    self.tree_at[r.z * W + r.x] = r.id
        self._update_animals()
        alive = [p for p in self.players.values() if not p.dead]
        for p in alive:
            self._move(p)
            self._update_stats(p)
        self._priest_blessing(alive)
        self._respawn_animals()

    def _walkable(self, x: float, z: float, kinds: Tuple[int, ...]) -> bool:
        tx, tz = int(x), int(z)
        if not (0 <= tx < W and 0 <= tz < H):
            return False
        i = tz * W + tx
        return self.terrain[i] in kinds and i not in self.tree_at

    def _move(self, p: Player) -> None:
        if p.move_x == 0 and p.move_z == 0:
            return
        speed = PLAYER_SPEED * DT * (0.6 if self.terrain_at(p.x, p.z) == SHALLOW else 1.0)
        nx, nz = p.x + p.move_x * speed, p.z + p.move_z * speed
        # 先试着斜着走；撞到东西就只沿 x 或 z 方向滑过去
        if self._walkable(nx, nz, WALK):
            p.x, p.z = nx, nz
        elif self._walkable(nx, p.z, WALK):
            p.x = nx
        elif self._walkable(p.x, nz, WALK):
            p.z = nz

    def _update_stats(self, p: Player) -> None:
        p.hunger = max(0.0, p.hunger - 0.04 * DT)
        p.sanity = max(0.0, p.sanity - (0.01 if p.role == "priest" else 0.02) * DT)
        # 饱食或精神低于 30 时扣血：越低扣得越快，0 的时候每秒扣 1 点
        drain = 0.0
        for v in (p.hunger, p.sanity):
            if v < LOW:
                drain += (LOW - v) / LOW * DT
        if p.sick:
            drain += 0.3 * DT
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
        if not priests:
            return
        for q in alive:
            if q.role == "priest":
                continue
            for pr in priests:
                if self._dist(pr, q.x, q.z) <= PRIEST_RANGE:
                    q.sanity = min(100.0, q.sanity + PRIEST_GAIN * DT)

    def _update_animals(self) -> None:
        alive = [p for p in self.players.values() if not p.dead]
        for a in self.animals:
            name, _, kinds, speed, flee, _ = ANIMALS[a.kind]
            near = None
            if flee:
                near = min(alive, key=lambda q: math.hypot(q.x - a.x, q.z - a.z), default=None)
                if near and math.hypot(near.x - a.x, near.z - a.z) > FLEE_RANGE:
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
            if self._walkable(nx, nz, kinds):
                a.x, a.z = nx, nz
            else:
                a.heading += math.pi      # 撞墙了就掉头
                a.turn_at = self.time + 1

    def _respawn_animals(self) -> None:
        for kind, spec in ANIMALS.items():
            count = sum(1 for a in self.animals if a.kind == kind)
            if count < spec[5] and self.rng.random() < 0.03:
                self._spawn_animal(kind)

    # ------------------------------------------------------------ 发给客户端的数据

    def static_info(self) -> Dict:
        """开局时发一次：地图、名字表、常量。之后不再变。"""
        return {
            "w": W, "h": H, "seed": self.seed,
            "terrain": "".join(str(t) for t in self.terrain),
            "roles": ROLES, "items": ITEMS,
            "viewRadius": VIEW_RADIUS, "animalNames": {k: v[0] for k, v in ANIMALS.items()},
            "resourceNames": {k: v[0] for k, v in RESOURCES.items()},
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
                "events": msgs,
            },
            "players": [[q.id, q.name, q.role, round(q.x, 2), round(q.z, 2), q.dead, q.sick]
                        for q in self.players.values()],
            "animals": [[a.id, a.kind, round(a.x, 2), round(a.z, 2), a.hp]
                        for a in self.animals if near(a.x, a.z)],
            "fires": [[f.id, round(f.x, 2), round(f.z, 2), round(f.until - self.time)]
                      for f in self.fires if near(f.x, f.z)],
        }
        if with_resources:
            data["res"] = [[r.id, r.kind, r.x, r.z, r.hp] for r in self.res
                           if r.present and near(r.x + 0.5, r.z + 0.5)]
        return data
