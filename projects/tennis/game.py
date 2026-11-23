"""网球的游戏核心：球场、球的物理、计分、房间状态。

这里**不碰网络**，只做计算，所以可以直接用测试检查。服务器每秒模拟 30 次
（见 server.py 的 tick），前端只负责显示和发送按键。

坐标约定（米）：
  x：沿球场长度方向。队 0 在 x<0 一侧（底线在 x=-11.885），队 1 在 x>0 一侧。
  y：高度（地面 y=0）。
  z：横向（左右）。
"""
from __future__ import annotations

import math
import random
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------ 球场与常数

G = 9.8                    # 重力
COURT_HALF_LEN = 11.885    # 球场半长（底线到中线）
DOUBLES_HALF_W = 5.485     # 双打边线到中线
SINGLES_HALF_W = 4.115     # 单打边线到中线（也是发球区的宽度）
SERVICE_LINE_X = 6.4       # 发球线到球网
NET_H = 0.914              # 球网高度（中间）
NET_HALF_W = 6.4           # 球网半宽（超出的球不算下网）
REACH = 1.35               # 击球范围：球到人的水平距离（米）
REACH_MIN_Y, REACH_MAX_Y = -0.1, 2.8   # 球拍能够到的高度
SERVE_MIN_Y, SERVE_MAX_Y = 1.0, 3.2   # 发球时能击中的抛球高度（下落到腰部也还能发，给反应慢的人留时间）
SWING_COOLDOWN = 0.35      # 两次挥拍之间的冷却（秒）
PLAYER_SPEED = 5.0         # 人物移动速度（米/秒）
TOSS_VY = 5.2              # 抛球的向上速度
TOSS_Y = 1.2               # 抛球时球的高度（手的高度）
DRAG = 0.0008              # 空气阻力系数（很小，只让远处的球稍微变短）
MAGNUS_TOP = 0.15          # 上旋 / 下旋的效果强度
MAGNUS_SIDE = 0.10         # 侧旋的效果强度
BASE_SPEED = 27.0          # 普通击球的基准速度（米/秒）
SERVE_SPEED = 38.0         # 发球的基准速度（米/秒）
PHYSICS_SUBSTEPS = 4       # 每个 tick 里把球的运动分成几小步（防止穿过球网）
POINT_PAUSE = 2.2          # 每分之后的停顿（秒）
BALL_MAX_RANGE = 40.0      # 超过这个距离的球直接算出界

SERVE_ORDER = {2: [0, 1], 4: [0, 2, 1, 3]}   # 发球顺序（座位号）

AI_ID = -1                 # 电脑座位的「用户 id」（不会和真实用户重复）
AI_NAME = "电脑"
AI_SERVE_DELAY = 1.0       # 电脑发球方：进入发球状态后停多久再抛球（秒）
AI_MISS_WAIT = 0.6         # 电脑这次没去接球，之后多久再重新判断（秒）
AI_HIT_CHANCE = 0.85       # 电脑够到球时击球的概率（其余时间算失误）
AI_STROKES = [("flat", 40), ("top", 25), ("back", 15), ("side_l", 10), ("side_r", 10)]

# 球种：速度系数、上旋强度（-1 下旋 .. 1 上旋）、侧旋（-1 左 .. 1 右）、
# 落点深度（米，从网算起的目标距离）、过网最低高度
STROKES: Dict[str, dict] = {
    "flat":   dict(speed=1.00, top=0.0,  side=0.0,  depth=9.5,  clear=1.10, name="平击"),
    "top":    dict(speed=0.90, top=1.0,  side=0.0,  depth=10.8, clear=1.00, name="上旋"),
    "back":   dict(speed=0.65, top=-1.0, side=0.0,  depth=6.0,  clear=1.25, name="下旋"),
    "side_l": dict(speed=0.95, top=0.0,  side=-1.0, depth=9.0,  clear=1.10, name="侧旋（左）"),
    "side_r": dict(speed=0.95, top=0.0,  side=1.0,  depth=9.0,  clear=1.10, name="侧旋（右）"),
}
SERVE_CLEAR = 0.95


