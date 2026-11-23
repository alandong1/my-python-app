"""游戏世界：地图生成、玩家、建筑、部队、战斗、野怪、战争迷雾。

所有状态都在内存里，由 main.py 里的循环每 TICK_SECONDS 调用一次 tick()。
"""
from __future__ import annotations

import math
import random
import uuid
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from . import config as C

Coord = Tuple[int, int]


class GameError(Exception):
    """玩家操作不合法时抛出，消息会显示给玩家。"""


# ---------------------------------------------------------------- 数据结构

class Tile:
    __slots__ = ("terrain", "owner", "building", "level", "npc")

    def __init__(self, terrain: str):
        self.terrain = terrain
        self.owner: Optional[str] = None
        self.building: Optional[str] = None
        self.level = 0
        self.npc: Optional[dict] = None  # {"type", "power", "max"}


class Army:
    def __init__(self, aid: int, owner: str, x: int, y: int, units: Dict[str, int]):
        self.id = aid
        self.owner = owner
        self.x, self.y = x, y
        self.units = {k: v for k, v in units.items() if v > 0}
        self.path: List[Coord] = []
        self.progress = 0

    def size(self) -> int:
        return sum(self.units.values())

    def speed(self) -> int:
        return max(C.UNITS[u]["speed"] for u in self.units) if self.units else 1


class Player:
    def __init__(self, pid: str, account_id: int, name: str, color: str):
        self.id = pid
        self.account_id = account_id
        self.name = name
        self.color = color
        self.alive = False
        self.res = {"gold": 0.0, "wood": 0.0}
        self.research = {"weapon": 0, "armor": 0}
        self.queue: List[dict] = []
        self.hq: Optional[Coord] = None
        self.tiles: Set[Coord] = set()
        self.explored: Set[Coord] = set()
        self.visible: Set[Coord] = set()
        self.events: List[dict] = []
        self.online = 0

    def log(self, text: str, kind: str = "info"):
        self.events.append({"text": text, "kind": kind})


# ---------------------------------------------------------------- 地图生成

def _value_noise(w: int, h: int, cell: int, rng: random.Random) -> List[List[float]]:
    gw, gh = w // cell + 2, h // cell + 2
    grid = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            gx, gy = x / cell, y / cell
            x0, y0 = int(gx), int(gy)
            fx, fy = gx - x0, gy - y0
            fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
            a = grid[y0][x0] * (1 - fx) + grid[y0][x0 + 1] * fx
            b = grid[y0 + 1][x0] * (1 - fx) + grid[y0 + 1][x0 + 1] * fx
            out[y][x] = a * (1 - fy) + b * fy
    return out


def _fractal(w, h, rng):
    layers = [(_value_noise(w, h, 12, rng), 0.6), (_value_noise(w, h, 6, rng), 0.3),
              (_value_noise(w, h, 3, rng), 0.1)]
    return [[sum(l[y][x] * wt for l, wt in layers) for x in range(w)] for y in range(h)]


