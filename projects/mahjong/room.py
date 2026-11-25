"""房间：3 个座位、房主、电脑补位、出牌节奏、积分结算和给每位玩家发送的画面。

规则在 engine.py，电脑的打法在 ai.py，积分和道具在 store.py。这里只负责：
- 谁在哪个座位、谁是房主、房间公开还是私密；
- 轮到谁、什么时候自动操作（电脑行动、真人超时、掉线托管）；
- 每局结束后把积分记进数据库，道具用掉时从数据库扣除。

几个约定：
- 每次牌局有变化，版本号 version 加一。定时任务醒来时如果发现版本号变了，就什么都不做。
- 所有修改牌局的操作都在 self.lock 里进行。
- 座位上的 pid 就是平台账号的 id（字符串）。游客也有账号，所以掉线后用同一个账号可以重连。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool

from . import ai
from . import rules as R
from . import rules_catalog
from . import store
from .engine import ITEM_NAMES, N_PLAYERS, GameError, Match

BOT_DELAY = 0.8          # 电脑出牌前停一下，让玩家看清楚刚发生了什么
DISCARD_TIMEOUT = 60     # 真人出牌的时间（秒），超时由电脑代打
CLAIM_TIMEOUT = 25       # 真人决定碰、杠、胡的时间（秒），超时自动「过」
NEXT_ROUND_DELAY = 6     # 一局结束后多久开下一局
ROUND_CHOICES = (1, 4, 8)
VISIBILITY = ("public", "private")


def _opt_int(v) -> Optional[int]:
    return None if v is None else int(v)


class Seat:
    def __init__(self, pid: Optional[str], name: str, ws: Any = None, bot: bool = False):
        self.pid = pid          # 真人的账号 id；电脑没有
        self.name = name
        self.ws = ws
        self.bot = bot          # 电脑；掉线的真人也会变成 bot（托管），重连后再变回来
        self.away = False       # 是否掉线托管中（只用于显示）


class Room:
    def __init__(self, code: str, visibility: str = "private", rng: Optional[random.Random] = None):
        self.code = code
        self.rule = "hubei"                       # 玩法（目前只有湖北卡五星可以开）
        self.visibility = visibility if visibility in VISIBILITY else "private"
        self.rounds = 4
        self.items_enabled = False
        self.seats: List[Optional[Seat]] = [None] * N_PLAYERS
        self.host: Optional[str] = None
        self.match: Optional[Match] = None
        self.version = 0
        self.lock = asyncio.Lock()
        self.rng = rng or random.Random()
        self._bot_task: Optional[asyncio.Task] = None     # 电脑行动的定时任务
        self._human_task: Optional[asyncio.Task] = None   # 真人超时的定时任务

    # ------------------------------------------------------------ 座位与状态

    def humans(self) -> List[Seat]:
        return [s for s in self.seats if s is not None and s.pid and not s.bot]

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

    def in_game(self) -> bool:
        return self.state() in ("playing", "round_end")

    def summary(self) -> dict:
        """大厅里显示的房间信息。"""
        host = next((s for s in self.seats if s and s.pid == self.host), None)
        return {
            "code": self.code,
            "rule": self.rule,
            "ruleName": rules_catalog.label(self.rule),
            "host": host.name if host else "",
            "seats": sum(1 for s in self.seats if s is not None),
            "rounds": self.rounds,
            "items": self.items_enabled,
        }

    def check_joinable(self, pid: str) -> None:
        """能不能加入（只检查，不改变房间）。"""
        if self.in_game():
            raise GameError("牌局已经开始，现在不能加入")
        if self.seat_of(pid) is not None:
            return
        if all(s is not None for s in self.seats):
            raise GameError("房间已满（湖北卡五星是三人玩）")

    def join(self, pid: str, name: str, ws: Any) -> None:
        self.check_joinable(pid)
        if self.seat_of(pid) is not None:
            return
        for i in range(N_PLAYERS):
            if self.seats[i] is None:
                self.seats[i] = Seat(pid, name, ws)
                if self.host is None:
                    self.host = pid
                return

    def leave(self, pid: str) -> None:
        """真人离开（主动或掉线）。等待中就让出座位；牌局中变成托管，之后可以重连。"""
        i = self.seat_of(pid)
        if i is None:
            return
        seat = self.seats[i]
        if self.in_game():
            seat.ws = None
            seat.bot = True
            seat.away = True
        else:
            self.seats[i] = None
            if self.host == pid:
                self.host = next((s.pid for s in self.seats if s and s.pid), None)

    def reattach(self, pid: str, ws: Any) -> None:
        """掉线的玩家重新连回来：拿回自己的座位。"""
        i = self.seat_of(pid)
        if i is None:
            raise GameError("你不在这个房间里")
        seat = self.seats[i]
        seat.ws = ws
        seat.bot = False
        seat.away = False

    def set_rounds(self, pid: str, rounds: Any) -> None:
        if pid != self.host:
            raise GameError("只有房主能修改局数")
        if self.in_game():
            raise GameError("牌局进行中，不能修改局数")
        if rounds not in ROUND_CHOICES:
            raise GameError("局数只能是 1、4 或 8")
        self.rounds = rounds

    def set_visibility(self, pid: str, visibility: str) -> None:
        if pid != self.host:
            raise GameError("只有房主能修改房间设置")
        if self.in_game():
            raise GameError("牌局进行中，不能修改")
        if visibility not in VISIBILITY:
            raise GameError("房间只能是公开或私密")
        self.visibility = visibility

    async def start(self, pid: str, items: bool) -> None:
        if pid != self.host:
            raise GameError("只有房主能开始游戏")
        if self.in_game():
            raise GameError("牌局已经在进行中")
        for i in range(N_PLAYERS):
            if self.seats[i] is None:
                self.seats[i] = Seat(None, f"电脑{i + 1}", bot=True)
        self.items_enabled = bool(items)
        self.match = Match(self.rounds, self.rng)
        self.match.begin_round(await self._round_items())

    # ------------------------------------------------------------ 道具与积分（数据库）

    async def _round_items(self) -> dict:
        """这一局每个座位能用的道具库存（从数据库读）。"""
        stock: List[Dict[str, int]] = []
        for s in self.seats:
            if s is not None and s.pid and not s.bot and self.items_enabled:
                w = await run_in_threadpool(store.wallet, int(s.pid))
                stock.append({k: n for k, n in w["items"].items() if n > 0})
            else:
                stock.append({})
        return {"enabled": self.items_enabled, "stock": stock}

    async def _award(self, deltas: List[int]) -> None:
        for i, s in enumerate(self.seats):
            if s is not None and s.pid and not s.bot and deltas[i]:
                await run_in_threadpool(store.add_points, int(s.pid), deltas[i])

    # ------------------------------------------------------------ 对外的入口

    async def handle(self, pid: str, msg: dict) -> None:
        async with self.lock:
            kind = msg.get("type")
            seat = self.seat_of(pid)
            if kind == "start":
                await self.start(pid, bool(msg.get("items")))
            elif kind == "rounds":
                self.set_rounds(pid, msg.get("rounds"))
            elif kind == "visibility":
                self.set_visibility(pid, str(msg.get("visibility")))
            elif kind in ("discard", "self", "claim", "item"):
                if seat is None or self.match is None:
                    raise GameError("你不在牌局里")
                r = self.match.round
                if kind == "discard":
                    r.discard(seat, int(msg.get("kind")))
                elif kind == "self":
                    r.act_self(seat, str(msg.get("action")), msg.get("kind"))
                elif kind == "claim":
                    r.respond(seat, str(msg.get("action")))
                else:
                    await self._use_item(seat, pid, r, msg)
            else:
                return
            await self._changed()

    async def _use_item(self, seat: int, pid: str, r, msg: dict) -> None:
        """使用技能：先从数据库扣除库存，操作不合规则再退回去。"""
        item = str(msg.get("item"))
        if item not in ITEM_NAMES:
            raise GameError("没有这个技能")
        uid = int(pid)
        if not await run_in_threadpool(store.consume, uid, item):
            raise GameError("你没有这个技能了")
        try:
            r.use_item(seat, item,
                       kind=_opt_int(msg.get("kind")),
                       src=_opt_int(msg.get("src")),
                       opp=_opt_int(msg.get("opp")))
        except GameError:
            await run_in_threadpool(store.refund, uid, item)
            raise

    async def drop(self, pid: str) -> None:
        """真人断开连接。"""
        async with self.lock:
            self._cancel_timers()
            if self.seat_of(pid) is None:
                return
            self.leave(pid)
            await self._changed()

    async def reconnect(self, pid: str, ws: Any) -> None:
        async with self.lock:
            self.reattach(pid, ws)
            await self._changed()

    async def attach(self, pid: str, name: str, ws: Any, items: Optional[bool] = None) -> None:
        """进入房间（建房、加入）。items 不为 None 时，同时开局（和电脑玩）。"""
        async with self.lock:
            self.join(pid, name, ws)
            if items is not None:
                await self.start(pid, items)
            await self._changed()

    def _cancel_timers(self) -> None:
        """取消还在等的定时任务（状态变了，它们醒来也没用）。"""
        cur = asyncio.current_task()
        for t in (self._bot_task, self._human_task):
            if t is not None and t is not cur and not t.done():
                t.cancel()

    # ------------------------------------------------------------ 变化后的处理

    async def _changed(self) -> None:
        self.version += 1
        if self.match is not None and self.match.round.phase == "over":
            if self.match.record():
                await self._award(self.match.round.result["deltas"])
        await self._broadcast()
        self._schedule()

    def _schedule(self) -> None:
        """看看接下来谁要操作：电脑就安排一次电脑行动，真人就开始计时。"""
        self._cancel_timers()
        if self.match is None or not self.humans():
            return
        v = self.version
        r = self.match.round
        if r.phase == "over":
            if not self.match.finished:
                self._bot_task = asyncio.ensure_future(self._next_round(v))
            return
        if r.phase == "discard":
            seat = r.turn
            # 明牌的人托管：摸什么打什么；只有能暗杠时才让他自己选
            prompt = (not self.seats[seat].bot and r.opened[seat]
                      and any(o["action"] == "gang_an" for o in r.self_options(seat)))
            if self.seats[seat].bot or (r.opened[seat] and not prompt):
                self._bot_task = asyncio.ensure_future(self._bot_turn(v))
            else:
                self._human_task = asyncio.ensure_future(self._human_timeout(v, DISCARD_TIMEOUT))
            return
        # claim：等所有人表态
        waiting = [t for t in r.pending if t not in r.responses]
        if any(self.seats[t].bot for t in waiting):
            self._bot_task = asyncio.ensure_future(self._bot_turn(v))
        if any(not self.seats[t].bot for t in waiting):
            self._human_task = asyncio.ensure_future(self._human_timeout(v, CLAIM_TIMEOUT))

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
            self.match.begin_round(await self._round_items())
            await self._changed()

    def _auto_step(self, include_humans: bool) -> None:
        """替电脑（以及超时的真人）做一步操作。电脑不用道具，超时就直接摸牌。"""
        r = self.match.round
        if r.phase == "claim":
            for t in list(r.pending):
                if r.phase != "claim":
                    break
                if t in r.responses:
                    continue
                if self.seats[t].bot:
                    act = ai.decide_claim(r.hands[t], len(r.melds[t]), r.visible(), r.pending[t],
                                          r.last[1])
                elif include_humans:
                    act = "hu" if "hu" in r.pending[t] else "pass"   # 真人超时：能胡就胡，否则过
                else:
                    continue
                r.respond(t, act)
        elif r.phase == "discard":
            seat = r.turn
            if not (self.seats[seat].bot or r.opened[seat] or include_humans):
                return
            opts = [o for o in r.self_options(seat) if o["action"] != "open"]
            if self.seats[seat].bot:
                act, kind = ai.decide_self(r.hands[seat], len(r.melds[seat]), r.visible(), opts)
            elif any(o["action"] == "hu" for o in opts):
                act, kind = "hu", -1
            elif r.opened[seat]:
                # 明牌的人：摸什么打什么（不能打的话，打一张允许的）
                allowed = r.allowed_discards(seat)
                act = "discard"
                kind = r.draw_kind if r.draw_kind in allowed else allowed[0]
            else:
                act, kind = "discard", ai.choose_discard(r.hands[seat], len(r.melds[seat]), r.visible())
            if act == "discard":
                allowed = r.allowed_discards(seat)          # 对方明牌时，不能打发给他的牌
                if kind not in allowed:
                    kind = allowed[0]
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
            "rule": self.rule,
            "ruleName": rules_catalog.label(self.rule),
            "visibility": self.visibility,
            "state": self.state(),
            "rounds": self.rounds,
            "items": self.items_enabled,
            "you": me,
            "isHost": me is not None and self.seats[me].pid == self.host,
            "seats": [None if s is None else {"name": s.name, "bot": s.bot, "away": s.away}
                      for s in self.seats],
            "scores": m.scores if m else None,
            "roundNo": m.round_no if m else 0,
            "dealer": m.dealer if m else None,
            "history": m.history if m else [],
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
                "suits": r.suits,
                "opened": r.opened,
                "openHands": [R.expand(r.hands[s]) if r.opened[s] else None for s in range(N_PLAYERS)],
                "handCounts": [sum(h) for h in r.hands],
                "last": list(r.last) if r.last else None,
                "hand": R.expand(r.hands[me]) if me is not None else [],
                "drawn": bool(r.drawn and r.turn == me),
                "self": r.self_options(me) if me is not None else [],
                "items": r.item_options(me) if me is not None else [],
                "stock": r.stock[me] if me is not None else {},
                "drawKind": r.draw_kind if (me is not None and r.drawn and r.turn == me) else None,
                "notes": r.notes[me][-6:] if me is not None else [],
                "claim": claim,
                "result": r.result,
            }
        return d
