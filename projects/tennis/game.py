"""网球的游戏核心：抽象的回合制选择（2026-11-26 版）。

玩法：
- 对方一击球，你就开始选。对方头顶会显示他刚打的那一拍（「如果我上网，你该如何应对？」）。
- 每次给你三个选项（打法 + 落点）。三个里至少一个是克制对方这一拍的「好选择」。
- 好选择成功率高，其余选项容易失误。失误的球直接判这一分。
- 小人会跑到来球落点的位置去接球，击球动作和落点都和选择的打法一致。

站位：depth（back 后场 / mid 中场 / front 前场）× lane（1 一区 / 2 二区）。
一区、二区按世界坐标固定（以球场中线为界）。

所有判定都在服务器算。这里**不碰网络**，只做计算，所以可以直接用测试检查。
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

SERVE_ORDER = {2: [0, 1], 4: [0, 2, 1, 3]}   # 发球顺序（座位号）

AI_ID = -1                 # 电脑座位的「用户 id」（不会和真实用户重复）
AI_NAME = "电脑"
AI_THINK = 1.2             # 电脑想多久再选（秒）
AI_BEST_P = 0.7            # 电脑有这么大的概率选「好选择」，其余时间随机选
MENU_TIME = 12.0           # 玩家的选择时限（秒），超时就随机选
WINDUP = 0.35              # 选完后到挥拍的最短时间（秒）
POINT_PAUSE = 2.2          # 一分结束后的停顿（秒）
FLIGHT = 1.0               # 普通球飞过来的时间（秒）
FLIGHT_HIGH = 1.4          # 高球、发球飞过来的时间（秒）

BEST_P = 0.88              # 好选择（克制对方这一拍）的成功率
FALLBACK_P = 0.72          # 没有克制选项时，随机挑一个当好选择的成功率
OTHER_P = 0.62             # 其余选项的成功率
SERVE_BEST_P = 0.90        # 发球的好选择成功率
SERVE_OTHER_P = 0.70       # 发球的其余成功率
WINNER_P = 0.08            # 高压、截击成功时直接得分的概率

DEPTH_NAME = {"back": "后场", "mid": "中场", "front": "前场"}
LANE_NAME = {1: "一区", 2: "二区"}
DEPTH_X = {"back": 10.6, "mid": 7.0, "front": 3.4}   # 站位对应的距离（队 0 在 x<0 一侧）
LANE_Z = {1: -2.3, 2: 2.3}                             # 一区、二区对应的左右位置

# 打法。attack：这一拍对对方来说是什么（用来找克制）；action：气泡里的说法
# lane：same 同一区 / opp 另一区 / any 任选；fail：失败的结果；arc：球的弧线；anim：击球动作
KINDS: Dict[str, dict] = {
    "straight":     dict(name="直线", action="打直线", attack="deep", depths=["back"], lane="same", fail="out", arc="normal", recover="back", anim="fore", winner=False),
    "cross":        dict(name="反斜线", action="打反斜线", attack="deep", depths=["back"], lane="opp", fail="out", arc="normal", recover="back", anim="fore", winner=False),
    "short_cross":  dict(name="小斜线", action="打小斜线", attack="short_cross", depths=["front", "mid"], lane="opp", fail="net", arc="low", recover="mid", anim="drop", winner=False),
    "drop":         dict(name="小球", action="打小球", attack="drop", depths=["front"], lane="any", fail="net", arc="low", recover="mid", anim="drop", winner=False),
    "lob":          dict(name="挑高", action="挑高", attack="lob", depths=["back"], lane="any", fail="out", arc="high", recover="back", anim="lob", winner=False),
    "smash":        dict(name="高压", action="高压", attack="smash", depths=["back", "mid"], lane="any", fail="rand", arc="high", recover="front", anim="smash", winner=True),
    "volley":       dict(name="截击", action="截击", attack="volley", depths=["mid"], lane="any", fail="net", arc="normal", recover="front", anim="volley", winner=True),
    "short_volley": dict(name="截短", action="截短", attack="short_cross", depths=["front"], lane="any", fail="net", arc="normal", recover="front", anim="volley", winner=False),
    "deep_volley":  dict(name="截长", action="截长", attack="volley", depths=["back"], lane="any", fail="out", arc="normal", recover="front", anim="volley", winner=False),
    "slice":        dict(name="切削", action="切削", attack="slice", depths=["mid"], lane="any", fail="net", arc="low", recover="mid", anim="slice", winner=False),
    "topspin":      dict(name="上旋", action="上旋", attack="topspin", depths=["back"], lane="any", fail="out", arc="normal", recover="back", anim="fore", winner=False),
    "flat":         dict(name="平击深球", action="平击深球", attack="deep", depths=["back"], lane="any", fail="out", arc="normal", recover="back", anim="fore", winner=False),
    "approach":     dict(name="上网", action="上网", attack="approach", depths=["back", "mid"], lane="any", fail="net", arc="normal", recover="front", anim="fore", winner=False),
}
# 发球。attack 是对方要面对的这一拍；发球落点永远在对角的那一区
SERVES: Dict[str, dict] = {
    "serve_flat":  dict(name="平发", action="发平球", attack="deep", depth="back", arc="normal", fail="fault", anim="serve"),
    "serve_top":   dict(name="上旋发球", action="发上旋球", attack="topspin", depth="back", arc="normal", fail="fault", anim="serve"),
    "serve_slice": dict(name="切发球", action="发切削球", attack="slice", depth="mid", arc="low", fail="fault", anim="serve"),
}
SERVE_IDS = list(SERVES)

# 克制表：对方这一拍（attack）→ 能克制它的打法（好选择从这里挑）
COUNTERS: Dict[str, List[str]] = {
    "approach": ["lob", "straight", "cross"],
    "drop": ["short_volley", "volley"],
    "short_cross": ["short_volley", "approach"],
    "volley": ["lob", "straight", "cross", "deep_volley"],
    "lob": ["smash"],
    "smash": ["topspin"],
    "deep": ["drop", "short_cross"],
    "topspin": ["slice", "short_cross"],
    "slice": ["topspin", "approach"],
}


class RoomError(Exception):
    """玩家的操作不合法（给玩家看的中文提示）。"""


def allowed_kind(kind: str, attack: str) -> bool:
    """这一拍之后，这种打法能不能用（例如只有对方挑高，才能高压）。"""
    if kind == "smash":
        return attack == "lob"
    if kind in ("volley", "short_volley", "deep_volley"):
        return attack in ("drop", "short_cross", "approach", "volley")
    if kind == "approach":
        return attack in ("deep", "topspin", "slice", "short_cross", "drop")
    return True


def other_lane(lane: int) -> int:
    return 3 - lane


@dataclass
class Seat:
    index: int
    team: int
    user_id: int
    name: str
    lane: int = 1              # 站在一区还是二区（接球时会跑到来球那一区）
    depth: str = "back"        # 站在前场、中场还是后场
    is_ai: bool = False        # 电脑座位（由服务器操作，规则和真人一样）


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




@dataclass
class Room:
    id: str
    name: str
    mode: str                 # "single" 单打 / "double" 双打
    host_id: int
    host_name: str
    seats: List[Optional[Seat]] = field(default_factory=list)
    status: str = "waiting"   # waiting 等待 / playing 进行中 / finished 已结束
    # 阶段：serve_menu 发球方选 / menu 对方击球后，接球方选 / swing 挥拍 / shot 失误的球飞出去 / point_over 一分结束
    phase: str = "idle"
    message: str = ""
    timer: float = 0.0        # 挥拍、飞球或停顿还剩多久
    deadline: float = 0.0     # 选择还剩多久
    score: Score = field(default_factory=Score)
    server_seat: int = 0
    serve_attempt: int = 1
    hitter: Optional[int] = None         # 现在轮到哪个座位选择
    menu_options: List[dict] = field(default_factory=list)
    menu_best: Optional[str] = None      # 好选择的选项编号（只在服务器知道）
    menu_best_p: float = BEST_P
    menu_other_p: float = OTHER_P
    menu_attack: str = "serve"           # 对方这一拍是什么（用来找克制）
    menu_elapsed: float = 0.0            # 球已经飞了多久
    flight: float = FLIGHT               # 这一拍的球要飞多久
    bubble: Optional[dict] = None        # 对方头顶的气泡：{"seat": 座位, "text": 文字}
    chosen: Optional[dict] = None        # 玩家选中的选项（挥拍时才结算）
    next_receiver: Optional[tuple] = None  # 击球成功后，轮到谁接球（等挥拍动画结束再开始）
    pending: Optional[Tuple[int, str]] = None   # 这一分要结算：(得分队, 原因)
    reserve: bool = False                        # 一发失误：挥拍结束后重新发球
    last_seat: Optional[int] = None
    last_shot: Optional[dict] = None
    events: List[dict] = field(default_factory=list)   # 这一帧发生的事（发给前端做动画）
    ai: bool = False                 # 人机房间：2 号位是电脑，只能单打，不出现在大厅
    rng: random.Random = field(default_factory=random.Random)
    ai_timer: float = 0.0            # 电脑已经想了多久

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
        lane = 1 if index % 2 == 0 else 2     # 双打时同一队的两个人分在一区和二区
        return Seat(index, team, user_id, name, lane=lane, depth="back")

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
        self.message = ""
        self._next_point()

    def restart(self, user_id: int):
        if user_id != self.host_id:
            raise RoomError("只有房主可以再打一局")
        if self.status != "finished":
            raise RoomError("比赛还没有结束")
        if self.player_count() < self.capacity:
            raise RoomError("人还没坐满")
        self.status = "playing"
        self.score = Score()
        self.message = ""
        self._next_point()

    def abort(self, reason: str):
        """比赛中途作废（有人离开）。"""
        self.status = "finished"
        self.phase = "idle"
        self.message = reason

    # -------------------------------------------------- 一分的开始

    def _next_point(self):
        """新的一分：发球方按局轮换，站在发球位置（一区或二区，由比分决定）。"""
        self.serve_attempt = 1
        order = SERVE_ORDER[self.capacity]
        self.server_seat = order[self.score.total_games % len(order)]
        server = self.seats[self.server_seat]
        for s in self.seats:
            if s:
                s.depth = "back"
        # 比分之和为偶数站一区，为奇数站二区（发球落到对角）
        server.lane = 1 if (self.score.points[0] + self.score.points[1]) % 2 == 0 else 2
        self.pending = None
        self.reserve = False
        self.next_receiver = None
        self.last_seat = None
        self.last_shot = None
        self.bubble = None
        self.chosen = None
        self.ai_timer = 0.0
        self._open_serve_menu()

    def _open_serve_menu(self):
        self.phase = "serve_menu"
        self.hitter = self.server_seat
        rng = self.rng
        options = []
        best = rng.choice(SERVE_IDS)
        server_lane = self.seats[self.server_seat].lane
        for k in SERVE_IDS:
            spec = SERVES[k]
            lane = other_lane(server_lane)
            options.append({"id": k, "kind": k, "depth": spec["depth"], "lane": lane,
                            "name": f"{spec['name']}·{LANE_NAME[lane]}{DEPTH_NAME[spec['depth']]}",
                            "desc": f"发到对角{LANE_NAME[lane]}{DEPTH_NAME[spec['depth']]}"})
        rng.shuffle(options)
        self.menu_options = options
        self.menu_best = best
        self.menu_best_p = SERVE_BEST_P
        self.menu_other_p = SERVE_OTHER_P
        self.menu_attack = "serve"
        self.menu_elapsed = 0.0
        self.flight = FLIGHT_HIGH
        self.deadline = MENU_TIME
        self.bubble = None
        self.ai_timer = 0.0

    def _open_rally_menu(self, receiver: Seat, attack: str, bubble_text: str,
                         lane: int, depth: str, flight: float):
        """对方击球的那一刻：接球方跑向来球的落点，开始选择。"""
        receiver.lane = lane
        receiver.depth = depth
        self.phase = "menu"
        self.hitter = receiver.index
        self._build_menu(attack, lane)
        self.menu_attack = attack
        self.menu_elapsed = 0.0
        self.flight = flight
        self.deadline = MENU_TIME
        self.bubble = {"seat": self.last_seat, "text": bubble_text}
        self.ai_timer = 0.0

    def _build_menu(self, attack: str, contact_lane: int):
        """给接球方三个选项：好选择（克制对方这一拍）+ 两个其他的。"""
        rng = self.rng
        pool = [k for k in KINDS if allowed_kind(k, attack)]
        counters = [k for k in COUNTERS.get(attack, []) if k in pool]
        if counters:
            best_kind = rng.choice(counters)
            best_p = BEST_P
            chosen = [best_kind]
        else:
            best_kind = None
            best_p = FALLBACK_P
            chosen = []
        others = [k for k in pool if k != best_kind]
        rng.shuffle(others)
        chosen += others[:3 - len(chosen)]
        if best_kind is None:
            best_kind = rng.choice(chosen)
        rng.shuffle(chosen)
        options = []
        for k in chosen:
            spec = KINDS[k]
            depth = rng.choice(spec["depths"])
            if spec["lane"] == "same":
                lane = contact_lane
            elif spec["lane"] == "opp":
                lane = other_lane(contact_lane)
            else:
                lane = rng.choice([1, 2])
            options.append({
                "id": f"{k}-{depth}-{lane}", "kind": k, "depth": depth, "lane": lane,
                "name": f"{spec['name']}·{LANE_NAME[lane]}{DEPTH_NAME[depth]}",
                "desc": f"打到对方{LANE_NAME[lane]}{DEPTH_NAME[depth]}",
            })
        self.menu_options = options
        self.menu_best = next(o["id"] for o in options if o["kind"] == best_kind)
        self.menu_best_p = best_p
        self.menu_other_p = OTHER_P

    # -------------------------------------------------- 玩家的操作

    def choose(self, user_id: int, option_id: str) -> None:
        """接球方选择一个选项。挥拍时才结算成败（等球飞到为止）。"""
        if self.status != "playing":
            raise RoomError("比赛还没开始")
        seat = self.seat_of(user_id)
        if not seat:
            raise RoomError("你不在这个房间里")
        if self.phase not in ("menu", "serve_menu") or seat.index != self.hitter:
            raise RoomError("现在不是你选择的时候")
        opt = next((o for o in self.menu_options if o["id"] == option_id), None)
        if opt is None:
            raise RoomError("没有这个选项")
        self.chosen = dict(opt, serve=(self.phase == "serve_menu"))
        self.phase = "swing"
        # 球还没飞到的话，要等球到了才挥拍
        self.timer = max(WINDUP, self.flight - self.menu_elapsed)

    def _receiver(self, team: int, lane: int) -> Seat:
        """接球的人：这一队里离来球最近的那个（单打就是唯一的一个）。"""
        cands = [s for s in self.seats if s and s.team == team]
        best = min(abs(s.lane - lane) for s in cands)
        pick = [s for s in cands if abs(s.lane - lane) == best]
        return self.rng.choice(pick)

    def _resolve(self):
        """挥拍结束：掷骰子决定成败，发出击球事件，然后轮到对方（或判分）。"""
        opt = self.chosen
        self.chosen = None
        seat = self.seats[self.hitter] if self.hitter is not None else None
        serve = bool(opt.get("serve"))
        spec = SERVES[opt["kind"]] if serve else KINDS[opt["kind"]]
        p = self.menu_best_p if opt["id"] == self.menu_best else self.menu_other_p
        flight = FLIGHT_HIGH if (spec["arc"] == "high" or serve) else FLIGHT
        team = seat.team
        to_team = 1 - team

        result = "ok"
        fail = None
        if self.rng.random() < p:
            if not serve and spec.get("winner") and self.rng.random() < WINNER_P:
                result = "winner"
        else:
            result = "fail"
            fail = spec["fail"]
            if fail == "rand":
                fail = self.rng.choice(["net", "out"])

        # 击球的人跑到打法要求的位置（动画里会挪过去）
        if not serve:
            seat.depth = spec["recover"]

        if result == "fail":
            to_zone = "far" if fail == "out" else "net"
        else:
            to_zone = "court"

        self.last_shot = {"seat": self.hitter, "kind": opt["kind"], "name": spec["name"], "action": spec["action"]}
        self.events.append({
            "type": "shot", "seat": self.hitter, "kind": opt["kind"], "name": spec["name"],
            "action": spec["action"], "result": result, "fail": fail, "toTeam": to_team,
            "toZone": to_zone, "toDepth": opt["depth"], "toLane": opt["lane"],
            "arc": spec["arc"], "anim": spec["anim"], "flight": flight,
        })
        self.last_seat = self.hitter
        self.bubble = None

        if result == "winner":
            self.pending = (team, f"{spec['name']}直接得分")
        elif result == "fail":
            if fail == "fault":
                if self.serve_attempt == 1:
                    self.serve_attempt = 2
                    self.reserve = True
                    self.events.append({"type": "fault", "reason": "一发失误"})
                    self.message = "一发失误，请再发一次"
                else:
                    self.pending = (1 - team, "双发失误")
            else:
                word = "下网" if fail == "net" else "出界"
                self.pending = (1 - team, f"{spec['name']}{word}")

        if self.pending is not None or self.reserve:
            self.phase = "shot"
            self.timer = flight
            self.menu_options = []
            return

        # 成功：轮到对方接球。选择从对方击球的这一刻开始（球还在飞，他就跑过去）。
        receiver = self._receiver(to_team, opt["lane"])
        text = f"如果我{spec['action']}，你该如何应对？"
        self.next_receiver = None
        self._open_rally_menu(receiver, spec["attack"], text, opt["lane"], opt["depth"], flight)

    # -------------------------------------------------- 每一帧

    def tick(self, dt: float) -> None:
        if self.status != "playing":
            return
        if self.ai:
            self._ai_step(dt)
        if self.phase in ("menu", "serve_menu"):
            self.menu_elapsed += dt
            seat = self.seats[self.hitter] if self.hitter is not None else None
            if seat and not seat.is_ai:
                self.deadline -= dt
                if self.deadline <= 0 and self.menu_options:    # 超时：随机选一个
                    self.choose(seat.user_id, self.rng.choice(self.menu_options)["id"])
            return
        if self.phase == "swing":
            self.timer -= dt
            if self.timer <= 0:
                self._resolve()
            return
        if self.phase == "shot":
            self.timer -= dt
            if self.timer <= 0:
                self._finish_shot()
            return
        if self.phase == "point_over":
            self.timer -= dt
            if self.timer <= 0:
                self._next_point()

    def _finish_shot(self):
        """挥拍的球飞完了：判这一分，或者轮到对方接球，或者重新发球。"""
        if self.pending:
            winner, reason = self.pending
            self._point(winner, reason)
            return
        if self.reserve:
            self.reserve = False
            self.bubble = None
            self._open_serve_menu()
            return
        if self.next_receiver:
            idx, attack, text, lane, depth, flight = self.next_receiver
            self.next_receiver = None
            self._open_rally_menu(self.seats[idx], attack, text, lane, depth, flight)

    def _ai_step(self, dt: float):
        """电脑：轮到它选择时，想一会儿再选。大多数时候选好选择。"""
        seat = self.ai_seat()
        if seat is None:
            return
        if self.phase in ("menu", "serve_menu") and self.hitter == seat.index and self.menu_options:
            self.ai_timer += dt
            if self.ai_timer >= AI_THINK:
                self.ai_timer = 0.0
                if self.rng.random() < AI_BEST_P:
                    pick = self.menu_best
                else:
                    pick = self.rng.choice(self.menu_options)["id"]
                self.choose(AI_ID, pick)
        else:
            self.ai_timer = 0.0

    def _point(self, winner_team: int, reason: str):
        game_won, set_won = self.score.win_point(winner_team)
        self.phase = "point_over"
        self.timer = POINT_PAUSE
        self.hitter = None
        self.menu_options = []
        self.pending = None
        self.bubble = None
        team_name = "队伍 A" if winner_team == 0 else "队伍 B"
        self.message = f"{reason}，{team_name} 得分"
        self.events.append({"type": "point", "winner": winner_team, "reason": reason,
                            "game": game_won, "set": set_won})
        if self.score.done:
            self.status = "finished"
            self.phase = "match_over"
            self.message = f"比赛结束：{team_name} 获胜！"

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
        events, self.events = self.events, []
        menu = None
        if self.phase in ("menu", "serve_menu") and self.menu_options:
            menu = {
                "options": [{"id": o["id"], "name": o["name"], "desc": o["desc"],
                             "depth": o["depth"], "lane": o["lane"]} for o in self.menu_options],
                "attack": self.menu_attack,
                "deadline": round(max(0.0, self.deadline), 2),
                "flight": self.flight,
                "elapsed": round(self.menu_elapsed, 2),
            }
        return {
            "type": "state",
            "status": self.status,
            "phase": self.phase,
            "message": self.message,
            "timer": round(max(0.0, self.timer), 2),
            "serveSeat": self.server_seat,
            "serveAttempt": self.serve_attempt,
            "hitter": self.hitter,
            "lastSeat": self.last_seat,
            "score": self.score.to_dict(),
            "menu": menu,
            "bubble": self.bubble,
            "seats": [None if s is None else {
                "index": s.index, "team": s.team, "userId": s.user_id, "name": s.name,
                "isAi": s.is_ai, "lane": s.lane, "depth": s.depth,
            } for s in self.seats],
            "events": events,
        }


def new_room_id() -> str:
    return secrets.token_hex(4)
