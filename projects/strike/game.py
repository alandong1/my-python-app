"""突击行动的游戏逻辑：移动、碰撞、射线、开火、死亡和复活。

这里是纯逻辑，不依赖 WebSocket，方便写单元测试。
服务器是唯一的裁判；static/game.js 里的 move() 与这里的 move() 保持一致，用于客户端预测。
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from . import config as C

Vec = Tuple[float, float, float]


def blocked(x: float, z: float, walls=C.WALLS) -> bool:
    """玩家（半径 PLAYER_RADIUS 的圆，按方形近似）在 (x, z) 处是否和障碍物重叠。"""
    r = C.PLAYER_RADIUS
    for x0, _y0, z0, x1, _y1, z1 in walls:
        if x + r > x0 and x - r < x1 and z + r > z0 and z - r < z1:
            return True
    return False


def move(x: float, z: float, fwd: float, side: float, yaw: float, dt: float, walls=C.WALLS) -> Tuple[float, float]:
    """按输入移动一小段时间，返回新的 (x, z)。

    fwd：前进（+1）/ 后退（-1）；side：向右（+1）/ 向左（-1）；yaw：朝向（弧度）。
    先沿 x 移动、再沿 z 移动，撞到障碍物的那个方向就不动，所以贴着墙走也能滑动。
    """
    dt = min(max(dt, 0.0), C.MAX_DT)
    fwd = min(max(fwd, -1.0), 1.0)
    side = min(max(side, -1.0), 1.0)
    m = math.hypot(fwd, side)
    if m > 1.0:
        fwd /= m
        side /= m
    s, c = math.sin(yaw), math.cos(yaw)
    fx, fz = -s, -c          # 朝向前方的单位向量（yaw=0 时朝 -z，和 Three.js 的默认方向一致）
    rx, rz = c, -s           # 朝向右边的单位向量
    step = C.MOVE_SPEED * dt
    dx = (fx * fwd + rx * side) * step
    dz = (fz * fwd + rz * side) * step
    bound = C.ARENA_HALF - C.PLAYER_RADIUS
    nx = min(max(x + dx, -bound), bound)
    if not blocked(nx, z, walls):
        x = nx
    nz = min(max(z + dz, -bound), bound)
    if not blocked(x, nz, walls):
        z = nz
    return x, z


def direction(yaw: float, pitch: float) -> Vec:
    """视线方向的单位向量。pitch 为正时抬头。"""
    cp = math.cos(pitch)
    return (-math.sin(yaw) * cp, math.sin(pitch), -math.cos(yaw) * cp)


def ray_box(o: Vec, d: Vec, lo: Vec, hi: Vec) -> Optional[float]:
    """射线 o + d·t 进入轴对齐箱子 [lo, hi] 的距离 t；不相交返回 None。origin 在箱子里时返回 0。"""
    tmin, tmax = 0.0, math.inf
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if o[i] < lo[i] or o[i] > hi[i]:
                return None
            continue
        t1 = (lo[i] - o[i]) / d[i]
        t2 = (hi[i] - o[i]) / d[i]
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin


@dataclass
class Player:
    id: int
    name: str
    x: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    hp: int = C.MAX_HP
    alive: bool = True
    respawn_at: float = 0.0
    kills: int = 0
    deaths: int = 0
    ack: int = 0             # 服务器已经处理到的最大输入编号（客户端据此做预测对齐）
    last_fire: float = -1e9
    last_input: float = 0.0
    budget: float = 0.1      # 移动时间预算（秒）


class Arena:
    """一个竞技场（房间）。所有方法都是同步的，只在服务器的事件循环里调用，不需要加锁。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic, rng: Optional[random.Random] = None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.players: Dict[int, Player] = {}
        self.events: List[dict] = []
        self._next_id = 1

    # ---- 进出房间

    def add_player(self, name: str) -> Player:
        if len(self.players) >= C.MAX_PLAYERS:
            raise ValueError("房间已满")
        now = self.clock()
        p = Player(id=self._next_id, name=name, last_input=now)
        self._next_id += 1
        self.players[p.id] = p
        self.spawn(p)
        return p

    def remove_player(self, pid: int) -> None:
        self.players.pop(pid, None)

    # ---- 出生与复活

    def spawn(self, p: Player) -> None:
        """挑一个离其他活人最远的出生点（同样远的话随机选），血量回满。"""
        others = [q for q in self.players.values() if q is not p and q.alive]
        order = list(C.SPAWNS)
        self.rng.shuffle(order)
        best, best_score = order[0], -1.0
        for sx, sz in order:
            score = min((math.hypot(sx - q.x, sz - q.z) for q in others), default=math.inf)
            if score > best_score:
                best, best_score = (sx, sz), score
        p.x, p.z = float(best[0]), float(best[1])
        p.hp = C.MAX_HP
        p.alive = True
        p.yaw = 0.0
        p.pitch = 0.0

    def tick(self) -> None:
        """每个广播周期调用一次：到时间的死人复活。"""
        now = self.clock()
        for p in self.players.values():
            if not p.alive and now >= p.respawn_at:
                self.spawn(p)

    # ---- 玩家操作

    def input(self, pid: int, seq: int, fwd: float, side: float, yaw: float, pitch: float, dt: float) -> None:
        p = self.players.get(pid)
        if p is None or seq <= p.ack:
            return  # 玩家不存在，或者是重复 / 乱序的旧输入
        now = self.clock()
        # 移动时间预算：按真实经过的时间攒，发消息再快也不能超出真实时间。
        p.budget = min(p.budget + max(now - p.last_input, 0.0), C.MAX_INPUT_BUDGET)
        p.last_input = now
        dt = min(max(dt, 0.0), p.budget)
        p.budget -= dt
        p.ack = seq
        p.yaw = yaw
        p.pitch = min(max(pitch, -C.MAX_PITCH), C.MAX_PITCH)
        if not p.alive:
            return
        p.x, p.z = move(p.x, p.z, fwd, side, p.yaw, dt)

    def fire(self, pid: int) -> None:
        p = self.players.get(pid)
        if p is None or not p.alive:
            return
        now = self.clock()
        if now - p.last_fire < C.FIRE_INTERVAL:
            return
        p.last_fire = now

        origin: Vec = (p.x, C.EYE_HEIGHT, p.z)
        d = direction(p.yaw, p.pitch)

        # 先算子弹能飞多远：墙、箱子、地面和射程
        reach = C.MAX_RANGE
        for x0, y0, z0, x1, y1, z1 in C.WALLS:
            t = ray_box(origin, d, (x0, y0, z0), (x1, y1, z1))
            if t is not None and t < reach:
                reach = t
        if d[1] < 0:
            reach = min(reach, -origin[1] / d[1])

        # 再看子弹能不能打到人：离枪口最近的那个活人
        target: Optional[Player] = None
        hit_t = reach
        for q in self.players.values():
            if q is p or not q.alive:
                continue
            r = C.PLAYER_RADIUS
            t = ray_box(origin, d, (q.x - r, 0.0, q.z - r), (q.x + r, C.PLAYER_HEIGHT, q.z + r))
            if t is not None and t <= reach and (target is None or t < hit_t):
                target, hit_t = q, t

        end = (origin[0] + d[0] * hit_t, origin[1] + d[1] * hit_t, origin[2] + d[2] * hit_t)
        self.events.append({"e": "shot", "by": p.id, "from": _r(origin), "to": _r(end)})
        if target is None:
            return
        head = end[1] >= C.HEAD_HEIGHT
        dmg = C.HEAD_DAMAGE if head else C.BODY_DAMAGE
        target.hp = max(target.hp - dmg, 0)
        self.events.append({"e": "hit", "by": p.id, "to": target.id, "dmg": dmg, "head": head})
        if target.hp <= 0:
            self._die(target, p, head, now)

    def _die(self, victim: Player, killer: Player, head: bool, now: float) -> None:
        victim.alive = False
        victim.deaths += 1
        victim.respawn_at = now + C.RESPAWN_SECONDS
        killer.kills += 1
        self.events.append({"e": "kill", "by": killer.id, "to": victim.id, "head": head})

    # ---- 给客户端的数据

    def take_events(self) -> List[dict]:
        events, self.events = self.events, []
        return events

    def roster(self) -> List[dict]:
        return [
            {"id": p.id, "name": p.name, "x": round(p.x, 3), "z": round(p.z, 3),
             "yaw": round(p.yaw, 4), "pitch": round(p.pitch, 4), "hp": p.hp, "alive": p.alive,
             "kills": p.kills, "deaths": p.deaths}
            for p in self.players.values()
        ]

    def you(self, pid: int) -> Optional[dict]:
        p = self.players.get(pid)
        if p is None:
            return None
        now = self.clock()
        return {"x": round(p.x, 3), "z": round(p.z, 3), "hp": p.hp, "alive": p.alive, "ack": p.ack,
                "respawn_in": round(max(p.respawn_at - now, 0.0), 2) if not p.alive else 0.0,
                "kills": p.kills, "deaths": p.deaths}


def _r(v: Vec) -> List[float]:
    return [round(v[0], 3), round(v[1], 3), round(v[2], 3)]