class RoomError(Exception):
    """玩家的操作不合法（给玩家看的中文提示）。"""


# ------------------------------------------------------------------ 球

@dataclass
class Ball:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    top: float = 0.0      # 上旋（正）/ 下旋（负）
    side: float = 0.0     # 侧旋：正 = 向右拐，负 = 向左拐
    grounded: bool = False  # 是否贴着地面（弹起后、滚动中）
    rolling_stop: bool = False  # 滚停了（只发出一次停止事件）

    def hold_at(self, x: float, y: float, z: float):
        self.x, self.y, self.z = x, y, z
        self.vx = self.vy = self.vz = 0.0
        self.top = self.side = 0.0
        self.grounded = False
        self.rolling_stop = False


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def in_court(x: float, z: float, singles: bool) -> bool:
    half_w = SINGLES_HALF_W if singles else DOUBLES_HALF_W
    return abs(x) <= COURT_HALF_LEN and abs(z) <= half_w


def in_service_box(x: float, z: float, receiver_sign: int, server_zside: int) -> bool:
    """发球必须落在对角的发球区里：接球方一侧、距网 0–6.4 米、对面的那一半。"""
    return (math.copysign(1, x) == receiver_sign and 0.3 <= abs(x) <= SERVICE_LINE_X
            and abs(z) <= SINGLES_HALF_W and math.copysign(1, z) == -server_zside)


def step_ball(ball: Ball, dt: float) -> List[Tuple[str, float, float]]:
    """让球运动 dt 秒（dt 很小）。返回发生的事件：[(类型, x, z)]。

    类型：'net' 下网、'bounce' 落地、'stop' 滚停、'far' 飞出很远。
    """
    events: List[Tuple[str, float, float]] = []
    if ball.rolling_stop:
        return events

    if not ball.grounded:
        prev_x, prev_y, prev_z = ball.x, ball.y, ball.z
        vh = math.hypot(ball.vx, ball.vz)
        vs = math.sqrt(ball.vx * ball.vx + ball.vy * ball.vy + ball.vz * ball.vz)
        ax = -DRAG * vs * ball.vx
        ay = -G - DRAG * vs * ball.vy - ball.top * MAGNUS_TOP * vh   # 上旋下压，下旋上托
        az = -DRAG * vs * ball.vz
        if vh > 0.01:   # 侧旋：沿运动方向右侧的方向拐弯
            rx, rz = -ball.vz / vh, ball.vx / vh
            push = ball.side * MAGNUS_SIDE * vh
            ax += rx * push
            az += rz * push
        ball.vx += ax * dt
        ball.vy += ay * dt
        ball.vz += az * dt
        ball.x += ball.vx * dt
        ball.y += ball.vy * dt
        ball.z += ball.vz * dt
        # 旋转会慢慢消失
        decay = math.exp(-0.05 * dt)
        ball.top *= decay
        ball.side *= decay

        # 过网检查：从一侧穿到另一侧时，看此时的高度
        if prev_x * ball.x < 0:
            t = prev_x / (prev_x - ball.x)
            y_cross = prev_y + (ball.y - prev_y) * t
            z_cross = prev_z + (ball.z - prev_z) * t
            if y_cross < NET_H and abs(z_cross) <= NET_HALF_W:
                events.append(("net", ball.x, ball.z))
                return events

        if abs(ball.x) > BALL_MAX_RANGE or abs(ball.z) > BALL_MAX_RANGE or ball.y > 30:
            events.append(("far", ball.x, ball.z))
            return events

        if ball.y <= 0:
            ball.y = 0.0
            ball.grounded = True
            if ball.vy < -0.8:          # 真正的弹起
                e = clamp(0.7 + 0.12 * ball.top, 0.5, 0.85)
                ball.vy = -ball.vy * e
                f = clamp(0.68 - 0.12 * ball.top, 0.5, 0.8)   # 落地后水平速度大减：上旋抓地快，下旋打滑远
                ball.vx *= f
                ball.vz *= f
                hv = math.hypot(ball.vx, ball.vz)
                if hv > 0.01:            # 侧旋在落地时把球推向一侧
                    ball.vx += -ball.vz / hv * ball.side * 0.8
                    ball.vz += ball.vx / hv * ball.side * 0.8
                ball.top *= 0.6
                ball.side *= 0.6
                ball.grounded = False     # 弹起后又在空中
            else:                        # 贴地滚动
                ball.vy = 0.0
            events.append(("bounce", ball.x, ball.z))
            return events
        return events

    # 贴地滚动：摩擦减速，停下后报一次
    ball.y = 0.0
    ball.vy = 0.0
    k = math.exp(-2.5 * dt)
    ball.vx *= k
    ball.vz *= k
    if math.hypot(ball.vx, ball.vz) < 0.4:
        ball.vx = ball.vz = 0.0
        ball.rolling_stop = True
        events.append(("stop", ball.x, ball.z))
    return events