def generate_map(w: int, h: int, seed: Optional[int] = None) -> List[List[Tile]]:
    rng = random.Random(seed)
    elev = _fractal(w, h, rng)
    moist = _fractal(w, h, rng)
    tiles = []
    for y in range(h):
        row = []
        for x in range(w):
            e, m = elev[y][x], moist[y][x]
            if e < 0.30:
                t = C.WATER
            elif e > 0.70:
                t = C.MOUNTAIN
            elif e > 0.62:
                t = C.HILLS
            elif m > 0.58:
                t = C.FOREST
            else:
                t = C.PLAINS
            if t in (C.PLAINS, C.HILLS) and rng.random() < 0.035:
                t = C.GOLD
            row.append(Tile(t))
        tiles.append(row)

    # 中央留给巨龙
    cx, cy = w // 2, h // 2
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            tiles[cy + dy][cx + dx].terrain = C.PLAINS

    def passable(x, y):
        return tiles[y][x].terrain not in C.IMPASSABLE

    def component(sx, sy):
        seen = {(sx, sy)}
        q = deque([(sx, sy)])
        while q:
            x, y = q.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and passable(nx, ny):
                    seen.add((nx, ny))
                    q.append((nx, ny))
        return seen

    # 找出最大的一片连通陆地
    visited: set = set()
    main: set = set()
    for y in range(h):
        for x in range(w):
            if (x, y) not in visited and passable(x, y):
                comp = component(x, y)
                visited |= comp
                if len(comp) > len(main):
                    main = comp

    # 中央如果不在最大陆地上（被湖泊或高山围住），就开一条路连过去
    if (cx, cy) not in main:
        prev = {(cx, cy): None}
        q = deque([(cx, cy)])
        end = None
        while q:
            cur = q.popleft()
            if cur in main:
                end = cur
                break
            x, y = cur
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= n[0] < w and 0 <= n[1] < h and n not in prev:
                    prev[n] = cur
                    q.append(n)
        while end is not None:
            ex, ey = end
            if not passable(ex, ey):
                tiles[ey][ex].terrain = C.PLAINS
            end = prev[end]

    # 不和中央连通的孤岛变成高山，保证所有可走地块互通
    reachable = component(cx, cy)
    for y in range(h):
        for x in range(w):
            if (x, y) not in reachable and passable(x, y):
                tiles[y][x].terrain = C.MOUNTAIN
    return tiles


# ---------------------------------------------------------------- 游戏世界

