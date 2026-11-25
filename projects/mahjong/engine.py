"""一局湖北卡五星（三人）的状态机（Round）和整场比赛（Match）。

只管规则，不管网络和时间：服务器和电脑玩家都调用这里的方法。
出错的操作会抛出 GameError，并且不改变牌局状态。

一局的阶段（Round.phase）：
  ding     定缺：每人选一门缺门（万、条、筒），缺门的牌必须先打光才能和牌
  discard  轮到 Round.turn 这家：摸了牌（drawn=True）可以自摸、杠，然后打一张；也可以明牌
  claim    刚有人打出一张牌，其他家可以胡、碰、杠，等大家都表态后才结算
  over     这一局结束，结果在 Round.result 里

和牌规则：
  - 至少两番才能和。屁胡（只有基本的 1 番）只能靠自摸和牌；
    如果这家已经明牌，屁胡也可以让别人点炮。
  - 手里还有缺门的牌，不能和。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from . import rules as R

N_PLAYERS = 3


class GameError(Exception):
    """玩家的操作不合规则。"""


class Round:
    def __init__(self, dealer: int, rng: Optional[random.Random] = None):
        rng = rng or random.Random()
        self.wall: List[int] = [k for k in range(R.KINDS) for _ in range(R.COPIES)]
        rng.shuffle(self.wall)
        self.dealer = dealer
        self.hands: List[List[int]] = [R.counts_of([]) for _ in range(N_PLAYERS)]   # 暗牌计数
        self.melds: List[List[dict]] = [[] for _ in range(N_PLAYERS)]              # 明牌
        self.discards: List[List[int]] = [[] for _ in range(N_PLAYERS)]            # 牌河
        self.missing: List[Optional[int]] = [None] * N_PLAYERS                     # 缺门（0 万 1 条 2 筒）
        self.opened: List[bool] = [False] * N_PLAYERS                              # 是否明牌
        self.gang_pay = [0] * N_PLAYERS    # 杠分：这一局里杠牌带来的输赢
        self.turn = dealer
        self.drawn = False                 # 当前玩家刚摸了牌（手里多一张）
        self.phase = "ding"
        self.pending: Dict[int, List[str]] = {}   # claim 阶段：谁能胡碰杠
        self.responses: Dict[int, str] = {}
        self.last: Optional[tuple] = None         # (座位, 牌种)：最近打出的牌
        self.result: Optional[dict] = None
        self.recorded = False                     # 结果是否已经计入整场比赛

        for _ in range(13):                       # 每家 13 张
            for s in range(N_PLAYERS):
                self.hands[s][self.wall.pop()] += 1
        self._draw_for(dealer)                    # 庄家多摸一张
        self.phase = "ding"                       # 先定缺，定完才开始出牌

    # ------------------------------------------------------------ 定缺

    def pending_ding(self) -> List[int]:
        return [s for s in range(N_PLAYERS) if self.missing[s] is None]

    def choose_missing(self, seat: int, suit: int) -> None:
        if self.phase != "ding":
            raise GameError("现在不是定缺的时候")
        if self.missing[seat] is not None:
            raise GameError("你已经定过缺了")
        if suit not in (0, 1, 2):
            raise GameError("缺门只能选万、条或筒")
        self.missing[seat] = suit
        if not self.pending_ding():
            self.phase = "discard"

    # ------------------------------------------------------------ 摸牌与轮转

    def _draw_for(self, seat: int) -> None:
        """轮到 seat 摸牌。牌墙空了就流局。"""
        self.turn = seat
        if not self.wall:
            self._end_draw()
            return
        self.hands[seat][self.wall.pop()] += 1
        self.drawn = True
        self.phase = "discard"

    def _next_turn(self) -> None:
        self.drawn = False
        self._draw_for((self.turn + 1) % N_PLAYERS)

    # ------------------------------------------------------------ 查询

    def _has_missing(self, c: List[int], seat: int) -> bool:
        m = self.missing[seat]
        if m is None:
            return False
        return any(c[k] for k in range(R.KINDS) if R.suit_of(k) == m)

    def _can_win(self, seat: int, kind: Optional[int], self_draw: bool) -> Optional[dict]:
        """seat 能不能和牌。kind 是别人打出的那张（点炮时），自摸时为 None。

        能和返回 {fan, items, hand}，不能和返回 None。
        """
        c = list(self.hands[seat])
        if kind is not None:
            c[kind] += 1
        if not R.is_win(c, len(self.melds[seat])):
            return None
        if self._has_missing(c, seat):
            return None
        fan, items, base = R.score_win(c, self.melds[seat], self_draw)
        if self_draw or base >= 2 or (base == 1 and self.opened[seat]):
            return {"fan": fan, "items": items, "hand": R.expand(c)}
        return None

    def self_options(self, seat: int) -> List[dict]:
        """轮到 seat 时能做的操作：明牌、自摸、暗杠、加杠。"""
        if self.phase != "discard" or seat != self.turn:
            return []
        opts: List[dict] = []
        if not self.opened[seat]:
            opts.append({"action": "open", "kind": None})
        if not self.drawn:
            return opts
        c = self.hands[seat]
        if self._can_win(seat, None, True):
            opts.append({"action": "hu", "kind": None})
        for k in range(R.KINDS):
            if c[k] == 4 and R.suit_of(k) != self.missing[seat]:
                opts.append({"action": "gang_an", "kind": k})
        for m in self.melds[seat]:
            if m["type"] == "pong" and c[m["kind"]] > 0:
                opts.append({"action": "gang_jia", "kind": m["kind"]})
        return opts

    def visible(self) -> List[int]:
        """所有人都看得见的牌（牌河和明牌），给电脑估算剩余牌用。"""
        v = [0] * R.KINDS
        for s in range(N_PLAYERS):
            for k in self.discards[s]:
                v[k] += 1
            for m in self.melds[s]:
                v[m["kind"]] += 3 if m["type"] == "pong" else 4
        return v

    # ------------------------------------------------------------ 出牌

    def discard(self, seat: int, kind: int) -> None:
        if self.phase != "discard" or seat != self.turn:
            raise GameError("现在不是你出牌")
        if self.hands[seat][kind] <= 0:
            raise GameError("手里没有这张牌")
        self.hands[seat][kind] -= 1
        self.discards[seat].append(kind)
        self.last = (seat, kind)
        self.drawn = False
        claims = self._claims_for(seat, kind)
        if claims:
            self.phase = "claim"
            self.pending = claims
            self.responses = {}
        else:
            self._next_turn()

    def _claims_for(self, src: int, kind: int) -> Dict[int, List[str]]:
        """别人打出 kind 后，每家能做的操作。缺门的牌不能碰和杠。"""
        out: Dict[int, List[str]] = {}
        for t in range(N_PLAYERS):
            if t == src:
                continue
            acts: List[str] = []
            if self._can_win(t, kind, False):
                acts.append("hu")
            if R.suit_of(kind) != self.missing[t]:
                c = self.hands[t]
                if c[kind] >= 3:
                    acts.append("gang_ming")
                if c[kind] >= 2:
                    acts.append("pong")
            if acts:
                out[t] = acts
        return out

    def respond(self, seat: int, action: str) -> None:
        """claim 阶段：seat 选择 hu / pong / gang_ming / pass。全部人表态后结算。"""
        if self.phase != "claim" or seat not in self.pending:
            raise GameError("现在不能操作")
        if action != "pass" and action not in self.pending[seat]:
            raise GameError("这个操作不可以")
        self.responses[seat] = action
        if len(self.responses) == len(self.pending):
            self._resolve_claims()

    def _resolve_claims(self) -> None:
        src, kind = self.last
        resp = self.responses
        self.pending = {}
        self.responses = {}
        order = lambda t: (t - src) % N_PLAYERS   # 离打牌的人越近越优先
        hus = sorted((t for t, a in resp.items() if a == "hu"), key=order)
        if hus:                                   # 一炮可以多响
            self._win_on_discard(hus, src, kind)
            return
        for want in ("gang_ming", "pong"):
            takers = sorted((t for t, a in resp.items() if a == want), key=order)
            if takers:
                self._meld(takers[0], want, src, kind)
                return
        self._next_turn()

    def _meld(self, t: int, action: str, src: int, kind: int) -> None:
        """t 碰或明杠 src 打出的牌。"""
        self.discards[src].pop()
        c = self.hands[t]
        if action == "pong":
            c[kind] -= 2
            self.melds[t].append({"type": "pong", "kind": kind, "from": src})
        else:
            c[kind] -= 3
            self.melds[t].append({"type": "gang_ming", "kind": kind, "from": src})
            self.gang_pay[src] -= 1          # 放杠的人给 1 分
            self.gang_pay[t] += 1
        self.last = None
        self.drawn = False
        if action == "gang_ming":
            self._draw_for(t)                # 杠后从牌墙补一张
        else:
            self.turn = t
            self.phase = "discard"           # 碰后直接打牌，不摸牌

    # ------------------------------------------------------------ 明牌、自摸、暗杠、加杠

    def act_self(self, seat: int, action: str, kind: Optional[int] = None) -> None:
        opts = self.self_options(seat)
        if action == "open":
            if not any(o["action"] == "open" for o in opts):
                raise GameError("现在不能明牌")
            self.opened[seat] = True
            return
        if action == "hu":
            if not any(o["action"] == "hu" for o in opts):
                raise GameError("现在不能胡")
            self._win_self(seat)
            return
        if not any(o["action"] == action and o["kind"] == kind for o in opts):
            raise GameError("现在不能这样杠")
        if action == "gang_an":
            self.hands[seat][kind] -= 4
            self.melds[seat].append({"type": "gang_an", "kind": kind, "from": None})
        else:                                # gang_jia：碰升级成杠
            self.hands[seat][kind] -= 1
            for m in self.melds[seat]:
                if m["type"] == "pong" and m["kind"] == kind:
                    m["type"] = "gang_jia"
                    break
        for o in range(N_PLAYERS):           # 暗杠、加杠：其余每家付 1 分
            if o != seat:
                self.gang_pay[o] -= 1
                self.gang_pay[seat] += 1
        self.drawn = False
        self._draw_for(seat)                 # 杠后补牌

    # ------------------------------------------------------------ 结算

    def _win_on_discard(self, hus: List[int], src: int, kind: int) -> None:
        deltas = list(self.gang_pay)
        winners = []
        for t in hus:
            info = self._can_win(t, kind, False)
            deltas[src] -= info["fan"]
            deltas[t] += info["fan"]
            winners.append({"seat": t, "fan": info["fan"], "items": info["items"],
                            "hand": info["hand"], "selfDraw": False})
        self._end("win", winners, src, deltas)

    def _win_self(self, seat: int) -> None:
        info = self._can_win(seat, None, True)
        deltas = list(self.gang_pay)
        for o in range(N_PLAYERS):
            if o != seat:
                deltas[o] -= info["fan"]
                deltas[seat] += info["fan"]
        winners = [{"seat": seat, "fan": info["fan"], "items": info["items"],
                    "hand": info["hand"], "selfDraw": True}]
        self._end("win", winners, None, deltas)

    def _end_draw(self) -> None:
        self._end("draw", [], None, list(self.gang_pay))

    def _end(self, kind: str, winners: List[dict], src: Optional[int], deltas: List[int]) -> None:
        self.phase = "over"
        self.pending = {}
        self.responses = {}
        self.drawn = False
        self.result = {
            "type": kind,
            "winners": winners,
            "from": src,
            "deltas": deltas,
            "revealed": [R.expand(h) for h in self.hands],
        }


class Match:
    """一场比赛：若干局，庄家轮转，累计分数。"""

    def __init__(self, rounds: int = 4, rng: Optional[random.Random] = None):
        self.rounds = rounds
        self.rng = rng or random.Random()
        self.round_no = 0
        self.dealer = 0
        self.scores = [0] * N_PLAYERS
        self.round: Optional[Round] = None

    def begin_round(self) -> Round:
        self.round_no += 1
        self.round = Round(self.dealer, self.rng)
        return self.round

    def record(self) -> None:
        """一局结束后调用一次：计入分数，决定下一局庄家。"""
        r = self.round
        if r.recorded or r.phase != "over":
            return
        r.recorded = True
        for i, d in enumerate(r.result["deltas"]):
            self.scores[i] += d
        winners = [w["seat"] for w in r.result["winners"]]
        # 庄家和牌或流局就连庄，否则下家坐庄
        if r.result["type"] == "win" and self.dealer not in winners:
            self.dealer = (self.dealer + 1) % N_PLAYERS

    @property
    def finished(self) -> bool:
        return self.round_no >= self.rounds and self.round is not None and self.round.phase == "over"
