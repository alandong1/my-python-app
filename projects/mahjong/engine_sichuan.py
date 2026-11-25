"""四川麻将（血战到底 / 血流成河）的一局状态机。

和湖北卡五星不同：
- 四个人，只用万条筒（108 张），没有字牌；只能碰、杠、胡，不能吃。
- 开局先换三张，再定缺（缺一门，缺门的牌要打光才能胡）。
- 血战到底：一炮只能一家胡，按打牌顺序第一个能胡的人胡；胡了的人退出，三家胡了或牌墙摸完，一局结束。
- 血流成河：一炮可以多家胡，结束条件同上。
- 花猪（手里有三门花色）赔给每一个其他人，金额按那个人能拿到的最大翻数算。

没有写在规则里、需要你确认的默认做法（见 REQUIREMENTS.md 第 14.1 节）：
- 换三张的方向每局轮换：下家、对家、上家。
- 平胡 1 翻，七对 2 翻，清一色 2 翻，每根（四张一样）+1 翻，自摸 +1 翻；分数 = 2 的翻数次方。
- 没有查大叫。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from . import rules as R
from .engine import GameError

N = 4
SUITS = 3          # 0 万 1 条 2 筒
KINDS = 27         # 四川麻将没有字牌
MODES = ("xuezhan", "xueliu")


def _score(hand: List[int], melds: List[dict], self_draw: bool):
    """番数和分项。hand 是包含胡的那张的暗牌计数。"""
    items = []
    if not melds and all(x % 2 == 0 for x in hand):
        items.append(("七对", 2))
    else:
        items.append(("平胡", 1))
    kinds = [k for k in range(KINDS) if hand[k]] + [m["kind"] for m in melds]
    suits = {k // 9 for k in kinds}
    if len(suits) == 1:
        items.append(("清一色", 2))
    gen = sum(1 for k in range(KINDS) if hand[k] == 4) + sum(1 for m in melds if m["type"].startswith("gang"))
    if gen:
        items.append(("根", gen))
    if self_draw:
        items.append(("自摸", 1))
    fan = sum(v for _, v in items)
    return fan, items


class SichuanRound:
    def __init__(self, dealer: int, rng: Optional[random.Random] = None,
                 mode: str = "xuezhan", exchange_dir: int = 1):
        if mode not in MODES:
            raise GameError("没有这种玩法")
        rng = rng or random.Random()
        self.rng = rng
        self.mode = mode
        self.dealer = dealer
        self.exchange_dir = exchange_dir          # 1 下家 2 对家 3 上家
        self.wall: List[int] = [k for k in range(KINDS) for _ in range(R.COPIES)]
        rng.shuffle(self.wall)
        self.hands: List[List[int]] = [R.counts_of([]) for _ in range(N)]
        self.melds: List[List[dict]] = [[] for _ in range(N)]
        self.discards: List[List[int]] = [[] for _ in range(N)]
        self.missing: List[Optional[int]] = [None] * N
        self.exch: List[Optional[List[int]]] = [None] * N
        self.finished = [False] * N               # 已经胡牌，退出
        self.wins: List[dict] = []                # 胡牌的人（按胡牌先后）
        self.deltas = [0] * N                     # 这一局每人的输赢（付钱时直接记上）
        self.turn = dealer
        self.drawn = False
        self.draw_kind: Optional[int] = None
        self.phase = "exchange"                   # exchange -> ding -> discard
        self.pending: Dict[int, List[str]] = {}
        self.responses: Dict[int, str] = {}
        self.last: Optional[tuple] = None
        self.result: Optional[dict] = None
        self.recorded = False
        self.suits: List[int] = [0, 1, 2]         # 四川：三门都有（界面用）

        for _ in range(13):
            for s in range(N):
                self.hands[s][self.wall.pop()] += 1

    # ------------------------------------------------------------ 换三张、定缺

    def choose_exchange(self, seat: int, kinds: List[int]) -> None:
        if self.phase != "exchange":
            raise GameError("现在不是换三张的时候")
        if self.exch[seat] is not None:
            raise GameError("你已经选过了")
        if len(kinds) != 3:
            raise GameError("请选三张牌")
        c = list(self.hands[seat])
        for k in kinds:
            if not (0 <= k < KINDS) or c[k] <= 0:
                raise GameError("请选手里的牌")
            c[k] -= 1
        self.exch[seat] = list(kinds)
        if all(e is not None for e in self.exch):
            self._apply_exchange()

    def _apply_exchange(self) -> None:
        d = self.exchange_dir
        for s in range(N):
            for k in self.exch[s]:
                self.hands[s][k] -= 1
        for s in range(N):
            target = (s + d) % N
            for k in self.exch[s]:
                self.hands[target][k] += 1
        self.phase = "ding"

    def choose_missing(self, seat: int, suit: int) -> None:
        if self.phase != "ding":
            raise GameError("现在不是定缺的时候")
        if self.missing[seat] is not None:
            raise GameError("你已经定过缺了")
        if suit not in (0, 1, 2):
            raise GameError("缺门只能选万、条或筒")
        self.missing[seat] = suit
        if all(m is not None for m in self.missing):
            self.phase = "discard"
            self._draw_for(self.dealer)

    def pending_ding(self) -> List[int]:
        return [s for s in range(N) if self.missing[s] is None]

    def pending_exchange(self) -> List[int]:
        return [s for s in range(N) if self.exch[s] is None]

    # ------------------------------------------------------------ 摸牌与轮转

    def _alive_after(self, seat: int) -> int:
        """seat 之后的下一位还没有胡牌的人。"""
        for i in range(1, N + 1):
            t = (seat + i) % N
            if not self.finished[t]:
                return t
        return seat

    def _draw_for(self, seat: int) -> None:
        self.turn = seat
        if not self.wall:
            self._end_draw()
            return
        kind = self.wall.pop()
        self.hands[seat][kind] += 1
        self.draw_kind = kind
        self.drawn = True
        self.phase = "discard"

    def _next_turn_from(self, seat: int) -> None:
        self.drawn = False
        if len(self.wins) >= 3:
            self._end_draw()
            return
        self._draw_for(self._alive_after(seat))

    # ------------------------------------------------------------ 胡牌判断

    def _missing_in(self, c: List[int], seat: int) -> bool:
        m = self.missing[seat]
        if m is None:
            return False
        return any(c[k] for k in range(m * 9, m * 9 + 9))

    def _win(self, seat: int, kind: Optional[int], self_draw: bool) -> Optional[dict]:
        c = list(self.hands[seat])
        if kind is not None:
            c[kind] += 1
        if not R.is_win(c, len(self.melds[seat])):
            return None
        if self._missing_in(c, seat):
            return None
        fan, items = _score(c, self.melds[seat], self_draw)
        return {"fan": fan, "points": 2 ** fan, "items": items, "hand": R.expand(c)}

    def _max_points(self, seat: int) -> int:
        """一个人能拿到的最大分数：所有能胡的牌里分数最高的。没有能胡的，按平胡 1 翻算。"""
        best = 2 ** 1
        for k in range(KINDS):
            info = self._win(seat, k, False)
            if info and info["points"] > best:
                best = info["points"]
        return best

    # ------------------------------------------------------------ 出牌与回应

    def discard(self, seat: int, kind: int) -> None:
        if self.phase != "discard" or seat != self.turn:
            raise GameError("现在不是你出牌")
        if self.hands[seat][kind] <= 0:
            raise GameError("手里没有这张牌")
        if self.missing[seat] is not None and R.suit_of(kind) != self.missing[seat]:
            if any(self.hands[seat][k] for k in range(self.missing[seat] * 9, self.missing[seat] * 9 + 9)):
                raise GameError("先把缺门的牌打光")
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
            self._next_turn_from(seat)

    def _claims_for(self, src: int, kind: int) -> Dict[int, List[str]]:
        out: Dict[int, List[str]] = {}
        for t in range(N):
            if t == src or self.finished[t]:
                continue
            acts: List[str] = []
            if self._win(t, kind, False):
                acts.append("hu")
            if self.missing[t] is None or R.suit_of(kind) != self.missing[t]:
                c = self.hands[t]
                if c[kind] >= 3:
                    acts.append("gang_ming")
                if c[kind] >= 2:
                    acts.append("pong")
            if acts:
                out[t] = acts
        return out

    def respond(self, seat: int, action: str) -> None:
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
        order = lambda t: (t - src) % N
        hus = sorted((t for t, a in resp.items() if a == "hu"), key=order)
        if hus:
            if self.mode == "xuezhan":
                hus = hus[:1]                     # 一炮一响：按顺序第一个
            self._win_on_discard(hus, src, kind)
            return
        for want in ("gang_ming", "pong"):
            takers = sorted((t for t, a in resp.items() if a == want), key=order)
            if takers:
                self._meld(takers[0], want, src, kind)
                return
        self._next_turn_from(src)

    def _take_discard(self, src: int, kind: int) -> None:
        pile = self.discards[src]
        idx = len(pile) - 1 - pile[::-1].index(kind)
        del pile[idx]

    def _meld(self, t: int, action: str, src: int, kind: int) -> None:
        self._take_discard(src, kind)
        c = self.hands[t]
        if action == "pong":
            c[kind] -= 2
            self.melds[t].append({"type": "pong", "kind": kind, "from": src})
        else:
            c[kind] -= 3
            self.melds[t].append({"type": "gang_ming", "kind": kind, "from": src})
            self.deltas[src] -= 1                 # 明杠：放杠的人给 1 分
            self.deltas[t] += 1
        self.last = None
        self.drawn = False
        if action == "gang_ming":
            self._draw_for(t)                     # 杠后补牌
        else:
            self.turn = t
            self.phase = "discard"                # 碰后直接打牌

    # ------------------------------------------------------------ 自摸、暗杠、加杠

    def self_options(self, seat: int) -> List[dict]:
        if self.phase != "discard" or seat != self.turn or not self.drawn:
            return []
        opts: List[dict] = []
        if self._win(seat, None, True):
            opts.append({"action": "hu", "kind": None})
        c = self.hands[seat]
        for k in range(KINDS):
            if c[k] == 4 and (self.missing[seat] is None or R.suit_of(k) != self.missing[seat]):
                opts.append({"action": "gang_an", "kind": k})
        for m in self.melds[seat]:
            if m["type"] == "pong" and c[m["kind"]] > 0:
                opts.append({"action": "gang_jia", "kind": m["kind"]})
        return opts

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
            pay = 2
        else:
            self.hands[seat][kind] -= 1
            for m in self.melds[seat]:
                if m["type"] == "pong" and m["kind"] == kind:
                    m["type"] = "gang_jia"
                    break
            pay = 1
        for o in range(N):
            if o != seat:
                self.deltas[o] -= pay
                self.deltas[seat] += pay
        self.drawn = False
        self._draw_for(seat)

    # ------------------------------------------------------------ 结算

    def _win_on_discard(self, hus: List[int], src: int, kind: int) -> None:
        for t in hus:
            info = self._win(t, kind, False)
            self.deltas[src] -= info["points"]          # 点炮：放炮的人付
            self.deltas[t] += info["points"]
            self.finished[t] = True
            self.wins.append({"seat": t, "fan": info["fan"], "points": info["points"],
                              "items": info["items"], "hand": info["hand"], "selfDraw": False})
        self._take_discard(src, kind)
        self.drawn = False
        self.last = None
        self._next_turn_from(src)

    def _win_self(self, seat: int) -> None:
        info = self._win(seat, None, True)
        for o in range(N):
            if o != seat:                                 # 自摸：其他人都付
                self.deltas[o] -= info["points"]
                self.deltas[seat] += info["points"]
        self.finished[seat] = True
        self.wins.append({"seat": seat, "fan": info["fan"], "points": info["points"],
                          "items": info["items"], "hand": info["hand"], "selfDraw": True})
        self.drawn = False
        self._next_turn_from(seat)

    def _end_draw(self) -> None:
        """一局结束（三家胡了，或牌墙摸完）：结算花猪，然后定下结果。"""
        for p in range(N):
            if self.finished[p]:
                continue
            suits = {k // 9 for k in range(KINDS) if self.hands[p][k]}
            suits |= {m["kind"] // 9 for m in self.melds[p]}
            if len(suits) == SUITS:                       # 花猪：三门都有
                for q in range(N):
                    if q != p:
                        amount = self._max_points(q)
                        self.deltas[p] -= amount
                        self.deltas[q] += amount
        self.phase = "over"
        self.pending = {}
        self.responses = {}
        self.drawn = False
        self.result = {
            "type": "win" if self.wins else "draw",
            "winners": self.wins,
            "from": None,
            "deltas": list(self.deltas),
            "tenpai": [],
            "revealed": [R.expand(h) for h in self.hands],
        }


class SichuanMatch:
    """一场四川麻将：若干局，庄家每局轮到下家，换三张的方向每局轮换。"""

    def __init__(self, rounds: int = 4, rng: Optional[random.Random] = None, mode: str = "xuezhan"):
        self.rounds = rounds
        self.rng = rng or random.Random()
        self.mode = mode
        self.round_no = 0
        self.dealer = 0
        self.scores = [0] * N
        self.round: Optional[SichuanRound] = None
        self.history: List[dict] = []

    def begin_round(self) -> SichuanRound:
        self.round_no += 1
        direction = ((self.round_no - 1) % 3) + 1
        self.round = SichuanRound(self.dealer, self.rng, self.mode, direction)
        return self.round

    def record(self) -> bool:
        r = self.round
        if r.recorded or r.phase != "over":
            return False
        r.recorded = True
        for i, d in enumerate(r.result["deltas"]):
            self.scores[i] += d
        self.history.append({
            "round": self.round_no,
            "dealer": self.dealer,
            "suits": [0, 1, 2],
            "type": r.result["type"],
            "from": None,
            "winners": r.result["winners"],
            "deltas": r.result["deltas"],
            "revealed": r.result["revealed"],
        })
        self.dealer = (self.dealer + 1) % N
        return True

    @property
    def finished(self) -> bool:
        return self.round_no >= self.rounds and self.round is not None and self.round.phase == "over"
