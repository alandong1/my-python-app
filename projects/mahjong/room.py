"""房间：3 个座位、房主、电脑补位、出牌节奏和给每位玩家发送的画面。

规则在 engine.py，电脑的打法在 ai.py，这里只负责「谁在哪个座位、轮到谁、什么时候自动操作」。

几个约定：
- 每次牌局有变化，版本号 version 加一。定时任务（电脑出牌、超时）醒来时
  如果发现版本号变了，说明状态已经变化，就什么都不做。
- 所有修改牌局的操作都在 self.lock 里进行，所以不会两个操作同时改状态。
- 真人掉线或中途离开：座位变成电脑「托管」，牌局继续。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List, Optional

from . import ai
from . import rules as R
from .engine import N_PLAYERS, GameError, Match

BOT_DELAY = 0.8          # 电脑出牌前停一下，让玩家看清楚刚发生了什么
DING_TIMEOUT = 20        # 真人定缺的时间（秒），超时由电脑替他选
DISCARD_TIMEOUT = 60     # 真人出牌的时间（秒），超时由电脑代打
CLAIM_TIMEOUT = 25       # 真人决定碰、杠、胡的时间（秒），超时自动「过」
NEXT_ROUND_DELAY = 6     # 一局结束后多久开下一局
ROUND_CHOICES = (1, 4, 8)


class Seat:
    def __init__(self, pid: Optional[str], name: str, ws: Any = None, bot: bool = False):
        self.pid = pid          # 真人的身份标识；电脑没有
        self.name = name
        self.ws = ws
        self.bot = bot


class Room:
    def __init__(self, code: str, rng: Optional[random.Random] = None):
        self.code = code
        self.rounds = 4
        self.seats: List[Optional[Seat]] = [None] * N_PLAYERS
        self.host: Optional[str] = None
        self.match: Optional[Match] = None
        self.version = 0
        self.lock = asyncio.Lock()
        self.rng = rng or random.Random()

    # ------------------------------------------------------------ 座位与状态

    def humans(self) -> List[Seat]:
        return [s for s in self.seats if s is not None and not s.bot]

    def seat_of(self, pid: str) -> Optional[int]:
        for i, s in enumerate(self.seats):
            if s is not None and s.pid == pid:
                return i
        return None

    def state(self) -> str:
        if self.match is None:
            return "waiting"
        if self.match.finished:
            return "match_end"
        if self.match.round.phase == "over":
            return "round_end"
        return "playing"

    def _in_game(self) -> bool:
        return self.state() in ("playing", "round_end")

    def join(self, pid: str, name: str, ws: Any) -> None:
        if self._in_game():
            raise GameError("牌局已经开始，现在不能加入")
        if self.seat_of(pid) is not None:
            return
        for i in range(N_PLAYERS):
            if self.seats[i] is None:
                self.seats[i] = Seat(pid, name, ws)
                if self.host is None:
                    self.host = pid
                return
        raise GameError("房间已满（湖北卡五星是三人玩）")

    def leave(self, pid: str) -> None:
        i = self.seat_of(pid)
        if i is None:
            return
        if self._in_game():
            seat = self.seats[i]
            seat.pid = None
            seat.ws = None
            seat.bot = True
            seat.name = f"{seat.name}（托管）"
        else:
            self.seats[i] = None
        if self.host == pid:
            self.host = next((s.pid for s in self.seats if s and s.pid), None)

    def set_rounds(self, pid: str, rounds: Any) -> None:
        if pid != self.host:
            raise GameError("只有房主能修改局数")
        if self._in_game():
            raise GameError("牌局进行中，不能修改局数")
        if rounds not in ROUND_CHOICES:
            raise GameError("局数只能是 1、4 或 8")
        self.rounds = rounds

    def start(self, pid: str) -> None:
        if pid != self.host:
            raise GameError("只有房主能开始游戏")
        if self._in_game():
            raise GameError("牌局已经在进行中")
        for i in range(N_PLAYERS):
            if self.seats[i] is None:
                self.seats[i] = Seat(None, f"电脑{i + 1}", bot=True)
        self.match = Match(self.rounds, self.rng)
        self.match.begin_round()

    # ------------------------------------------------------------ 对外的入口

    async def handle(self, pid: str, msg: dict) -> None:
        async with self.lock:
            kind = msg.get("type")
            seat = self.seat_of(pid)
            if kind == "start":
                self.start(pid)
            elif kind == "rounds":
                self.set_rounds(pid, msg.get("rounds"))
            elif kind in ("ding", "discard", "self", "claim"):
                if seat is None or self.match is None:
                    raise GameError("你不在牌局里")
                r = self.match.round
                if kind == "ding":
                    r.choose_missing(seat, int(msg.get("suit")))
                elif kind == "discard":
                    r.discard(seat, int(msg.get("kind")))
                elif kind == "self":
                    r.act_self(seat, str(msg.get("action")), msg.get("kind"))
                else:
                    r.respond(seat, str(msg.get("action")))
            else:
                return
            await self._changed()

    async def drop(self, pid: str) -> None:
        """真人断开连接。"""
        async with self.lock:
            if self.seat_of(pid) is None:
                return
            self.leave(pid)
            await self._changed()

    # ------------------------------------------------------------ 变化后的处理

    async def _changed(self) -> None:
        self.version += 1
        if self.match is not None and self.match.round.phase == "over":
            self.match.record()
        await self._broadcast()
        self._schedule()

    def _schedule(self) -> None:
        """看看接下来谁要操作：电脑就安排一次电脑行动，真人就开始计时。"""
        if self.match is None or not self.humans():
            return
        v = self.version
        r = self.match.round
        if r.phase == "over":
            if not self.match.finished:
                asyncio.ensure_future(self._next_round(v))
            return
        if r.phase == "ding":
            waiting = r.pending_ding()
            if any(self.seats[s].bot for s in waiting):
                asyncio.ensure_future(self._bot_turn(v))
            if any(not self.seats[s].bot for s in waiting):
                asyncio.ensure_future(self._human_timeout(v, DING_TIMEOUT))
            return
        if r.phase == "discard":
            if self.seats[r.turn].bot:
                asyncio.ensure_future(self._bot_turn(v))
            else:
                asyncio.ensure_future(self._human_timeout(v, DISCARD_TIMEOUT))
            return
        # claim：等所有人表态
        waiting = [t for t in r.pending if t not in r.responses]
        if any(self.seats[t].bot for t in waiting):
            asyncio.ensure_future(self._bot_turn(v))
        if any(not self.seats[t].bot for t in waiting):
            asyncio.ensure_future(self._human_timeout(v, CLAIM_TIMEOUT))

    async def _bot_turn(self, v: int) -> None:
        await asyncio.sleep(BOT_DELAY)
        async with self.lock:
            if v != self.version:
                return
            self._auto_step(include_humans=False)
            await self._changed()

    async def _human_timeout(self, v: int, seconds: float) -> None:
        await asyncio.sleep(seconds)
        async with self.lock:
            if v != self.version:
                return
            self._auto_step(include_humans=True)
            await self._changed()

    async def _next_round(self, v: int) -> None:
        await asyncio.sleep(NEXT_ROUND_DELAY)
        async with self.lock:
            if v != self.version or self.match is None or self.match.finished:
                return
            self.match.begin_round()
            await self._changed()

    def _auto_step(self, include_humans: bool) -> None:
        """替电脑（以及超时的真人）做一步操作。"""
        r = self.match.round
        if r.phase == "ding":
            for s in r.pending_ding():
                if self.seats[s].bot or include_humans:
                    r.choose_missing(s, ai.choose_missing(r.hands[s]))
        elif r.phase == "claim":
            for t in list(r.pending):
                if r.phase != "claim":
                    break
                if t in r.responses:
                    continue
                if self.seats[t].bot:
                    act = ai.decide_claim(r.hands[t], len(r.melds[t]), r.visible(), r.pending[t],
                                          r.last[1], r.missing[t])
                elif include_humans:
                    act = "hu" if "hu" in r.pending[t] else "pass"   # 真人超时：能胡就胡，否则过
                else:
                    continue
                r.respond(t, act)
        elif r.phase == "discard":
            seat = r.turn
            if not (self.seats[seat].bot or include_humans):
                return
            opts = [o for o in r.self_options(seat) if o["action"] != "open"]
            if self.seats[seat].bot:
                act, kind = ai.decide_self(r.hands[seat], len(r.melds[seat]), r.visible(), opts,
                                           r.missing[seat])
            elif any(o["action"] == "hu" for o in opts):
                act, kind = "hu", -1
            else:
                act, kind = "discard", ai.choose_discard(r.hands[seat], len(r.melds[seat]),
                                                         r.visible(), r.missing[seat])
            if act == "discard":
                r.discard(seat, kind)
            elif act == "hu":
                r.act_self(seat, "hu")
            else:
                r.act_self(seat, act, kind)

    # ------------------------------------------------------------ 发送画面

    async def _broadcast(self) -> None:
        for i, s in enumerate(self.seats):
            if s is not None and s.pid and not s.bot and s.ws is not None:
                try:
                    await s.ws.send_json(self.view(i))
                except Exception:
                    pass

    def view(self, me: Optional[int]) -> Dict[str, Any]:
        """座位 me 的玩家看到的画面：只有自己的暗牌；明牌的人手牌公开。"""
        m = self.match
        d: Dict[str, Any] = {
            "type": "state",
            "code": self.code,
            "state": self.state(),
            "rounds": self.rounds,
            "you": me,
            "isHost": me is not None and self.seats[me].pid == self.host,
            "seats": [None if s is None else {"name": s.name, "bot": s.bot} for s in self.seats],
            "scores": m.scores if m else None,
            "roundNo": m.round_no if m else 0,
            "dealer": m.dealer if m else None,
        }
        if m is not None:
            r = m.round
            claim = []
            if me is not None and r.phase == "claim" and me not in r.responses:
                claim = r.pending.get(me, [])
            d["round"] = {
                "phase": r.phase,
                "turn": r.turn,
                "wall": len(r.wall),
                "discards": r.discards,
                "melds": r.melds,
                "missing": r.missing,
                "opened": r.opened,
                "openHands": [R.expand(r.hands[s]) if r.opened[s] else None for s in range(N_PLAYERS)],
                "handCounts": [sum(h) for h in r.hands],
                "last": list(r.last) if r.last else None,
                "hand": R.expand(r.hands[me]) if me is not None else [],
                "drawn": bool(r.drawn and r.turn == me),
                "self": r.self_options(me) if me is not None else [],
                "claim": claim,
                "result": r.result,
            }
        return d