class Game:
    def __init__(self, seed: Optional[int] = None):
        self.w, self.h = C.MAP_W, C.MAP_H
        self.rng = random.Random(seed)
        self.tiles = generate_map(self.w, self.h, seed)
        self.players: Dict[str, Player] = {}
        self.by_account: Dict[int, str] = {}  # 账户 id -> 玩家 id
        self.armies: Dict[int, Army] = {}
        self._next_army = 1
        self.tick_no = 0
        self.dragon_dead_at: Optional[int] = None
        for _ in range(C.NPC_TARGET_COUNT):
            self._spawn_npc()
        self._spawn_dragon()

    # ---------- 工具
    def tile(self, x: int, y: int) -> Tile:
        return self.tiles[y][x]

    def in_map(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def neighbors4(self, x, y):
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if self.in_map(nx, ny):
                yield nx, ny

    def armies_at(self, x: int, y: int) -> List[Army]:
        return [a for a in self.armies.values() if a.x == x and a.y == y]

    def _new_army(self, owner, x, y, units) -> Army:
        a = Army(self._next_army, owner, x, y, units)
        self._next_army += 1
        self.armies[a.id] = a
        return a

    # ---------- 玩家加入 / 出生
    def join(self, account_id: int, name: str) -> Player:
        """已登录的账户进入游戏：已有王国就继续，没有就新建一个。"""
        if account_id in self.by_account:
            p = self.players[self.by_account[account_id]]
            p.name = name[:12] or p.name   # 账户改名后同步
            return p
        name = (name or "").strip()[:12] or "无名领主"
        pid = uuid.uuid4().hex[:8]
        used = {p.color for p in self.players.values()}
        color = next((c for c in C.PLAYER_COLORS if c not in used),
                     "#%06x" % self.rng.randint(0, 0xFFFFFF))
        p = Player(pid, account_id, name, color)
        self.players[pid] = p
        self.by_account[account_id] = pid
        self.spawn(p)
        return p

    def spawn(self, p: Player):
        hqs = [q.hq for q in self.players.values() if q.alive and q.hq]
        best, best_score = None, -1.0
        for _ in range(400):
            x = self.rng.randint(3, self.w - 4)
            y = self.rng.randint(3, self.h - 4)
            ok = True
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    t = self.tile(x + dx, y + dy)
                    if t.owner or t.npc or (abs(dx) <= 1 and abs(dy) <= 1 and t.terrain in C.IMPASSABLE):
                        ok = False
            if not ok or self.tile(x, y).terrain in C.IMPASSABLE:
                continue
            d_center = math.hypot(x - self.w / 2, y - self.h / 2)
            d_hq = min([math.hypot(x - hx, y - hy) for hx, hy in hqs] or [99])
            score = min(d_hq, 20) * 2 + min(d_center, 16)
            if score > best_score:
                best, best_score = (x, y), score
        if best is None:
            raise GameError("地图已满，暂时无法加入")
        x, y = best
        p.alive = True
        p.res = {k: float(v) for k, v in C.START_RES.items()}
        p.research = {"weapon": 0, "armor": 0}
        p.queue = []
        p.hq = (x, y)
        hq = self.tile(x, y)
        hq.terrain = C.PLAINS
        hq.building, hq.level = "hq", 1
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                t = self.tile(x + dx, y + dy)
                if t.terrain not in C.IMPASSABLE:
                    self._set_owner(x + dx, y + dy, p.id)
        # 保证家门口有一块金矿和一片森林
        for (dx, dy), terr in (((2, 0), C.GOLD), ((-2, 0), C.FOREST), ((0, 2), C.FOREST)):
            t = self.tile(x + dx, y + dy)
            if not t.owner and not t.npc:
                t.terrain = terr
        self._new_army(p.id, x, y, {"infantry": 5})
        p.log(f"欢迎，{p.name}！你的主城建立在 ({x},{y})。", "good")

    def respawn(self, p: Player):
        if p.alive:
            raise GameError("你还活着")
        self.spawn(p)

    def _set_owner(self, x, y, pid: Optional[str]):
        t = self.tile(x, y)
        if t.owner and t.owner in self.players:
            self.players[t.owner].tiles.discard((x, y))
        t.owner = pid
        if pid:
            self.players[pid].tiles.add((x, y))

    def _eliminate(self, victim: Player, by: Optional[Player]):
        for (x, y) in list(victim.tiles):
            t = self.tile(x, y)
            t.building, t.level = None, 0
            self._set_owner(x, y, None)
        for a in [a for a in self.armies.values() if a.owner == victim.id]:
            del self.armies[a.id]
        victim.alive = False
        victim.hq = None
        victim.queue = []
        if by:
            loot = {k: int(v * 0.5) for k, v in victim.res.items()}
            for k, v in loot.items():
                by.res[k] += v
            by.log(f"🏆 你攻陷了 {victim.name} 的主城！掠夺 {loot['gold']} 金 / {loot['wood']} 木", "good")
            victim.log(f"💀 你的主城被 {by.name} 攻陷了！", "bad")
        victim.res = {"gold": 0.0, "wood": 0.0}

    # ---------- 计算属性
    def max_level(self, p: Player, btype: str) -> int:
        return max((self.tile(x, y).level for x, y in p.tiles
                    if self.tile(x, y).building == btype), default=0)

    def income(self, p: Player) -> Dict[str, float]:
        inc = {"gold": 0.0, "wood": 0.0}
        if not p.alive:
            return inc
        for x, y in p.tiles:
            t = self.tile(x, y)
            if t.building == "hq":
                for k, v in C.BASE_INCOME.items():
                    inc[k] += v + C.HQ_INCOME_PER_LEVEL * (t.level - 1)
            elif t.building in C.BUILDING_INCOME:
                for k, v in C.BUILDING_INCOME[t.building].items():
                    inc[k] += v * t.level
        return inc

    def unit_power(self, p: Player, unit: str, vs_building=False) -> float:
        u = C.UNITS[unit]
        atk = u["atk"] * (1 + C.RESEARCH_BONUS * p.research["weapon"])
        if vs_building:
            atk *= u.get("siege", 1.0)
        hp = u["hp"] * (1 + C.RESEARCH_BONUS * p.research["armor"])
        return atk * hp / 50

    def army_power(self, a: Army, vs_building=False) -> float:
        p = self.players[a.owner]
        return sum(self.unit_power(p, u, vs_building) * n for u, n in a.units.items())

    def expand_cost(self, p: Player) -> int:
        return C.EXPAND_BASE_GOLD + C.EXPAND_PER_TILE_GOLD * len(p.tiles)

    def _pay(self, p: Player, cost: Dict[str, float], mult: float = 1):
        for k, v in cost.items():
            if p.res[k] < v * mult:
                need = {"gold": "金币", "wood": "木材"}[k]
                raise GameError(f"{need}不足（需要 {int(v * mult)}）")
        for k, v in cost.items():
            p.res[k] -= v * mult

    # ---------- 玩家操作
    def _require_alive(self, p):
        if not p.alive:
            raise GameError("你已出局，请重新开始")

    def _owned(self, p, x, y) -> Tile:
        if not self.in_map(x, y) or self.tile(x, y).owner != p.id:
            raise GameError("这不是你的领地")
        return self.tile(x, y)

    def expand(self, p: Player, x: int, y: int):
        self._require_alive(p)
        if not self.in_map(x, y):
            raise GameError("超出地图")
        t = self.tile(x, y)
        if t.owner:
            raise GameError("该地块已有主人")
        if t.terrain in C.IMPASSABLE:
            raise GameError("无法占领高山或湖泊")
        if t.npc:
            raise GameError("先派兵清除野怪")
        if not any(self.tile(nx, ny).owner == p.id for nx, ny in self.neighbors4(x, y)):
            raise GameError("只能拓展与领地相邻的地块")
        if any(a.owner != p.id for a in self.armies_at(x, y)):
            raise GameError("有敌军驻扎")
        self._pay(p, {"gold": self.expand_cost(p)})
        self._set_owner(x, y, p.id)

    def build(self, p: Player, x: int, y: int, btype: str):
        self._require_alive(p)
        t = self._owned(p, x, y)
        b = C.BUILDINGS.get(btype)
        if not b or not b["buildable"]:
            raise GameError("未知建筑")
        if t.building:
            raise GameError("这里已经有建筑了")
        if b["terrain"] and t.terrain not in b["terrain"]:
            allowed = "、".join(C.TERRAIN_NAMES[k] for k in b["terrain"])
            raise GameError(f"{b['name']}只能建在：{allowed}")
        self._pay(p, b["cost"])
        t.building, t.level = btype, 1
        p.log(f"建造了 {b['name']}", "info")

    def upgrade(self, p: Player, x: int, y: int):
        self._require_alive(p)
        t = self._owned(p, x, y)
        if not t.building:
            raise GameError("这里没有建筑")
        if t.level >= C.MAX_BUILDING_LEVEL:
            raise GameError("已经是最高等级")
        b = C.BUILDINGS[t.building]
        self._pay(p, b["cost"], t.level + 1)
        t.level += 1
        p.log(f"{b['name']} 升到了 {t.level} 级", "info")

    def demolish(self, p: Player, x: int, y: int):
        self._require_alive(p)
        t = self._owned(p, x, y)
        if t.building == "hq":
            raise GameError("不能拆除主城")
        t.building, t.level = None, 0

    def train(self, p: Player, unit: str, count: int):
        self._require_alive(p)
        u = C.UNITS.get(unit)
        if not u:
            raise GameError("未知兵种")
        count = max(1, min(int(count), 50))
        need = u["barracks"]
        if self.max_level(p, "barracks") < need:
            raise GameError(f"需要 {need} 级兵营才能训练{u['name']}")
        if len(p.queue) >= 8:
            raise GameError("训练队列已满")
        self._pay(p, u["cost"], count)
        p.queue.append({"unit": unit, "count": count, "progress": 0})

    def research(self, p: Player, kind: str):
        self._require_alive(p)
        r = C.RESEARCH.get(kind)
        if not r:
            raise GameError("未知研究")
        lvl = p.research[kind]
        if lvl >= self.max_level(p, "smithy"):
            raise GameError("需要更高等级的铁匠铺")
        self._pay(p, r["cost"], lvl + 1)
        p.research[kind] = lvl + 1
        p.log(f"{r['name']} 提升到 {lvl + 1} 级", "good")

    def move(self, p: Player, army_id: int, x: int, y: int, fraction: float = 1.0):
        self._require_alive(p)
        a = self.armies.get(int(army_id))
        if not a or a.owner != p.id:
            raise GameError("找不到这支部队")
        if not self.in_map(x, y) or self.tile(x, y).terrain in C.IMPASSABLE:
            raise GameError("无法到达该地点")
        if (x, y) == (a.x, a.y):
            raise GameError("部队已经在这里")
        if (x, y) not in p.explored:
            raise GameError("不能向未探索的区域进军")
        path = self._find_path((a.x, a.y), (x, y))
        if not path:
            raise GameError("没有可行的路线")
        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction < 1.0:
            part = {u: int(n * fraction) for u, n in a.units.items()}
            if sum(part.values()) == 0:
                raise GameError("部队人数太少，无法分兵")
            if sum(part.values()) < a.size():
                for u, n in part.items():
                    a.units[u] -= n
                a.units = {u: n for u, n in a.units.items() if n > 0}
                a = self._new_army(p.id, a.x, a.y, part)
        a.path = path
        a.progress = 0

    def stop(self, p: Player, army_id: int):
        a = self.armies.get(int(army_id))
        if a and a.owner == p.id:
            a.path = []

    def _find_path(self, start: Coord, goal: Coord) -> List[Coord]:
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            for n in self.neighbors4(*cur):
                if n not in prev and self.tile(*n).terrain not in C.IMPASSABLE:
                    prev[n] = cur
                    q.append(n)
        if goal not in prev:
            return []
        path = []
        cur = goal
        while cur != start:
            path.append(cur)
            cur = prev[cur]
        return path[::-1]

    # ---------- 战斗
    @staticmethod
    def _survive(winner: float, loser: float) -> float:
        """兰彻斯特平方律：胜方存活比例。"""
        if winner <= 0:
            return 0.0
        return math.sqrt(max(0.0, 1 - (loser / winner) ** 2))

    @staticmethod
    def _shrink(a: Army, frac: float):
        a.units = {u: int(round(n * frac)) for u, n in a.units.items()}
        a.units = {u: n for u, n in a.units.items() if n > 0}

    def _step_army(self, a: Army):
        """部队尝试走进下一格。返回后部队可能已被消灭。"""
        p = self.players[a.owner]
        nx, ny = a.path[0]
        t = self.tile(nx, ny)
        enemies = [e for e in self.armies_at(nx, ny) if e.owner != a.owner]
        terrain_mult = C.TERRAIN_DEFENSE.get(t.terrain, 1.0)

        # 1) 野怪
        if t.npc:
            info = C.NPC_TYPES[t.npc["type"]]
            atk = self.army_power(a)
            dfn = t.npc["power"]
            if atk > dfn:
                self._shrink(a, self._survive(atk, dfn))
                for k, v in info["reward"].items():
                    p.res[k] += v
                p.log(f"⚔️ 击败了{info['name']}！获得 {info['reward']['gold']} 金 / {info['reward']['wood']} 木", "good")
                if t.npc["type"] == "dragon":
                    self.dragon_dead_at = self.tick_no
                    for q in self.players.values():
                        if q is not p:
                            q.log(f"🐉 {p.name} 屠杀了远古巨龙！", "info")
                t.npc = None
                if not a.units:
                    del self.armies[a.id]
                    return
            else:
                t.npc["power"] = dfn * self._survive(dfn, atk)
                del self.armies[a.id]
                p.log(f"💀 你的部队被{info['name']}全歼（敌方剩余战力 {int(t.npc['power'])}）", "bad")
                return

        # 2) 敌方部队 + 建筑防御
        owner = self.players.get(t.owner) if t.owner and t.owner != a.owner else None
        defense_building = 0.0
        if owner and t.building == "hq":
            defense_building = C.HQ_DEFENSE_PER_LEVEL * t.level
        elif owner and t.building == "tower":
            defense_building = C.TOWER_DEFENSE_PER_LEVEL * t.level
        if enemies or defense_building:
            vs_building = defense_building > 0
            atk = self.army_power(a, vs_building)
            enemy_army_power = sum(self.army_power(e) for e in enemies)
            dfn = (enemy_army_power + defense_building) * terrain_mult
            defenders = {self.players[e.owner] for e in enemies}
            if owner:
                defenders.add(owner)
            names = "、".join(d.name for d in defenders)
            if atk > dfn:
                self._shrink(a, self._survive(atk, dfn))
                for e in enemies:
                    del self.armies[e.id]
                p.log(f"⚔️ 在 ({nx},{ny}) 战胜了 {names}！", "good")
                for d in defenders:
                    d.log(f"💀 {p.name} 在 ({nx},{ny}) 击溃了你的防守", "bad")
                if t.building == "tower" and owner:
                    t.building, t.level = None, 0
                if t.building == "hq" and owner:
                    self._eliminate(owner, p)
                if not a.units:
                    del self.armies[a.id]
                    return
            else:
                frac = self._survive(dfn, atk)
                if enemy_army_power > 0:
                    # 建筑防御不损耗，部队按比例损失
                    army_frac = max(0.0, 1 - (1 - frac) * dfn / (enemy_army_power * terrain_mult))
                    for e in enemies:
                        self._shrink(e, army_frac)
                        if not e.units:
                            del self.armies[e.id]
                del self.armies[a.id]
                p.log(f"💀 进攻 ({nx},{ny}) 失败，部队被 {names} 全歼", "bad")
                for d in defenders:
                    d.log(f"🛡️ 成功击退了 {p.name} 在 ({nx},{ny}) 的进攻", "good")
                return

        # 3) 进入地块
        a.x, a.y = nx, ny
        a.path.pop(0)
        if t.owner and t.owner != a.owner and t.building != "hq":
            old = self.players.get(t.owner)
            self._set_owner(nx, ny, a.owner)
            if old:
                old.log(f"⚠️ {p.name} 占领了你在 ({nx},{ny}) 的地块", "bad")
        if not a.path:
            # 到达终点，和同一格的己方静止部队合并
            for other in self.armies_at(nx, ny):
                if other is not a and other.owner == a.owner and not other.path:
                    for u, n in a.units.items():
                        other.units[u] = other.units.get(u, 0) + n
                    del self.armies[a.id]
                    break

    # ---------- 野怪
    def _spawn_npc(self):
        hqs = [q.hq for q in self.players.values() if q.alive and q.hq]
        for _ in range(100):
            x, y = self.rng.randrange(self.w), self.rng.randrange(self.h)
            t = self.tile(x, y)
            if t.owner or t.npc or t.terrain in C.IMPASSABLE or self.armies_at(x, y):
                continue
            d = min([max(abs(x - hx), abs(y - hy)) for hx, hy in hqs] or [99])
            if d < 4:
                continue
            types = [k for k, v in C.NPC_TYPES.items() if v["weight"] > 0]
            if d < 9:
                types = ["wolves", "bandits"]
            weights = [C.NPC_TYPES[k]["weight"] for k in types]
            kind = self.rng.choices(types, weights)[0]
            power = C.NPC_TYPES[kind]["power"] * self.rng.uniform(0.85, 1.2)
            t.npc = {"type": kind, "power": power, "max": power}
            return

    def _spawn_dragon(self):
        cx, cy = self.w // 2, self.h // 2
        t = self.tile(cx, cy)
        if not t.owner:
            p = C.NPC_TYPES["dragon"]["power"]
            t.npc = {"type": "dragon", "power": p, "max": p}
            self.dragon_dead_at = None

    def _npc_count(self) -> int:
        return sum(1 for row in self.tiles for t in row if t.npc and t.npc["type"] != "dragon")

    # ---------- 视野
    def _compute_vision(self, p: Player):
        vis: Set[Coord] = set()

        def add(cx, cy, r):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= r * r + r and self.in_map(cx + dx, cy + dy):
                        vis.add((cx + dx, cy + dy))

        for x, y in p.tiles:
            t = self.tile(x, y)
            r = C.VISION_TERRITORY
            if t.building == "hq":
                r = C.VISION_HQ
            elif t.building == "tower":
                r = C.VISION_TOWER
            add(x, y, r)
        for a in self.armies.values():
            if a.owner == p.id:
                add(a.x, a.y, C.VISION_ARMY)
        p.visible = vis
        new = vis - p.explored
        p.explored |= vis
        return new

    # ---------- 主循环
    def tick(self):
        self.tick_no += 1

        for p in self.players.values():
            if not p.alive:
                continue
            for k, v in self.income(p).items():
                p.res[k] += v
            if p.queue:
                job = p.queue[0]
                u = C.UNITS[job["unit"]]
                lvl = self.max_level(p, "barracks")
                if lvl < u["barracks"]:
                    continue  # 兵营被毁，暂停训练
                per_unit = max(1, round(u["time"] / C.TICK_SECONDS / (1 + 0.25 * (lvl - 1))))
                job["progress"] += 1
                if job["progress"] >= per_unit:
                    job["progress"] = 0
                    job["count"] -= 1
                    self._add_to_hq(p, job["unit"], 1)
                    if job["count"] <= 0:
                        p.queue.pop(0)

        for a in sorted(self.armies.values(), key=lambda a: a.id):
            if a.id not in self.armies or not a.path:
                continue
            a.progress += 1
            if a.progress >= a.speed():
                a.progress = 0
                self._step_army(a)

        for row in self.tiles:
            for t in row:
                if t.npc and t.npc["power"] < t.npc["max"]:
                    t.npc["power"] = min(t.npc["max"], t.npc["power"] + t.npc["max"] * 0.004)

        if self.tick_no % C.NPC_RESPAWN_TICKS == 0 and self._npc_count() < C.NPC_TARGET_COUNT:
            self._spawn_npc()
        if self.dragon_dead_at is not None and self.tick_no - self.dragon_dead_at > C.DRAGON_RESPAWN_TICKS:
            self._spawn_dragon()

    def _add_to_hq(self, p: Player, unit: str, n: int):
        x, y = p.hq
        for a in self.armies_at(x, y):
            if a.owner == p.id and not a.path:
                a.units[unit] = a.units.get(unit, 0) + n
                return
        self._new_army(p.id, x, y, {unit: n})

    # ---------- 序列化（按玩家视野裁剪）
    def view_for(self, p: Player) -> dict:
        new = self._compute_vision(p)
        tiles = []
        for x, y in p.visible:
            t = self.tile(x, y)
            npc = None
            if t.npc:
                npc = [t.npc["type"], int(t.npc["power"]), int(t.npc["max"])]
            tiles.append([x, y, t.terrain, t.owner, t.building, t.level, npc])
        armies = []
        for a in self.armies.values():
            if (a.x, a.y) in p.visible:
                d = {"id": a.id, "owner": a.owner, "x": a.x, "y": a.y,
                     "size": a.size(), "power": int(self.army_power(a))}
                if a.owner == p.id:
                    d["units"] = a.units
                    d["path"] = a.path
                armies.append(d)
        events, p.events = p.events, []
        return {
            "type": "state",
            "tick": self.tick_no,
            "me": {
                "id": p.id, "alive": p.alive, "hq": p.hq,
                "res": {k: int(v) for k, v in p.res.items()},
                "income": {k: round(v * 2, 1) for k, v in self.income(p).items()},  # 每秒
                "research": p.research,
                "queue": p.queue,
                "expandCost": self.expand_cost(p),
                "barracks": self.max_level(p, "barracks"),
                "smithy": self.max_level(p, "smithy"),
                "unitPower": {u: round(self.unit_power(p, u), 1) for u in C.UNITS},
            },
            "tiles": tiles,
            "armies": armies,
            "events": events,
            "newExplored": len(new),
        }

    def scoreboard(self) -> List[dict]:
        rows = []
        for p in self.players.values():
            rows.append({
                "id": p.id, "name": p.name, "color": p.color, "alive": p.alive,
                "online": p.online > 0, "tiles": len(p.tiles),
                "army": sum(a.size() for a in self.armies.values() if a.owner == p.id),
            })
        rows.sort(key=lambda r: (-r["tiles"], -r["army"]))
        return rows

    def static_info(self) -> dict:
        return {
            "w": self.w, "h": self.h, "tick": C.TICK_SECONDS,
            "terrainNames": C.TERRAIN_NAMES,
            "buildings": C.BUILDINGS, "units": C.UNITS, "research": C.RESEARCH,
            "npcs": {k: {"name": v["name"], "icon": v["icon"], "reward": v["reward"]}
                     for k, v in C.NPC_TYPES.items()},
            "maxLevel": C.MAX_BUILDING_LEVEL,
        }

    # ---------- 存档 / 读档
    # 存档格式版本。修改了下面存档的数据结构时 +1，旧存档就不会被错误地读进来。
    SAVE_VERSION = 1

    def to_dict(self) -> dict:
        """把整个世界打包成可以转成 JSON 的字典。"""
        w = self.w
        return {
            "version": self.SAVE_VERSION,
            "w": self.w, "h": self.h,
            "tick": self.tick_no,
            "next_army": self._next_army,
            "dragon_dead_at": self.dragon_dead_at,
            # 每格：[地形, 主人, 建筑, 等级, 野怪]，按行展开
            "tiles": [[t.terrain, t.owner, t.building, t.level, t.npc]
                      for row in self.tiles for t in row],
            "players": [{
                "id": p.id, "account_id": p.account_id, "name": p.name, "color": p.color,
                "alive": p.alive, "res": p.res, "research": p.research, "queue": p.queue,
                "hq": list(p.hq) if p.hq else None,
                # 探索过的格子用一个整数表示：y * 宽 + x，比存坐标对小得多
                "explored": sorted(y * w + x for x, y in p.explored),
            } for p in self.players.values()],
            "armies": [{
                "id": a.id, "owner": a.owner, "x": a.x, "y": a.y, "units": a.units,
                "path": [list(c) for c in a.path], "progress": a.progress,
            } for a in self.armies.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        """从存档恢复世界。格式不兼容时抛出 ValueError。"""
        if d.get("version") != cls.SAVE_VERSION:
            raise ValueError(f"存档版本 {d.get('version')} 与当前版本 {cls.SAVE_VERSION} 不一致")
        if (d["w"], d["h"]) != (C.MAP_W, C.MAP_H):
            raise ValueError(f"存档地图尺寸 {d['w']}x{d['h']} 与当前设置 {C.MAP_W}x{C.MAP_H} 不一致")
        g = cls.__new__(cls)  # 跳过 __init__，不重新生成地图
        g.w, g.h = d["w"], d["h"]
        g.rng = random.Random()
        g.tick_no = d["tick"]
        g._next_army = d["next_army"]
        g.dragon_dead_at = d["dragon_dead_at"]
        g.tiles = []
        flat = d["tiles"]
        for y in range(g.h):
            row = []
            for x in range(g.w):
                terrain, owner, building, level, npc = flat[y * g.w + x]
                t = Tile(terrain)
                t.owner, t.building, t.level, t.npc = owner, building, level, npc
                row.append(t)
            g.tiles.append(row)
        g.players, g.by_account = {}, {}
        for pd in d["players"]:
            p = Player(pd["id"], pd["account_id"], pd["name"], pd["color"])
            p.alive, p.res, p.research, p.queue = pd["alive"], pd["res"], pd["research"], pd["queue"]
            p.hq = tuple(pd["hq"]) if pd["hq"] else None
            p.explored = {(i % g.w, i // g.w) for i in pd["explored"]}
            g.players[p.id] = p
            g.by_account[p.account_id] = p.id
        # 领地列表由地块的主人推出来，不单独存，避免两边不一致
        for y in range(g.h):
            for x in range(g.w):
                owner = g.tiles[y][x].owner
                if owner in g.players:
                    g.players[owner].tiles.add((x, y))
        g.armies = {}
        for ad in d["armies"]:
            a = Army(ad["id"], ad["owner"], ad["x"], ad["y"], ad["units"])
            a.path = [tuple(c) for c in ad["path"]]
            a.progress = ad["progress"]
            g.armies[a.id] = a
        return g