def solve_launch(x0: float, y0: float, z0: float, tx: float, tz: float,
                 speed: float, clear: float, top: float = 0.0) -> Tuple[float, float, float]:
    """算出球的初速度：从 (x0,y0,z0) 出发，落在 (tx,tz)，过网时至少高出 clear 米。

    不考虑空气阻力（阻力很小）。上旋会让球下沉得更快：马格努斯效应和「水平速度」成正比，
    所以这里迭代一次，用水平速度算出有效重力，和 step_ball 保持一致。
    速度不够时会自动把球打得更高（飞行时间变长）。
    """
    dx = tx - x0
    dz = tz - z0
    dist = math.hypot(dx, dz)
    a = -x0 / dx if dx != 0 else 0.5           # 过网位置占全程的比例
    t_speed = dist / speed
    t = t_speed
    g = G
    for _ in range(4):
        vh = dist / t                            # 水平速度
        g = G + top * MAGNUS_TOP * vh            # 上旋 → 有效重力变大；下旋 → 变小
        t = t_speed
        # 过网高度 = (1-a) * (y0 + 0.5*g*a*T²)，T 越大越高，所以至少要让它 >= clear
        if 0 < a < 1:
            need = clear / (1 - a) - y0
            if need > 0:
                t = max(t, math.sqrt(need / (0.5 * g * a)))
    vx = dx / t
    vz = dz / t
    vy = (0.5 * g * t * t - y0) / t              # 在时间 t 时正好落回地面
    return vx, vy, vz


# ------------------------------------------------------------------ 计分

