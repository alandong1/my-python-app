"""突击行动的游戏逻辑：移动、碰撞、射线、武器、金钱、狙击镜、两队、电脑玩家、开火、死亡和复活。

这里是纯逻辑，不依赖 WebSocket，方便写单元测试。
服务器是唯一的裁判；static/game.js 里的 move() 与这里的 move() 保持一致，用于客户端预测。
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import config as C

Vec = Tuple[float, float, float]
SLOTS = ("primary", "secondary")
BOT_PREFIX = "电脑"


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


def _default_slots() -> Dict[str, Optional[str]]:
    return {"primary": None, "secondary": C.DEFAULT_WEAPON}


def _angle_diff(a: float, b: float) -> float:
    """两个角度之间的最短差（结果在 -π 到 π 之间）。"""
    return (b - a + math.pi) % (2 * math.pi) - math.pi


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
    money: int = C.START_MONEY
    slots: Dict[str, Optional[str]] = field(default_factory=_default_slots)   # 主武器 / 副武器
    active: str = "secondary"                                                  # 当前拿着哪个槽位
    scoped: bool = False                                                       # 是否开着狙击镜
    team: int = 0                                                              # 0 红队，1 蓝队
    is_bot: bool = False                                                       # 是不是电脑玩家
    bot_target: Optional[int] = None         # 电脑正在追击的敌人 id
    bot_seen_since: float = 0.0              # 什么时候第一次看到这个敌人
    bot_wp: Optional[Tuple[float, float]] = None   # 电脑巡逻的目标点
    bot_wp_until: float = 0.0                # 巡逻目标最晚到什么时候换

    def weapon(self) -> dict:
        return C.WEAPONS[self.slots[self.active] or C.DEFAULT_WEAPON]


class Arena:
    """一个竞技场（房间）。所有方法都是同步的，只在服务器的事件循环里调用，不需要加锁。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic, rng: Optional[random.Random] = None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.players: Dict[int, Player] = {}
        self.events: List[dict] = []
        self.team_kills = [0, 0]          # 两队的击杀数
        self._next_id = 1
        self._bot_count = 0
        self._last_tick: Optional[float] = None

    # ---- 进出房间

    def _pick_team(self) -> int:
        """分到人少的那一队；人数一样多时分到红队（0）。"""
        counts = [0, 0]
        for p in self.players.values():
            counts[p.team] += 1
        return 0 if counts[0] <= counts[1] else 1

    def add_player(self, name: str) -> Player:
        if len(self.players) >= C.MAX_PLAYERS:
            raise ValueError("房间已满")
        now = self.clock()
        p = Player(id=self._next_id, name=name, last_input=now, team=self._pick_team())
        self._next_id += 1
        self.players[p.id] = p
        self.spawn(p)
        return p

    def add_bot(self) -> Player:
        self._bot_count += 1
        now = self.clock()
        p = Player(id=self._next_id, name=f"{BOT_PREFIX}{self._bot_count}", last_input=now,
                   team=self._pick_team(), is_bot=True)
        self._next_id += 1
        self.players[p.id] = p
        self.spawn(p)
        return p

    def remove_player(self, pid: int) -> None:
        self.players.pop(pid, None)

    def human_count(self) -> int:
        return sum(1 for p in self.players.values() if not p.is_bot)

    def balance_bots(self) -> None:
        """让「人类玩家 + 电脑」至少有 MIN_ONLINE 人：不够就加电脑，多了就踢掉电脑（优先踢人多的那一队的）。"""
        target = max(0, C.MIN_ONLINE - self.human_count())
        bots = [p for p in self.players.values() if p.is_bot]
        while len(bots) < target:
            bots.append(self.add_bot())
        while len(bots) > target:
            counts = [0, 0]
            for b in bots:
                counts[b.team] += 1
            team = 0 if counts[0] >= counts[1] else 1
            victim = max((b for b in bots if b.team == team), key=lambda b: b.id)
            bots.remove(victim)
            self.remove_player(victim.id)

    # ---- 出生与复活

    def spawn(self, p: Player) -> None:
        """挑一个离其他活的敌人最远的出生点（同样远的话随机选），血量回满。"""
        others = [q for q in self.players.values() if q is not p and q.alive and q.team != p.team]
        if not others:
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
        p.bot_target = None
        p.bot_wp = None

    def tick(self) -> None:
        """每个广播周期调用一次：复活到期的人，然后让电脑玩家思考和行动。"""
        now = self.clock()
        dt = 0.0 if self._last_tick is None else min(max(now - self._last_tick, 0.0), C.MAX_DT)
        self._last_tick = now
        for p in self.players.values():
            if not p.alive and now >= p.respawn_at:
                self.spawn(p)
        for p in list(self.players.values()):
            if p.is_bot and p.alive:
                self._bot_think(p, now, dt)

    # ---- 玩家操作

    def input(self, pid: int, seq: int, fwd: float, side: float, yaw: float, pitch: float, dt: float) -> None:
        p = self.players.get(pid)
        if p is None or seq <= p.ack or p.is_bot:
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

    def equip(self, pid: int, slot: str) -> None:
        """切换到主武器或副武器（只能切到自己有的武器）。切换时狙击镜会关闭。"""
        p = self.players.get(pid)
        if p is None or slot not in SLOTS or p.slots[slot] is None:
            return
        p.active = slot
        p.scoped = False

    def set_scope(self, pid: int, on: bool) -> None:
        """开 / 关狙击镜。只有带镜的武器才能开；开镜后散布变小。"""
        p = self.players.get(pid)
        if p is None:
            return
        p.scoped = bool(on) and p.alive and p.weapon()["zoom"] > 0

    def buy(self, pid: int, weapon_id: str) -> bool:
        """买一把武器，自动装备到它所在的槽位（替换掉那个槽位原来的武器）。
        只能在活着的时候买；手枪是免费的默认武器，不能买。"""
        p = self.players.get(pid)
        if p is None or not p.alive or p.is_bot:
            return False
        w = C.WEAPONS.get(weapon_id)
        if w is None or w["price"] <= 0:
            return False
        slot = w["slot"]
        if p.slots[slot] == weapon_id or p.money < w["price"]:
            return False
        p.money -= w["price"]
        p.slots[slot] = weapon_id
        p.active = slot
        p.scoped = False
        return True

    def fire(self, pid: int, extra_spread: float = 0.0) -> None:
        p = self.players.get(pid)
        if p is None or not p.alive:
            return
        w = p.weapon()
        now = self.clock()
        if now - p.last_fire < w["interval"]:
            return
        p.last_fire = now

        # 散布：每次开火在朝向上随机偏一点（开镜时只有十分之一）；电脑玩家还会有额外的偏差
        spread = w["spread"] * (0.1 if p.scoped else 1.0) + extra_spread
        yaw = p.yaw + self.rng.uniform(-spread, spread)
        pitch = p.pitch + self.rng.uniform(-spread, spread)
        origin: Vec = (p.x, C.EYE_HEIGHT, p.z)
        d = direction(yaw, pitch)

        # 先算子弹能飞多远：墙、箱子、地面和射程
        reach = C.MAX_RANGE
        for x0, y0, z0, x1, y1, z1 in C.WALLS:
            t = ray_box(origin, d, (x0, y0, z0), (x1, y1, z1))
            if t is not None and t < reach:
                reach = t
        if d[1] < 0:
            reach = min(reach, -origin[1] / d[1])

        # 再看子弹能不能打到人：离枪口最近的那个敌人（队友不会挡住子弹，也不会被打中）
        target: Optional[Player] = None
        hit_t = reach
        for q in self.players.values():
            if q is p or not q.alive or q.team == p.team:
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
        dmg = w["head"] if head else w["body"]
        target.hp = max(target.hp - dmg, 0)
        self.events.append({"e": "hit", "by": p.id, "to": target.id, "dmg": dmg, "head": head})
        if target.hp <= 0:
            self._die(target, p, head, now)

    def _die(self, victim: Player, killer: Player, head: bool, now: float) -> None:
        victim.alive = False
        victim.deaths += 1
        victim.respawn_at = now + C.RESPAWN_SECONDS
        victim.slots = _default_slots()     # 死了就只剩手枪，钱保留
        victim.active = "secondary"
        victim.scoped = False
        killer.kills += 1
        killer.money = min(C.MAX_MONEY, killer.money + C.KILL_REWARD)
        self.team_kills[killer.team] += 1
        self.events.append({"e": "kill", "by": killer.id, "to": victim.id, "head": head})

    # ---- 电脑玩家的简单 AI

    def _clear_line(self, a: Vec, b: Vec) -> bool:
        """从 a 到 b 的直线上有没有墙或箱子挡着。"""
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-9:
            return True
        d = (dx / length, dy / length, dz / length)
        for x0, y0, z0, x1, y1, z1 in C.WALLS:
            t = ray_box(a, d, (x0, y0, z0), (x1, y1, z1))
            if t is not None and t < length:
                return False
        return True

    def _turn(self, cur: float, want: float, dt: float) -> float:
        """慢慢转向目标角度（不会一下子转过去，人看起来也更自然）。"""
        diff = _angle_diff(cur, want)
        step = min(max(diff, -C.BOT_TURN * dt), C.BOT_TURN * dt)
        return cur + step

    def _random_point(self) -> Tuple[float, float]:
        bound = C.ARENA_HALF - 3.0
        for _ in range(30):
            x = self.rng.uniform(-bound, bound)
            z = self.rng.uniform(-bound, bound)
            if not blocked(x, z):
                return x, z
        return 0.0, 0.0

    def _bot_think(self, p: Player, now: float, dt: float) -> None:
        """电脑玩家每个周期做一次决定：看得到敌人就追击并射击，看不到就四处巡逻。"""
        eye: Vec = (p.x, C.EYE_HEIGHT, p.z)
        target: Optional[Player] = None
        best = C.BOT_SIGHT
        for q in self.players.values():
            if q is p or not q.alive or q.team == p.team:
                continue
            dist = math.hypot(q.x - p.x, q.z - p.z)
            if dist >= best:
                continue
            if self._clear_line(eye, (q.x, 1.0, q.z)):    # 瞄准身体中间（约 1 米高）
                target, best = q, dist

        if target is not None:
            if p.bot_target != target.id:
                p.bot_target = target.id
                p.bot_seen_since = now
            dx, dz = target.x - p.x, target.z - p.z
            want_yaw = math.atan2(-dx, -dz)                       # 和 game.py 的朝向约定一致
            want_pitch = math.atan2(1.0 - C.EYE_HEIGHT, math.hypot(dx, dz))
            p.yaw = self._turn(p.yaw, want_yaw, dt)
            p.pitch = min(max(self._turn(p.pitch, want_pitch, dt), -C.MAX_PITCH), C.MAX_PITCH)
            # 远了就靠近，近了就后退，同时左右走动（不站着当靶子）
            fwd = 0.7 if best > 14 else (-0.4 if best < 6 else 0.0)
            side = math.sin(now * 1.7 + p.id) * 0.8
            p.x, p.z = move(p.x, p.z, fwd, side, p.yaw, dt)
            aimed = abs(_angle_diff(p.yaw, want_yaw)) < 0.2 and abs(_angle_diff(p.pitch, want_pitch)) < 0.2
            if aimed and now - p.bot_seen_since >= C.BOT_REACTION and self.rng.random() < C.BOT_FIRE_CHANCE:
                self.fire(p.id, extra_spread=C.BOT_SPREAD)
            return

        # 看不到敌人：巡逻。走到目标点、或者目标点到期、或者被挡住了，就换一个目标点。
        p.bot_target = None
        if p.bot_wp is None or now >= p.bot_wp_until or math.hypot(p.bot_wp[0] - p.x, p.bot_wp[1] - p.z) < 1.0:
            p.bot_wp = self._random_point()
            p.bot_wp_until = now + 8.0
        wx, wz = p.bot_wp
        want_yaw = math.atan2(-(wx - p.x), -(wz - p.z))
        p.yaw = self._turn(p.yaw, want_yaw, dt)
        p.pitch = self._turn(p.pitch, 0.0, dt)
        before = (p.x, p.z)
        p.x, p.z = move(p.x, p.z, 1.0, 0.0, p.yaw, dt)
        if math.hypot(p.x - before[0], p.z - before[1]) < 0.2 * C.MOVE_SPEED * dt:
            p.bot_wp = None      # 撞墙了，下一次换个目标点

    # ---- 给客户端的数据

    def take_events(self) -> List[dict]:
        events, self.events = self.events, []
        return events

    def roster(self) -> List[dict]:
        return [
            {"id": p.id, "name": p.name, "team": p.team, "x": round(p.x, 3), "z": round(p.z, 3),
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
                "kills": p.kills, "deaths": p.deaths, "money": p.money,
                "slots": dict(p.slots), "active": p.active, "scoped": p.scoped, "team": p.team}


def _r(v: Vec) -> List[float]:
    return [round(v[0], 3), round(v[1], 3), round(v[2], 3)]
