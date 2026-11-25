"""一局麻将的状态机（Round）和整场比赛（Match）。

只管规则，不管网络和时间：服务器和电脑玩家都调用这里的方法来出牌、碰、杠、胡。
出错的操作会抛出 GameError，并且不改变牌局状态。

一局的阶段（Round.phase）：
  discard  轮到 Round.turn 这家：摸了牌（drawn=True）就可以自摸、杠，然后打一张
  claim    刚有人打出一张牌，其他家可以胡、碰、杠，等大家都表态后才结算
  over     这一局结束，结果在 Round.result 里
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from . import rules as R


class GameError(Exception):
    """玩家的操作不合规则。"""


class Round:
    def __init__(self, dealer: int, rng: Optional[random.Random] = None):
        rng = rng or random.Random()
        self.wall: List[int] = [k for k in range(R.KINDS) for _ in range(R.COPIES)]
        rng.shuffle(self.wall)
        self.dealer = dealer
        self.hands: List[List[int]] = [R.counts_of([]) for _ in range(4)]   # 暗牌计数
        self.melds: List[List[dict]] = [[] for _ in range(4)]               # 明牌
        self.discards: List[List[int]] = [[] for _ in range(4)]             # 牌河
        self.gang_pay = [0, 0, 0, 0]     # 杠分：这一局里杠牌带来的输赢
        self.turn = dealer
        self.drawn = False               # 当前玩家刚摸了牌（手里多一张）
        self.phase = "discard"
        self.pending: Dict[int, List[str]] = {}   # claim 阶段：谁能吃碰杠胡
        self.responses: Dict[int, str] = {}
        self.last: Optional[tuple] = None         # (座位, 牌种)：最近打出的牌
        self.result: Optional[dict] = None
        self.recorded = False                     # 结果是否已经计入整场比赛

        for _ in range(13):                       # 每家 13 张
            for s in range(4):
                self.hands[s][self.wall.pop()] += 1
        self._draw_for(dealer)                    # 庄家多摸一张

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
        self._draw_for((self.turn + 1) % 4)

    # ------------------------------------------------------------ 查询

    def self_options(self, seat: int) -> List[dict]:
        """摸牌后，seat 能做的自摸、暗杠、加杠。"""
        if self.phase != "discard" or seat != self.turn or not self.drawn:
            return []
        c = self.hands[seat]
        opts: List[dict] = []
        if R.is_win(c, len(self.melds[seat])):
            opts.append({"action": "hu", "kind": None})
        for k in range(R.KINDS):
            if c[k] == 4:
                opts.append({"action": "gang_an", "kind": k})
        for m in self.melds[seat]:
            if m["type"] == "pong" and c[m["kind"]] > 0:
                opts.append({"action": "gang_jia", "kind": m["kind"]})
        return opts

    def visible(self) -> List[int]:
        """所有人都看得见的牌（牌河和明牌），给电脑估算剩余牌用。"""
        v = [0] * R.KINDS
        for s in range(4):
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
        """别人打出 kind 后，每家能做的操作。"""
        out: Dict[int, List[str]] = {}
        for t in range(4):
            if t == src:
                continue
            c = self.hands[t]
            acts: List[str] = []
            c[kind] += 1
            if R.is_win(c, len(self.melds[t])):
                acts.append("hu")
            c[kind] -= 1
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
        order = lambda t: (t - src) % 4   # 离打牌的人越近越优先
        hus = sorted((t for t, a in resp.items() if a == "hu"), key=order)
        if hus:                            # 一炮可以多响
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

    # ------------------------------------------------------------ 自摸、暗杠、加杠

    def act_self(self, seat: int, action: str, kind: Optional[int] = None) -> None:
        opts = self.self_options(seat)
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
            pay_each = 1
        else:                                # gang_jia：碰升级成杠
            self.hands[seat][kind] -= 1
            for m in self.melds[seat]:
                if m["type"] == "pong" and m["kind"] == kind:
                    m["type"] = "gang_jia"
                    break
            pay_each = 1
        for o in range(4):                   # 暗杠、加杠：每家付 1 分
            if o != seat:
                self.gang_pay[o] -= pay_each
                self.gang_pay[seat] += pay_each
        self.drawn = False
        self._draw_for(seat)                 # 杠后补牌

    # ------------------------------------------------------------ 结算

    def _score(self, seat: int, self_draw: bool, win_kind: Optional[int]):
        c = list(self.hands[seat])
        if win_kind is not None:
            c[win_kind] += 1
        fan, items = R.score_win(c, self.melds[seat], self_draw)
        return fan, items, R.expand(c)

    def _win_on_discard(self, hus: List[int], src: int, kind: int) -> None:
        deltas = list(self.gang_pay)
        winners = []
        for t in hus:
            fan, items, hand = self._score(t, False, kind)
            deltas[src] -= fan
            deltas[t] += fan
            winners.append({"seat": t, "fan": fan, "items": items, "hand": hand, "selfDraw": False})
        self._end("win", winners, src, deltas)

    def _win_self(self, seat: int) -> None:
        fan, items, hand = self._score(seat, True, None)
        deltas = list(self.gang_pay)
        for o in range(4):
            if o != seat:
                deltas[o] -= fan
                deltas[seat] += fan
        winners = [{"seat": seat, "fan": fan, "items": items, "hand": hand, "selfDraw": True}]
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
        self.scores = [0, 0, 0, 0]
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
            self.dealer = (self.dealer + 1) % 4

    @property
    def finished(self) -> bool:
        return self.round_no >= self.rounds and self.round is not None and self.round.phase == "over"