class Score:
    """标准网球计分：分 → 局 → 盘；6:6 进入抢七；三盘两胜。"""

    def __init__(self, best_of: int = 3):
        self.points = [0, 0]          # 当前这一局里的分（抢七时是抢七分）
        self.games = [0, 0]           # 当前这一盘里的局数
        self.sets_won = [0, 0]
        self.set_scores: List[Tuple[int, int]] = []
        self.tiebreak = False
        self.total_games = 0
        self.done = False
        self.winner: Optional[int] = None
        self.sets_to_win = best_of // 2 + 1

    def win_point(self, team: int) -> Tuple[bool, bool]:
        """记一分。返回 (这一分是否赢了一局, 是否赢了一盘)。"""
        if self.done:
            raise RoomError("比赛已经结束")
        other = 1 - team
        self.points[team] += 1
        a, b = self.points[team], self.points[other]
        need = 7 if self.tiebreak else 4          # 抢七先到 7 分，普通局先到 4 分
        if a >= need and a - b >= 2:
            return True, self._win_game(team)
        return False, False

    def _win_game(self, team: int) -> bool:
        """赢了一局。返回这一局是否同时结束了一盘。"""
        self.games[team] += 1
        self.total_games += 1
        self.points = [0, 0]
        if self.tiebreak:
            self._finish_set(team)
            return True
        g_me, g_other = self.games[team], self.games[1 - team]
        if g_me >= 6 and g_me - g_other >= 2:
            self._finish_set(team)
            return True
        if self.games[0] == 6 and self.games[1] == 6:
            self.tiebreak = True                   # 6:6 进入抢七
        return False

    def _finish_set(self, team: int):
        self.set_scores.append((self.games[0], self.games[1]))
        self.sets_won[team] += 1
        self.games = [0, 0]
        self.tiebreak = False
        if self.sets_won[team] >= self.sets_to_win:
            self.done = True
            self.winner = team

    def label(self, team: int) -> str:
        """给玩家看的本局比分：0 / 15 / 30 / 40 / Ad / 或抢七分数。"""
        a, b = self.points[team], self.points[1 - team]
        if self.tiebreak:
            return str(a)
        if a >= 3 and b >= 3:
            if a == b:
                return "40"
            return "Ad" if a > b else "40"
        return ["0", "15", "30", "40"][min(a, 3)]

    def is_deuce(self) -> bool:
        return not self.tiebreak and self.points[0] >= 3 and self.points[0] == self.points[1]

    def to_dict(self) -> dict:
        return {
            "labels": [self.label(0), self.label(1)],
            "games": list(self.games),
            "setsWon": list(self.sets_won),
            "sets": [list(s) for s in self.set_scores],
            "tiebreak": self.tiebreak,
            "deuce": self.is_deuce(),
            "done": self.done,
            "winner": self.winner,
        }


# ------------------------------------------------------------------ 房间

@dataclass
class Seat:
    index: int
    team: int
    user_id: int
    name: str
    x: float = 0.0
    z: float = 0.0
    f: float = 0.0        # 摇杆：前（朝对面）
    r: float = 0.0        # 摇杆：右
    cooldown: float = 0.0
    is_ai: bool = False   # 电脑座位（由服务器操作，规则和真人一样）


