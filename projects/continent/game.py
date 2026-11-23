"""大陆争霸的游戏逻辑：地图、单位、建筑、移动、战斗、经济、视野。

这里不碰网络，只管规则。服务器（server.py）负责把玩家的操作交给这里，
再把「玩家自己能看到的那部分世界」发回去。
"""
from __future__ import annotations

import itertools
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from . import config as C

DIRS8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


class GameError(Exception):
    """玩家的操作不合法时抛出，消息会显示给玩家看。"""


@dataclass
class Unit:
    id: int
    owner: int
    kind: str
    x: int
    y: int
    hp: float
    maxhp: float
    cool: int = 0                 # 还要等几个回合才能再开火
    acc: float = 0.0              # 移动「进度」：攒够 1 格才真的走一步
    path: List[Tuple[int, int]] = field(default_factory=list)
    order: Optional[str] = None   # None / "move" / "attack"
    dest: Optional[Tuple[int, int]] = None
    target: Optional[int] = None  # 攻击命令的目标 id


@dataclass
class Building:
    id: int
    owner: int
    kind: str
    x: int
    y: int
    hp: float
    maxhp: float
    cool: int = 0
    queue: List[list] = field(default_factory=list)   # 生产队列：[单位类型, 剩余回合, 总回合]


@dataclass
class Player:
    id: int
    name: str
    color: str
    gold: float
    research: Dict[str, int]
    hq: Optional[int] = None                   # 主基地的建筑 id；None 表示基地被毁
    relocating: Optional[dict] = None          # 搬迁中：{x, y, cost, done}
    relocate_ready: int = 0                    # 冷却结束的回合数
    explored: Set[int] = field(default_factory=set)


def cfg_of(kind: str) -> dict:
    return C.UNITS[kind] if kind in C.UNITS else C.BUILDINGS[kind]


def domain_of(entity) -> str:
    return C.UNITS[entity.kind]["domain"] if isinstance(entity, Unit) else "land"


