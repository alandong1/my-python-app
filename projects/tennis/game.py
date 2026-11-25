"""网球的游戏核心：抽象的回合制选择。

玩法（2026-11-25 起）：不模拟球的物理。每次球到了一个人的面前，这个人从三个选项里
选一个怎么打；选项决定小人站到哪里、球落到对面哪里，以及失败时是下网还是出界。
选项成功率不一样：「好选择」约 80%，另外两个约 35%。来回进行，直到有人失分。

所有判定都在服务器算。这里**不碰网络**，只做计算，所以可以直接用测试检查。
服务器每秒检查 30 次计时器（选择时限、动画、一分结束后的停顿），前端只负责显示。

站位（zone）：back 后场、mid 中场、net 网前。队 0 在 x<0 一侧，队 1 在 x>0 一侧。
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
MENU_TIME = 12.0           # 人类玩家的选择时限（秒），超时就随机选
SHOT_TIME = 1.6            # 击球动画的时长（秒）
POINT_PAUSE = 2.2          # 一分结束后的停顿（秒）

BEST_P = 0.8               # 「好选择」（选项和对方站位配合）的成功率
FALLBACK_P = 0.6           # 三个选项里没有对口的，随机挑一个当好选择，成功率稍低
OTHER_P = 0.35             # 其余选项的成功率
SERVE_OTHER_P = 0.55       # 发球时其余发球的成功率（发球比对打稳一些）
WINNER_P = 0.3             # 截击、高压成功时，直接得分的概率

# 选项：zone 击球后小人站的位置；next 成功后对方面对的局面；fail 失败的结果
OPTIONS: Dict[str, dict] = {
    "flat":   dict(name="深球（平击）", desc="打到对方后场，最常用", zone="back", next="deep", fail="out"),
    "top":    dict(name="上旋深球", desc="球会下沉，落点稳", zone="back", next="deep", fail="out"),
    "slice":  dict(name="切削", desc="低而慢的球，逼对方失误", zone="mid", next="short", fail="net"),
    "drop":   dict(name="小球", desc="轻轻放在网前，逼对方跑上来", zone="mid", next="short", fail="net"),
    "lob":    dict(name="高挑", desc="高高挑过对方头顶", zone="back", next="lob", fail="out"),
    "volley": dict(name="上网截击", desc="冲到网前，在空中截住球", zone="net", next="deep", fail="net", winner=True),
    "smash":  dict(name="高压", desc="跳起来重扣后场", zone="net", next="deep", fail="rand", winner=True),
    "serve_flat":  dict(name="平发", desc="速度快，但容易失误", zone="back", next="deep", fail="fault"),
    "serve_top":   dict(name="上旋发球", desc="稳一些，弹起来偏高", zone="back", next="deep", fail="fault"),
    "serve_slice": dict(name="切发球", desc="角度刁，落点偏短", zone="back", next="short", fail="fault"),
}
# 局面 → 可以给的选项（每次从里面挑三个）
POOLS: Dict[str, List[str]] = {
    "deep": ["flat", "top", "slice", "drop", "lob"],     # 球落在我方后场
    "short": ["volley", "drop", "lob", "flat", "slice"],  # 对方来了短球
    "lob": ["smash", "flat", "volley"],                   # 对方挑高过来
}
SERVE_IDS = ["serve_flat", "serve_top", "serve_slice"]
ARC_OPTIONS = {"lob", "smash", "serve_top"}   # 这些球要飞高弧线
ZONE_X = {"back": 10.6, "mid": 7.0, "net": 2.6}


class RoomError(Exception):
    """玩家的操作不合法（给玩家看的中文提示）。"""


def tactical_best(situation: str, opp_zone: str) -> Optional[str]:
    """和局面、对方站位配合的「好选择」。没有对口的返回 None。"""
    if situation == "deep":
        if opp_zone == "net":
            return "lob"      # 对方在网前，挑过头顶
        if opp_zone == "back":
            return "drop"     # 对方在后场，放小球
        return "flat"         # 对方在中场，打深球
    if situation == "short":
        return "volley"       # 来了短球，冲上去截击
    if situation == "lob":
        return "smash"        # 高球，高压
    return None


@dataclass
class Seat:
    index: int
    team: int
    user_id: int
    name: str
    z: float = 0.0            # 同一队两个人时的左右位置（双打）
    zone: str = "back"        # 当前站位：back / mid / net
    is_ai: bool = False       # 电脑座位（由服务器操作，规则和真人一样）


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
    # 阶段：serve_menu 发球方选 / menu 击球方选 / animating 击球动画 / point_over 一分结束
    phase: str = "idle"
    message: str = ""
    timer: float = 0.0        # 动画或停顿还剩多久
    deadline: float = 0.0     # 选择还剩多久
    score: Score = field(default_factory=Score)
    server_seat: int = 0
    serve_attempt: int = 1
    hitter: Optional[int] = None         # 现在轮到哪个座位选择
    menu_options: List[str] = field(default_factory=list)
    menu_best: Optional[str] = None      # 好选择（只在服务器知道）
    menu_best_p: float = BEST_P
    menu_situation: str = "serve"
    menu_opp_zone: str = "back"
    pending: Optional[Tuple[int, str]] = None   # 动画结束后要结算的一分：(得分队, 原因)
    reserve: bool = False                        # 动画结束后要重新发球（一发失误）
    next_menu: Optional[Tuple[int, str, str]] = None  # 动画结束后轮到的人：(座位, 局面, 对方站位)
    last_seat: Optional[int] = None
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
        z = 0.0 if cap == 2 else (-2.4 if index % 2 == 0 else 2.4)
        return Seat(index, team, user_id, name, z=z)

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
        """新的一分：发球方按局轮换，所有人回到后场。"""
        self.serve_attempt = 1
        order = SERVE_ORDER[self.capacity]
        self.server_seat = order[self.score.total_games % len(order)]
        for s in self.seats:
            if s:
                s.zone = "back"
        self.pending = None
        self.reserve = False
        self.next_menu = None
        self.last_seat = None
        self.ai_timer = 0.0
        self._open_serve_menu()

    def _open_serve_menu(self):
        self.phase = "serve_menu"
        self.hitter = self.server_seat
        self._build_menu("serve", "back")
        self.deadline = MENU_TIME
        self.ai_timer = 0.0

    def _open_rally_menu(self, hitter: int, situation: str, opp_zone: str):
        self.phase = "menu"
        self.hitter = hitter
        self._build_menu(situation, opp_zone)
        self.deadline = MENU_TIME
        self.ai_timer = 0.0

    def _build_menu(self, situation: str, opp_zone: str):
        """给击球方三个选项。好选择一定在里面（如果局面有对口的选项）。"""
        rng = self.rng
        if situation == "serve":
            options = list(SERVE_IDS)
            best = rng.choice(SERVE_IDS)
            best_p = BEST_P
        else:
            pool = POOLS[situation]
            best = tactical_best(situation, opp_zone)
            if best is not None and best in pool:
                others = [o for o in pool if o != best]
                rng.shuffle(others)
                options = [best] + others[:2]
                best_p = BEST_P
            else:
                options = rng.sample(pool, 3)
                best = rng.choice(options)
                best_p = FALLBACK_P
        rng.shuffle(options)
        self.menu_options = options
        self.menu_best = best
        self.menu_best_p = best_p
        self.menu_situation = situation
        self.menu_opp_zone = opp_zone

    # -------------------------------------------------- 玩家的操作

    def choose(self, user_id: int, option: str) -> None:
        """击球方选择一个选项。服务器在这里掷骰子决定成败。"""
        if self.status != "playing":
            raise RoomError("比赛还没开始")
        seat = self.seat_of(user_id)
        if not seat:
            raise RoomError("你不在这个房间里")
        if self.phase not in ("menu", "serve_menu") or seat.index != self.hitter:
            raise RoomError("现在不是你选择的时候")
        if option not in self.menu_options:
            raise RoomError("没有这个选项")
        opt = OPTIONS[option]
        team = seat.team

        if option == self.menu_best:
            p = self.menu_best_p
        else:
            p = SERVE_OTHER_P if self.phase == "serve_menu" else OTHER_P
        fail = None
        if self.rng.random() < p:
            if opt.get("winner") and self.rng.random() < WINNER_P:
                result = "winner"
            else:
                result = "ok"
        else:
            result = "fail"
            fail = opt["fail"]
            if fail == "rand":
                fail = self.rng.choice(["net", "out"])

        # 击球的小人跑到选项要求的位置
        seat.zone = opt["zone"]
        to_team = 1 - team
        if result == "ok":
            to_zone = "back" if opt["next"] in ("deep", "lob") else "mid"
        elif result == "winner":
            to_zone = "back"
        elif fail == "out":
            to_zone = "far"
        else:
            to_zone = "net"

        self.events.append({
            "type": "shot", "seat": seat.index, "option": option, "name": opt["name"],
            "result": result, "fail": fail, "toTeam": to_team, "toZone": to_zone,
            "arc": option in ARC_OPTIONS,
        })
        self.pending = None
        self.reserve = False
        self.next_menu = None
        if result == "winner":
            self.pending = (team, f"{opt['name']}直接得分")
        elif result == "fail":
            if fail == "fault":
                if self.serve_attempt == 1:
                    self.serve_attempt = 2
                    self.reserve = True
                    self.message = "一发失误，请再发一次"
                    self.events.append({"type": "fault", "reason": "一发失误"})
                else:
                    self.pending = (1 - team, "双发失误")
            else:
                word = "下网" if fail == "net" else "出界"
                self.pending = (1 - team, f"{opt['name']}{word}")
        else:
            receiver = self._receiver(to_team)
            self.next_menu = (receiver.index, opt["next"], opt["zone"])
        self.last_seat = seat.index
        self.phase = "animating"
        self.timer = SHOT_TIME

    def _receiver(self, team: int) -> Seat:
        candidates = [s for s in self.seats if s and s.team == team]
        return self.rng.choice(candidates)

    # -------------------------------------------------- 每一帧

    def tick(self, dt: float) -> None:
        if self.status != "playing":
            return
        if self.ai:
            self._ai_step(dt)
        if self.phase in ("menu", "serve_menu"):
            seat = self.seats[self.hitter] if self.hitter is not None else None
            if seat and not seat.is_ai:
                self.deadline -= dt
                if self.deadline <= 0:       # 超时：随机选一个
                    self.choose(seat.user_id, self.rng.choice(self.menu_options))
            return
        if self.phase == "animating":
            self.timer -= dt
            if self.timer <= 0:
                self._finish_shot()
            return
        if self.phase == "point_over":
            self.timer -= dt
            if self.timer <= 0:
                self._next_point()

    def _finish_shot(self):
        """击球动画结束：结算一分，或轮到下一个人选择。"""
        if self.pending:
            winner, reason = self.pending
            self._point(winner, reason)
            return
        if self.reserve:
            self.reserve = False
            self._open_serve_menu()
            return
        if self.next_menu:
            hitter, situation, opp_zone = self.next_menu
            self.next_menu = None
            self._open_rally_menu(hitter, situation, opp_zone)

    def _ai_step(self, dt: float):
        """电脑：轮到它选择时，想一会儿再选。大多数时候选好选择。"""
        seat = self.ai_seat()
        if seat is None:
            return
        if self.phase in ("menu", "serve_menu") and self.hitter == seat.index:
            self.ai_timer += dt
            if self.ai_timer >= AI_THINK:
                self.ai_timer = 0.0
                if self.rng.random() < AI_BEST_P:
                    pick = self.menu_best
                else:
                    pick = self.rng.choice(self.menu_options)
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
                "options": [{"id": o, "name": OPTIONS[o]["name"], "desc": OPTIONS[o]["desc"]}
                            for o in self.menu_options],
                "situation": self.menu_situation,
                "oppZone": self.menu_opp_zone,
                "deadline": round(max(0.0, self.deadline), 2),
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
            "seats": [None if s is None else {
                "index": s.index, "team": s.team, "userId": s.user_id, "name": s.name,
                "isAi": s.is_ai, "zone": s.zone, "z": s.z,
            } for s in self.seats],
            "events": events,
        }


def new_room_id() -> str:
    return secrets.token_hex(4)