@dataclass
class Room:
    id: str
    name: str
    mode: str                 # "single" 单打 / "double" 双打
    host_id: int
    host_name: str
    seats: List[Optional[Seat]] = field(default_factory=list)
    status: str = "waiting"   # waiting 等待 / playing 进行中 / finished 已结束
    phase: str = "idle"       # serve_wait 等发球 / toss 抛球中 / rally 对打 / point_over 一分结束
    message: str = ""
    timer: float = 0.0
    ball: Ball = field(default_factory=Ball)
    score: Score = field(default_factory=Score)
    server_seat: int = 0
    serve_attempt: int = 1
    serve_pending: bool = False     # 发球已击出，还没落到对方的发球区
    last_seat: Optional[int] = None  # 最后击球的座位
    bounces: int = 0                 # 球在对方场地落地的次数（没人回击时）
    events: List[dict] = field(default_factory=list)   # 这一帧发生的事（发给前端播音效）
    ai: bool = False                 # 人机房间：2 号位是电脑，只能单打，不出现在大厅
    rng: random.Random = field(default_factory=random.Random)
    ai_timer: float = 0.0            # 电脑发球方：已经等了多久
    ai_wait: float = 0.0             # 电脑这次没去接球：还要等多久再判断

    def __post_init__(self):
        cap = 2 if self.mode == "single" else 4
        if self.ai and cap != 2:
            raise RoomError("人机对战只支持单打")
        if not self.seats:
            self.seats = [None] * cap
        # 房主自动占 1 号位（建房时就占好，别人抢不走）
        self.seats[0] = self._new_seat(0, self.host_id, self.host_name)
        if self.ai:
            # 人机房间：电脑直接坐在 2 号位，房间立刻满员
            self.seats[1] = self._new_seat(1, AI_ID, AI_NAME)
            self.seats[1].is_ai = True

    # -------------------------------------------------- 座位

    @property
    def capacity(self) -> int:
        return len(self.seats)

    def _new_seat(self, index: int, user_id: int, name: str) -> Seat:
        cap = self.capacity
        team = 0 if index < cap // 2 else 1
        if cap == 2:
            z = 0.0
        else:
            k = index % 2      # 同一队的两个人，一个在左边一个在右边
            z = -2.4 if k == 0 else 2.4
        x = -9.0 if team == 0 else 9.0
        return Seat(index, team, user_id, name, x=x, z=z)

    def ai_seat(self) -> Optional[Seat]:
        for s in self.seats:
            if s and s.is_ai:
                return s
        return None

    def seat_of(self, user_id: int) -> Optional[Seat]:
        for s in self.seats:
            if s and s.user_id == user_id:
                return s
        return None

    def player_count(self) -> int:
        return sum(1 for s in self.seats if s)

    def join(self, user_id: int, name: str) -> Seat:
        if self.seat_of(user_id):
            return self.seat_of(user_id)
        if self.status != "waiting":
            raise RoomError("比赛进行中，不能加入")
        for i, s in enumerate(self.seats):
            if s is None:
                seat = self._new_seat(i, user_id, name)
                self.seats[i] = seat
                return seat
        raise RoomError("房间已满")

    def leave(self, user_id: int):
        for i, s in enumerate(self.seats):
            if s and s.user_id == user_id:
                self.seats[i] = None

    # -------------------------------------------------- 开始 / 结束

    def start(self, user_id: int):
        if user_id != self.host_id:
            raise RoomError("只有房主可以开始比赛")
        if self.status == "playing":
            raise RoomError("比赛已经在进行中")
        if self.player_count() < self.capacity:
            raise RoomError("人还没坐满，不能开始")
        self.status = "playing"
        self.score = Score()
        self.server_seat = 0
        self.serve_attempt = 1
        self.message = ""
        self._prepare_serve()

    def _prepare_serve(self):
        """轮到新的一分：发球人移到发球位置，球握在手里。"""
        order = SERVE_ORDER[self.capacity]
        self.server_seat = order[self.score.total_games % len(order)]
        self.ai_timer = 0.0
        self.phase = "serve_wait"
        self.serve_pending = False
        self.last_seat = None
        self.bounces = 0
        server = self.seats[self.server_seat]
        server.x = -12.2 if server.team == 0 else 12.2
        server.z = self.serve_zside() * 0.6
        self.ball.hold_at(server.x, 1.0, server.z)

    def serve_zside(self) -> int:
        """发球站在哪一边：分数之和为偶数时在右（z>0），奇数时在左（z<0）。"""
        return 1 if (self.score.points[0] + self.score.points[1]) % 2 == 0 else -1

    # -------------------------------------------------- 玩家操作

    def set_stick(self, user_id: int, f: float, r: float):
        seat = self.seat_of(user_id)
        if not seat:
            return
        f = clamp(float(f), -1.0, 1.0)
        r = clamp(float(r), -1.0, 1.0)
        mag = math.hypot(f, r)
        if mag > 1:
            f, r = f / mag, r / mag
        seat.f, seat.r = f, r

    def swing(self, user_id: int, stroke: str, aim_r: float = 0.0, aim_f: float = 0.0) -> str:
        """挥拍。返回给玩家看的提示（空字符串表示成功）。"""
        if self.status != "playing":
            raise RoomError("比赛还没开始")
        seat = self.seat_of(user_id)
        if not seat:
            raise RoomError("你不在这个房间里")
        if stroke not in STROKES:
            raise RoomError("没有这种球")
        if seat.cooldown > 0:
            return ""
        aim_r = clamp(float(aim_r), -1.0, 1.0)
        aim_f = clamp(float(aim_f), -1.0, 1.0)

        if self.phase == "serve_wait":
            if seat.index != self.server_seat:
                raise RoomError("还没轮到你发球")
            self.phase = "toss"
            self.message = ""
            b = self.ball
            b.hold_at(seat.x, TOSS_Y, seat.z)
            b.vy = TOSS_VY
            return ""

        if self.phase == "toss":
            if seat.index != self.server_seat:
                raise RoomError("现在是对方发球")
            dist = math.hypot(self.ball.x - seat.x, self.ball.z - seat.z)
            if dist > 1.0 or not (SERVE_MIN_Y <= self.ball.y <= SERVE_MAX_Y):
                raise RoomError("球还没到合适的位置")
            seat.cooldown = SWING_COOLDOWN
            self._hit(seat, stroke, aim_r, aim_f, serve=True)
            return ""

        if self.phase == "rally":
            if seat.index == self.last_seat:
                raise RoomError("不能连续击同一个球两次")
            dist = math.hypot(self.ball.x - seat.x, self.ball.z - seat.z)
            if dist > REACH or not (REACH_MIN_Y <= self.ball.y <= REACH_MAX_Y):
                raise RoomError("没够到球")
            seat.cooldown = SWING_COOLDOWN
            self._hit(seat, stroke, aim_r, aim_f, serve=False)
            return ""

        raise RoomError("这一分还没开始")

    def _hit(self, seat: Seat, stroke: str, aim_r: float, aim_f: float, serve: bool):
        s = STROKES[stroke]
        b = self.ball
        dist = math.hypot(b.x - seat.x, b.z - seat.z)
        quality = clamp(1 - dist / REACH, 0.3, 1.0)      # 击中球拍中心最好
        opp = 1 if seat.team == 0 else -1                  # 对面球场的方向（队 0 打向 x>0）

        if serve:
            base = SERVE_SPEED
            tx = opp * clamp(3.5 + 0.6 * aim_f, 1.5, 6.0)            # 落在发球区内
            tz = -self.serve_zside() * 1.9 + aim_r * 1.2
            tz = clamp(tz, -3.9, 3.9)
            clear = SERVE_CLEAR
        else:
            base = BASE_SPEED
            tx = opp * clamp(s["depth"] + 0.8 * aim_f, 4.0, 11.2)   # 最深也要落在底线以内
            tz = clamp(aim_r * 4.0 + seat.z * 0.2, -5.0, 5.0)
            clear = s["clear"]
        speed = base * s["speed"] * (0.85 + 0.15 * quality)
        b.top = s["top"]
        b.side = s["side"]
        vx, vy, vz = solve_launch(b.x, b.y, b.z, tx, tz, speed, clear, s["top"])
        b.vx, b.vy, b.vz = vx, vy, vz
        b.grounded = False
        b.rolling_stop = False
        self.last_seat = seat.index
        self.bounces = 0
        self.serve_pending = serve
        if serve:
            self.phase = "rally"
            self.message = ""
        self.events.append({"type": "hit", "seat": seat.index, "stroke": stroke, "serve": serve})

    # -------------------------------------------------- 每一帧

    def tick(self, dt: float) -> None:
        if self.status != "playing":
            return
        if self.ai:
            self._ai_step(dt)
        for seat in self.seats:
            if seat:
                seat.cooldown = max(0.0, seat.cooldown - dt)
                self._move(seat, dt)

        if self.phase == "point_over":
            self.timer -= dt
            if self.timer <= 0:
                self._next_point()
            return
        if self.phase not in ("toss", "rally"):
            return
        h = dt / PHYSICS_SUBSTEPS
        for _ in range(PHYSICS_SUBSTEPS):
            if self.phase not in ("toss", "rally"):
                break
            for kind, x, z in step_ball(self.ball, h):
                self._on_ball_event(kind, x, z)

    def _ai_step(self, dt: float):
        """电脑的决策：每个 tick 调用一次。它只用摇杆和挥拍，和真人走同样的规则。"""
        seat = self.ai_seat()
        if seat is None:
            return
        b = self.ball
        is_server = seat.index == self.server_seat

        if self.phase == "serve_wait" and is_server:
            self.ai_timer += dt
            if self.ai_timer >= AI_SERVE_DELAY:
                self.ai_timer = 0.0
                try:
                    self.swing(AI_ID, "top")          # 抛球
                except RoomError:
                    pass
            return
        if self.phase == "toss" and is_server:
            # 球下落到合适的高度时发球（在窗口内会每个 tick 试一次，只会成功一次）
            if b.vy < 0 and 1.8 <= b.y <= 2.8:
                try:
                    self.swing(AI_ID, self._ai_pick_stroke(), self._ai_aim(), 0.0)
                except RoomError:
                    pass
            return

        # 移动：来球时跑到球的落点附近，否则站在基准位置
        if self.phase == "rally" and b.vx < 0:       # 球朝电脑这一边飞
            tx = clamp(b.x + b.vx * 0.25, 0.6, 12.0)
            tz = b.z + b.vz * 0.25
        else:
            tx, tz = 8.0, 0.0
        dx, dz = tx - seat.x, tz - seat.z
        fx, fz = (1.0, 0.0) if seat.team == 0 else (-1.0, 0.0)   # 朝对面
        rx, rz = -fz, fx                                          # 右手边
        self.set_stick(AI_ID,
                       clamp((dx * fx + dz * fz) * 2, -1, 1),
                       clamp((dx * rx + dz * rz) * 2, -1, 1))

        # 击球：来球在够得着的范围内，就击球（偶尔失误）
        if self.phase == "rally" and seat.index != self.last_seat and seat.cooldown <= 0:
            if self.ai_wait > 0:
                self.ai_wait -= dt
                return
            dist = math.hypot(b.x - seat.x, b.z - seat.z)
            if dist < REACH * 0.9 and REACH_MIN_Y <= b.y <= REACH_MAX_Y:
                if self.rng.random() < AI_HIT_CHANCE:
                    try:
                        self.swing(AI_ID, self._ai_pick_stroke(), self._ai_aim(),
                                   self.rng.uniform(-0.2, 0.6))
                    except RoomError:
                        pass
                else:
                    self.ai_wait = AI_MISS_WAIT

    def _ai_pick_stroke(self) -> str:
        names = [n for n, _ in AI_STROKES]
        weights = [w for _, w in AI_STROKES]
        return self.rng.choices(names, weights)[0]

    def _ai_aim(self) -> float:
        """电脑的瞄准有随机误差：左右偏差在 ±0.8 以内。"""
        return self.rng.uniform(-0.8, 0.8)

    def _move(self, seat: Seat, dt: float):
        if seat.f == 0 and seat.r == 0:
            return
        # 发球方站在发球位置不能动，直到把球发出去
        if self.phase in ("serve_wait", "toss") and seat.index == self.server_seat:
            return
        # 摇杆方向是「相对自己的」：前 = 朝对面，右 = 自己的右手边
        fx, fz = (1.0, 0.0) if seat.team == 0 else (-1.0, 0.0)
        rx, rz = -fz, fx          # 右手边
        dx = seat.f * fx + seat.r * rx
        dz = seat.f * fz + seat.r * rz
        seat.x += dx * PLAYER_SPEED * dt
        seat.z += dz * PLAYER_SPEED * dt
        if seat.team == 0:
            seat.x = clamp(seat.x, -13.0, -0.6)
        else:
            seat.x = clamp(seat.x, 0.6, 13.0)
        seat.z = clamp(seat.z, -6.2, 6.2)

    def _on_ball_event(self, kind: str, x: float, z: float):
        self.events.append({"type": kind, "x": round(x, 2), "z": round(z, 2)})
        last_team = self.seats[self.last_seat].team if self.last_seat is not None else None
        if self.phase == "toss":
            self._serve_fault("抛球没有接住")
            return
        if kind == "net":
            if self.serve_pending:
                self._serve_fault("发球下网")
            elif last_team is not None:
                self._point(1 - last_team, "球下网了")
        elif kind == "far":
            if last_team is not None:
                self._point(1 - last_team, "球飞出了场外")
        elif kind == "stop":
            if self.serve_pending:
                self._serve_fault("发球没有落在发球区")
            elif last_team is not None:
                self._point(last_team, "球停下了，对方没接到")
        elif kind == "bounce":
            if self.serve_pending:
                receiver_sign = 1 if self.seats[self.server_seat].team == 0 else -1
                if in_service_box(x, z, receiver_sign, self.serve_zside()):
                    self.serve_pending = False
                    self.bounces = 1
                else:
                    self._serve_fault("发球没有落在对角的发球区")
                return
            if last_team is None:
                return
            singles = self.mode == "single"
            self.bounces += 1
            side = 0 if x < 0 else 1
            if not in_court(x, z, singles):
                self._point(1 - last_team, "球出界了")
            elif side == last_team:
                self._point(1 - last_team, "球落在了自己这一边")
            elif self.bounces >= 2:
                self._point(last_team, "球弹了两次")

    def _serve_fault(self, reason: str):
        self.serve_pending = False
        self.ai_timer = 0.0
        if self.serve_attempt == 1:
            self.serve_attempt = 2
            self.phase = "serve_wait"
            server = self.seats[self.server_seat]
            self.ball.hold_at(server.x, 1.0, server.z)
            self.message = f"一发失误：{reason}，请再发一次"
            self.events.append({"type": "fault", "reason": reason})
        else:
            server_team = self.seats[self.server_seat].team
            self._point(1 - server_team, f"双发失误：{reason}")

    def _point(self, winner_team: int, reason: str):
        game_won, set_won = self.score.win_point(winner_team)
        self.phase = "point_over"
        self.timer = POINT_PAUSE
        self.serve_pending = False
        self.ball.vx = self.ball.vy = self.ball.vz = 0.0
        self.ball.grounded = True
        self.ball.rolling_stop = True
        team_name = "队伍 A" if winner_team == 0 else "队伍 B"
        self.message = f"{reason}，{team_name} 得分"
        self.events.append({"type": "point", "winner": winner_team, "reason": reason,
                            "game": game_won, "set": set_won})
        if self.score.done:
            self.status = "finished"
            self.phase = "match_over"
            self.message = f"比赛结束：{team_name} 获胜！"

    def _next_point(self):
        self.serve_attempt = 1
        self._prepare_serve()

    def restart(self, user_id: int):
        if user_id != self.host_id:
            raise RoomError("只有房主可以再打一局")
        if self.status != "finished":
            raise RoomError("比赛还没有结束")
        if self.player_count() < self.capacity:
            raise RoomError("人还没坐满")
        self.status = "playing"
        self.score = Score()
        self.server_seat = 0
        self.serve_attempt = 1
        self.message = ""
        self._prepare_serve()

    def abort(self, reason: str):
        """比赛中途作废（有人离开）。"""
        self.status = "finished"
        self.phase = "idle"
        self.message = reason

    # -------------------------------------------------- 给前端的数据

    def summary(self) -> dict:
        return {
            "id": self.id, "name": self.name, "mode": self.mode,
            "modeName": "单打" if self.mode == "single" else "双打",
            "status": self.status, "host": self.host_name,
            "players": self.player_count(), "capacity": self.capacity,
            "ai": self.ai,
        }

    def snapshot(self) -> dict:
        b = self.ball
        events, self.events = self.events, []
        return {
            "type": "state",
            "status": self.status,
            "phase": self.phase,
            "message": self.message,
            "serveSeat": self.server_seat,
            "serveAttempt": self.serve_attempt,
            "lastSeat": self.last_seat,
            "score": self.score.to_dict(),
            "ball": {"x": round(b.x, 3), "y": round(b.y, 3), "z": round(b.z, 3),
                     "top": round(b.top, 2), "side": round(b.side, 2)},
            "seats": [None if s is None else {
                "index": s.index, "team": s.team, "userId": s.user_id, "name": s.name,
                "isAi": s.is_ai,
                "x": round(s.x, 3), "z": round(s.z, 3),
            } for s in self.seats],
            "events": events,
        }


def new_room_id() -> str:
    return secrets.token_hex(4)