class World:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.w, self.h = C.W, C.H
        self.terrain: List[str] = []
        self.ore: Set[int] = set()
        self.units: Dict[int, Unit] = {}
        self.buildings: Dict[int, Building] = {}
        self.occ: Dict[int, int] = {}          # 格子 → 占用它的建筑 id
        self.players: Dict[int, Player] = {}
        self.tick_count = 0
        self.next_id = 1
        self.last_t: Optional[float] = None
        self.vis: Dict[int, Set[int]] = {}     # 玩家 id → 当前看得见的格子
        self._circles: Dict[float, List[Tuple[int, int]]] = {}
        self._gen_map()

    # ------------------------------------------------------------ 基本工具

    def idx(self, x: int, y: int) -> int:
        return y * self.w + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def _new_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    def level(self, owner: int, cls: Optional[str]) -> int:
        p = self.players.get(owner)
        if p is None or cls is None:
            return 0
        return p.research.get(cls, 0)

    def is_enemy(self, a: int, b: int) -> bool:
        return a != b

    # ------------------------------------------------------------ 地图生成

    def _gen_map(self) -> None:
        w, h, rng = self.w, self.h, self.rng
        t = [C.PLAIN] * (w * h)

        def blob(cx: int, cy: int, r: float, kind: str) -> None:
            for y in range(int(cy - r) - 1, int(cy + r) + 2):
                for x in range(int(cx - r) - 1, int(cx + r) + 2):
                    if self.in_bounds(x, y):
                        d2 = (x - cx) ** 2 + (y - cy) ** 2
                        if d2 <= r * r * rng.uniform(0.75, 1.1):
                            t[self.idx(x, y)] = kind

        for _ in range(12):   # 森林
            blob(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(1.5, 3), C.FOREST)
        for _ in range(7):    # 山地
            blob(rng.uniform(3, w - 3), rng.uniform(3, h - 3), rng.uniform(1.5, 2.8), C.MOUNTAIN)
        for _ in range(2):    # 两个大湖
            blob(rng.uniform(6, w - 6), rng.uniform(5, h - 5), rng.uniform(3.5, 4.5), C.SEA)
        for _ in range(4):    # 几个小池塘
            blob(rng.uniform(2, w - 2), rng.uniform(2, h - 2), rng.uniform(1.2, 2), C.SEA)
        self.terrain = t

        # 矿点：散布在平原上，不靠水
        plains = [i for i in range(w * h) if t[i] == C.PLAIN and not self._near_sea(i % w, i // w)]
        rng.shuffle(plains)
        self.ore = set(plains[:16])

    def _near_sea(self, x: int, y: int) -> bool:
        return any(self.in_bounds(x + dx, y + dy) and self.terrain[self.idx(x + dx, y + dy)] == C.SEA
                   for dx, dy in DIRS8)

    def _find_spawn(self) -> Tuple[int, int]:
        """找一块好的基地地址：周围 5×5 都是平地或森林，没有矿，离其他基地远一点。"""
        hqs = [(b.x, b.y) for b in self.buildings.values() if b.kind == "hq"]

        def good(x: int, y: int, min_d: float) -> bool:
            if not self.in_bounds(x, y) or self.idx(x, y) in self.occ:
                return False
            if self.terrain[self.idx(x, y)] not in C.BUILDABLE or self.idx(x, y) in self.ore:
                return False
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if not self.in_bounds(x + dx, y + dy) or \
                       self.terrain[self.idx(x + dx, y + dy)] not in C.BUILDABLE:
                        return False
            return all(math.hypot(x - hx, y - hy) >= min_d for hx, hy in hqs)

        for min_d in (14, 9, 4, 0):
            for _ in range(3000):
                x, y = self.rng.randrange(self.w), self.rng.randrange(self.h)
                if good(x, y, min_d):
                    return x, y
        for y in range(self.h):   # 实在找不到就随便找一块空地
            for x in range(self.w):
                if self.in_bounds(x, y) and self.terrain[self.idx(x, y)] in C.BUILDABLE \
                   and self.idx(x, y) not in self.occ:
                    return x, y
        raise GameError("地图上已经没有空地了")

    # ------------------------------------------------------------ 实体的增删

    def _add_building(self, owner: int, kind: str, x: int, y: int) -> Building:
        cfg = C.BUILDINGS[kind]
        b = Building(self._new_id(), owner, kind, x, y, cfg["hp"], cfg["hp"])
        self.buildings[b.id] = b
        self.occ[self.idx(x, y)] = b.id
        return b

    def _add_unit(self, owner: int, kind: str, x: int, y: int) -> Unit:
        cfg = C.UNITS[kind]
        hp = cfg["hp"] * (1 + C.HP_PER_LEVEL * self.level(owner, cfg["cls"]))
        u = Unit(self._new_id(), owner, kind, x, y, hp, hp)
        self.units[u.id] = u
        return u

    def _remove_building(self, b: Building) -> None:
        if self.buildings.pop(b.id, None) is None:
            return
        self.occ.pop(self.idx(b.x, b.y), None)
        p = self.players.get(b.owner)
        if p is None:
            return
        if p.hq == b.id:
            p.hq = None
            # 基地被毁：正在搬迁的，取消搬迁并退款
            if p.relocating:
                p.gold += p.relocating["cost"]
                p.relocating = None

    def _found_base(self, p: Player, gold: float = 0) -> None:
        x, y = self._find_spawn()
        hq = self._add_building(p.id, "hq", x, y)
        p.hq = hq.id
        p.gold += gold
        self._add_unit(p.id, "infantry", x, y)
        self._add_unit(p.id, "infantry", x, y)

    def join(self, pid: int, name: str) -> Player:
        p = self.players.get(pid)
        if p is None:
            color = C.PLAYER_COLORS[len(self.players) % len(C.PLAYER_COLORS)]
            p = Player(pid, name, color, float(C.START_GOLD),
                       {k: 0 for k in C.RESEARCH_CLASSES})
            self.players[pid] = p
            self._found_base(p)
            self._refresh_vision()
        else:
            p.name = name
        return p

    # ------------------------------------------------------------ 视野

    def _circle(self, sight: float) -> List[Tuple[int, int]]:
        if sight not in self._circles:
            r = int(math.ceil(sight))
            self._circles[sight] = [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1)
                                    if dx * dx + dy * dy <= sight * sight + 0.5]
        return self._circles[sight]

    def _refresh_vision(self) -> None:
        vis: Dict[int, Set[int]] = {pid: set() for pid in self.players}
        for e in itertools.chain(self.units.values(), self.buildings.values()):
            s = vis.get(e.owner)
            if s is None:
                continue
            for dx, dy in self._circle(cfg_of(e.kind)["sight"]):
                x, y = e.x + dx, e.y + dy
                if self.in_bounds(x, y):
                    s.add(self.idx(x, y))
        self.vis = vis
        for pid, p in self.players.items():
            p.explored |= vis[pid]

    def can_see(self, pid: int, x: int, y: int) -> bool:
        return self.idx(x, y) in self.vis.get(pid, ())

    # ------------------------------------------------------------ 寻路与移动

    def _can_enter(self, dom: str, mountain_ok: bool, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        i = self.idx(x, y)
        t = self.terrain[i]
        if dom == "air":
            return True
        if dom == "sea":
            return t == C.SEA
        # 陆地单位：不能下海，不能爬山（步兵除外），不能穿过建筑
        if t == C.SEA or (t == C.MOUNTAIN and not mountain_ok) or i in self.occ:
            return False
        return True

    def _path(self, u: Unit, pred) -> Optional[List[Tuple[int, int]]]:
        """广度优先搜索：从单位当前位置走到满足 pred 的格子。返回不含起点的路线，走不到返回 None。"""
        cfg = C.UNITS[u.kind]
        dom, mountain = cfg["domain"], cfg["mountain"]
        start = (u.x, u.y)
        if pred(start):
            return []
        prev: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
        q = deque([start])
        found = None
        while q and found is None:
            cx, cy = q.popleft()
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if n in prev or not self._can_enter(dom, mountain, *n):
                    continue
                prev[n] = (cx, cy)
                if pred(n):
                    found = n
                    break
                q.append(n)
        if found is None:
            return None
        path = []
        cur = found
        while cur != start:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return path

    def _in_range(self, u: Unit, tgt) -> bool:
        return math.hypot(tgt.x - u.x, tgt.y - u.y) <= C.UNITS[u.kind]["rng"] + 1e-9

    def _find_entity(self, eid: Optional[int]):
        if eid is None:
            return None
        return self.units.get(eid) or self.buildings.get(eid)

    def _update_order(self, u: Unit) -> None:
        """每回合检查单位的命令：到了就停，走不通就取消，攻击目标则靠近它。"""
        if u.order == "move":
            if (u.x, u.y) == u.dest:
                u.order, u.dest, u.path = None, None, []
            elif not u.path:
                dest = u.dest
                u.path = self._path(u, lambda t: t == dest) or []
                if not u.path:
                    u.order, u.dest = None, None
        elif u.order == "attack":
            tgt = self._find_entity(u.target)
            if tgt is None or tgt.owner == u.owner or not self.can_see(u.owner, tgt.x, tgt.y):
                u.order, u.target, u.path = None, None, []
            elif self._in_range(u, tgt):
                u.path = []          # 够得着就站住开火
            elif not u.path:
                rng = C.UNITS[u.kind]["rng"]
                u.path = self._path(u, lambda t: math.hypot(t[0] - tgt.x, t[1] - tgt.y) <= rng + 1e-9) or []
                if not u.path:
                    u.order, u.target = None, None

    def _move(self, u: Unit) -> None:
        if not u.path:
            u.acc = 0.0
            return
        dom, mountain = C.UNITS[u.kind]["domain"], C.UNITS[u.kind]["mountain"]
        u.acc += C.UNITS[u.kind]["speed"]
        while u.path and u.acc >= 1:
            nx, ny = u.path[0]
            if not self._can_enter(dom, mountain, nx, ny):
                u.path = []           # 路被挡住了，下一回合重新找路
                u.acc = 0.0
                return
            u.x, u.y = nx, ny
            u.path.pop(0)
            u.acc -= 1
        if not u.path:
            u.acc = 0.0

    # ------------------------------------------------------------ 经济与生产

    def mines_of(self, pid: int) -> int:
        return sum(1 for b in self.buildings.values() if b.owner == pid and b.kind == "mine")

    def income(self, pid: int) -> int:
        p = self.players[pid]
        return (C.HQ_INCOME if p.hq else 0) + C.MINE_INCOME * self.mines_of(pid)

    def _economy(self) -> None:
        mines: Dict[int, int] = {}
        for b in self.buildings.values():
            if b.kind == "mine":
                mines[b.owner] = mines.get(b.owner, 0) + 1
        for p in self.players.values():
            p.gold += (C.HQ_INCOME if p.hq else 0) + C.MINE_INCOME * mines.get(p.id, 0)

    def _production(self) -> None:
        for b in list(self.buildings.values()):
            if not b.queue:
                continue
            head = b.queue[0]
            head[1] -= 1
            if head[1] > 0:
                continue
            b.queue.pop(0)
            kind = head[0]
            if C.UNITS[kind]["domain"] == "sea":
                # 航母要从港口旁边的海里下水
                spot = next(((b.x + dx, b.y + dy) for dx, dy in DIRS8
                             if self.in_bounds(b.x + dx, b.y + dy)
                             and self.terrain[self.idx(b.x + dx, b.y + dy)] == C.SEA), None)
                if spot is None:
                    b.queue.insert(0, [kind, 1, head[2]])   # 旁边没海，等一等（一般不会发生）
                    continue
                self._add_unit(b.owner, kind, *spot)
            else:
                self._add_unit(b.owner, kind, b.x, b.y)

    def _relocations(self) -> None:
        for p in list(self.players.values()):
            r = p.relocating
            if r and self.tick_count >= r["done"]:
                p.relocating = None
                ok = (self.in_bounds(r["x"], r["y"]) and self.idx(r["x"], r["y"]) not in self.occ
                      and self.terrain[self.idx(r["x"], r["y"])] in C.BUILDABLE)
                if not ok:
                    p.gold += r["cost"]          # 目标已经被占了：退款，基地不动
                    continue
                old = self.buildings.get(p.hq) if p.hq else None
                if old:
                    self._remove_building(old)
                hq = self._add_building(p.id, "hq", r["x"], r["y"])
                p.hq = hq.id

    # ------------------------------------------------------------ 战斗

    def _combat(self) -> None:
        for e in list(itertools.chain(self.units.values(), self.buildings.values())):
            cfg = cfg_of(e.kind)
            if cfg["atk"] <= 0 or cfg["rng"] <= 0:
                continue
            if e.cool > 0:
                e.cool -= 1
                continue
            doms = cfg.get("targets", ())
            cls = cfg.get("cls")
            tgt = None
            if isinstance(e, Unit) and e.order == "attack":
                t = self._find_entity(e.target)
                if t is not None and self.is_enemy(e.owner, t.owner) and domain_of(t) in doms \
                   and math.hypot(t.x - e.x, t.y - e.y) <= cfg["rng"] + 1e-9:
                    tgt = t
            if tgt is None:
                best = None
                for t in itertools.chain(self.units.values(), self.buildings.values()):
                    if not self.is_enemy(e.owner, t.owner) or domain_of(t) not in doms:
                        continue
                    d = math.hypot(t.x - e.x, t.y - e.y)
                    if d <= cfg["rng"] + 1e-9 and (best is None or d < best[0]):
                        best = (d, t)
                tgt = best[1] if best else None
            if tgt is None:
                continue
            dmg = cfg["atk"] * (1 + C.ATTACK_PER_LEVEL * self.level(e.owner, cls))
            tgt.hp -= dmg
            e.cool = max(0, cfg["cool"] - 1)

    def _cleanup(self) -> None:
        for u in [u for u in self.units.values() if u.hp <= 0]:
            del self.units[u.id]
        for b in [b for b in self.buildings.values() if b.hp <= 0]:
            self._remove_building(b)

    # ------------------------------------------------------------ 推进时间

    def step(self) -> None:
        """推进一个回合。"""
        self.tick_count += 1
        self._economy()
        self._production()
        self._relocations()
        for u in list(self.units.values()):
            if u.id in self.units:
                self._update_order(u)
                self._move(u)
        self._combat()
        self._cleanup()
        self._refresh_vision()

    def advance_to(self, now: float) -> None:
        """服务器每次收到请求时调用：按真实时间推进游戏。没人请求时世界不动。"""
        if self.last_t is None:
            self.last_t = now
            return
        n = int((now - self.last_t) / C.TICK)
        if n <= 0:
            return
        if n > C.MAX_TICKS_PER_CALL:
            n = C.MAX_TICKS_PER_CALL
            self.last_t = now
        else:
            self.last_t += n * C.TICK
        for _ in range(n):
            self.step()

    # ------------------------------------------------------------ 玩家的操作

    def command(self, pid: int, action: str, a: dict) -> None:
        p = self.players.get(pid)
        if p is None:
            raise GameError("请先进入游戏")
        handlers = {
            "move": self._cmd_move, "attack": self._cmd_attack, "build": self._cmd_build,
            "train": self._cmd_train, "cancel": self._cmd_cancel, "research": self._cmd_research,
            "relocate": self._cmd_relocate, "respawn": self._cmd_respawn,
        }
        if action not in handlers:
            raise GameError("未知的操作")
        handlers[action](p, a)
        self._refresh_vision()

    def _int(self, a: dict, key: str) -> int:
        try:
            return int(a[key])
        except (KeyError, TypeError, ValueError):
            raise GameError(f"缺少或错误的参数：{key}")

    def _own_units(self, p: Player, a: dict) -> List[Unit]:
        ids = a.get("units") or []
        if not isinstance(ids, list):
            raise GameError("请选择单位")
        units = []
        for i in ids:
            u = self.units.get(i) if isinstance(i, int) else None
            if u and u.owner == p.id:
                units.append(u)
        if not units:
            raise GameError("请先选中自己的单位")
        return units

    def _cmd_move(self, p: Player, a: dict) -> None:
        x, y = self._int(a, "x"), self._int(a, "y")
        if not self.in_bounds(x, y):
            raise GameError("目的地不在地图上")
        ok = 0
        for u in self._own_units(p, a):
            path = self._path(u, lambda t: t == (x, y))
            if path is None:
                continue
            u.order, u.dest, u.target, u.path = "move", (x, y), None, path
            ok += 1
        if not ok:
            raise GameError("选中的单位都到不了那里")

    def _cmd_attack(self, p: Player, a: dict) -> None:
        tid = self._int(a, "target")
        tgt = self._find_entity(tid)
        if tgt is None or tgt.owner == p.id:
            raise GameError("目标不存在")
        if not self.can_see(p.id, tgt.x, tgt.y):
            raise GameError("看不见这个目标，先派侦察机去看看")
        ok = 0
        for u in self._own_units(p, a):
            if C.UNITS[u.kind]["targets"] and domain_of(tgt) in C.UNITS[u.kind]["targets"]:
                u.order, u.target, u.dest, u.path = "attack", tid, None, []
                ok += 1
        if not ok:
            raise GameError("选中的单位打不到它")

    def _cmd_build(self, p: Player, a: dict) -> None:
        kind = a.get("kind")
        if kind not in C.BUILDINGS or kind == "hq":
            raise GameError("不能建造这个")
        cfg = C.BUILDINGS[kind]
        x, y = self._int(a, "x"), self._int(a, "y")
        if not self.in_bounds(x, y):
            raise GameError("这里不在地图上")
        i = self.idx(x, y)
        if self.terrain[i] not in C.BUILDABLE or i in self.occ:
            raise GameError("这里不能建造")
        if cfg["ore"] and i not in self.ore:
            raise GameError("矿场必须建在矿点上")
        if cfg["shore"] and not self._near_sea(x, y):
            raise GameError("港口必须建在海边")
        mine = [b for b in self.buildings.values() if b.owner == p.id]
        if cfg["requires"] and not any(b.kind == cfg["requires"] for b in mine):
            raise GameError(f"需要先建造{C.BUILDINGS[cfg['requires']]['name']}")
        if not any(max(abs(b.x - x), abs(b.y - y)) <= C.BUILD_RANGE for b in mine):
            raise GameError("只能建在自己的基地或建筑附近")
        if p.gold < cfg["cost"]:
            raise GameError("金币不够")
        p.gold -= cfg["cost"]
        self._add_building(p.id, kind, x, y)

    def _own_building(self, p: Player, a: dict) -> Building:
        b = self.buildings.get(self._int(a, "building"))
        if b is None or b.owner != p.id:
            raise GameError("这不是你的建筑")
        return b

    def _cmd_train(self, p: Player, a: dict) -> None:
        b = self._own_building(p, a)
        kind = a.get("kind")
        if kind not in C.BUILDINGS[b.kind]["produces"]:
            raise GameError("这座建筑造不出这个单位")
        cfg = C.UNITS[kind]
        if len(b.queue) >= C.QUEUE_MAX:
            raise GameError("队列满了")
        if p.gold < cfg["cost"]:
            raise GameError("金币不够")
        p.gold -= cfg["cost"]
        b.queue.append([kind, cfg["time"], cfg["time"]])

    def _cmd_cancel(self, p: Player, a: dict) -> None:
        b = self._own_building(p, a)
        idx = self._int(a, "index")
        if not 0 <= idx < len(b.queue):
            raise GameError("没有这个队列项")
        kind = b.queue.pop(idx)[0]
        p.gold += C.UNITS[kind]["cost"]          # 取消全额退款

    def _cmd_research(self, p: Player, a: dict) -> None:
        cls = a.get("cls")
        if cls not in C.RESEARCH_CLASSES:
            raise GameError("没有这个研究")
        if not p.hq:
            raise GameError("基地被毁，不能研究")
        lvl = p.research[cls]
        if lvl >= C.RESEARCH_MAX:
            raise GameError("已经满级了")
        cost = C.RESEARCH_COSTS[lvl]
        if p.gold < cost:
            raise GameError("金币不够")
        p.gold -= cost
        p.research[cls] = lvl + 1
        # 已经造好的同类单位，生命上限也跟着涨
        factor = (1 + C.HP_PER_LEVEL * (lvl + 1)) / (1 + C.HP_PER_LEVEL * lvl)
        for u in self.units.values():
            if u.owner == p.id and C.UNITS[u.kind]["cls"] == cls:
                u.maxhp *= factor
                u.hp *= factor

    def _cmd_relocate(self, p: Player, a: dict) -> None:
        x, y = self._int(a, "x"), self._int(a, "y")
        if not p.hq:
            raise GameError("基地被毁了，请先重建基地")
        if p.relocating:
            raise GameError("已经在搬迁中")
        if self.tick_count < p.relocate_ready:
            raise GameError(f"搬迁冷却中，还需 {p.relocate_ready - self.tick_count} 秒")
        if not self.in_bounds(x, y):
            raise GameError("目的地不在地图上")
        i = self.idx(x, y)
        if self.terrain[i] not in C.BUILDABLE or i in self.occ:
            raise GameError("目的地不能建基地")
        hq = self.buildings[p.hq]
        dist = math.hypot(x - hq.x, y - hq.y)
        if dist < 1:
            raise GameError("已经在这里了")
        cost = int(C.RELOCATE_BASE + C.RELOCATE_PER_TILE * dist)
        if p.gold < cost:
            raise GameError(f"搬迁需要 {cost} 金币")
        p.gold -= cost
        p.relocating = {"x": x, "y": y, "cost": cost, "done": self.tick_count + C.RELOCATE_TIME}
        p.relocate_ready = self.tick_count + C.RELOCATE_COOLDOWN

    def _cmd_respawn(self, p: Player, a: dict) -> None:
        if p.hq:
            raise GameError("基地还在，不需要重建")
        self._found_base(p, gold=C.RESPAWN_GOLD)

    # ------------------------------------------------------------ 发给客户端的数据

    def view(self, pid: int) -> dict:
        """玩家自己能看到的世界。看不见的敌方单位、建筑一律不发。"""
        p = self.players[pid]
        vis = self.vis.get(pid, set())
        n = self.w * self.h
        terrain = "".join(self.terrain[i] if i in p.explored else "?" for i in range(n))
        visible = "".join("1" if i in vis else "0" for i in range(n))
        ore = sorted(i for i in self.ore if i in p.explored)

        units = []
        for u in self.units.values():
            if u.owner != pid and self.idx(u.x, u.y) not in vis:
                continue
            units.append({"id": u.id, "owner": u.owner, "kind": u.kind, "x": u.x, "y": u.y,
                          "hp": round(u.hp), "maxhp": round(u.maxhp),
                          "order": u.order, "mine": u.owner == pid})
        buildings = []
        for b in self.buildings.values():
            if b.owner != pid and self.idx(b.x, b.y) not in vis:
                continue
            item = {"id": b.id, "owner": b.owner, "kind": b.kind, "x": b.x, "y": b.y,
                    "hp": round(b.hp), "maxhp": round(b.maxhp), "mine": b.owner == pid}
            if b.owner == pid:
                item["queue"] = [{"kind": q[0], "left": q[1], "total": q[2]} for q in b.queue]
            buildings.append(item)

        hq = self.buildings.get(p.hq) if p.hq else None
        reloc = None
        if p.relocating:
            r = p.relocating
            reloc = {"x": r["x"], "y": r["y"], "left": max(0, r["done"] - self.tick_count)}
        research = {}
        for cls in C.RESEARCH_CLASSES:
            lvl = p.research[cls]
            research[cls] = {"level": lvl,
                             "nextCost": C.RESEARCH_COSTS[lvl] if lvl < C.RESEARCH_MAX else None}

        return {
            "tick": self.tick_count,
            "w": self.w, "h": self.h,
            "terrain": terrain, "visible": visible, "ore": ore,
            "me": {"id": p.id, "name": p.name, "color": p.color, "gold": int(p.gold),
                   "income": self.income(pid),
                   "hq": [hq.x, hq.y] if hq else None,
                   "relocating": reloc,
                   "relocateReady": max(0, p.relocate_ready - self.tick_count),
                   "research": research},
            "players": [{"id": q.id, "name": q.name, "color": q.color, "hasHq": q.hq is not None}
                        for q in self.players.values()],
            "units": units,
            "buildings": buildings,
        }


CATALOG = {
    "units": C.UNITS,
    "buildings": C.BUILDINGS,
    "research": C.RESEARCH_CLASSES,
    "researchCosts": list(C.RESEARCH_COSTS),
    "researchMax": C.RESEARCH_MAX,
    "queueMax": C.QUEUE_MAX,
    "relocate": {"base": C.RELOCATE_BASE, "perTile": C.RELOCATE_PER_TILE,
                 "time": C.RELOCATE_TIME, "cooldown": C.RELOCATE_COOLDOWN},
}
