"""电脑玩家的打法（「正常」难度）。

思路：和牌的核心是让向听数尽量小（离听牌还差得少），在向听数相同时，
选择「进张」多的打法（能让向听数变小的牌剩得多，摸到的机会大）。
碰和杠只在能让向听数变好时才做；能和就一定和。
定缺时选手里最少的一门；缺门的牌一有就先打掉，因为它们不能和牌。

这不是穷举最优解，而是常用的高效打法：每一步都做出当前能算出来的最好选择。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from . import rules as R


def choose_missing(h: Sequence[int]) -> int:
    """定缺：选手里张数最少的那一门（0 万、1 条、2 筒）。"""
    counts = [sum(h[s * 9:(s + 1) * 9]) for s in range(3)]
    return min(range(3), key=lambda s: (counts[s], s))


def _sh(h: Sequence[int], melds: int, missing: Optional[int]) -> int:
    """向听数，不计缺门的牌（缺门的牌一定要打掉，不影响听牌的判断）。"""
    if missing is None:
        return R.shanten(h, melds)
    tmp = list(h)
    for k in range(missing * 9, missing * 9 + 9):
        tmp[k] = 0
    return R.shanten(tmp, melds)


def _best_discard_shanten(h: List[int], melds: int, missing: Optional[int]) -> int:
    """假设打掉一张牌，最好能达到的向听数。"""
    best = 99
    for d in range(R.KINDS):
        if h[d]:
            h[d] -= 1
            best = min(best, _sh(h, melds, missing))
            h[d] += 1
    return best


def _near_hand(h: Sequence[int], x: int) -> bool:
    """同花色里，x 前后两张（含 x 自己）有没有手牌。字牌只看自己。"""
    if x >= R.HONOR_START:
        return h[x] > 0
    lo = (x // 9) * 9
    return any(h[y] for y in range(max(lo, x - 2), min(lo + 9, x + 3)))


def choose_discard(h: Sequence[int], melds: int, visible: Sequence[int],
                   missing: Optional[int] = None) -> int:
    """从暗牌里选一张打出去：先打缺门，再看向听数，最后看进张数。"""
    h = list(h)
    candidates = [d for d in range(R.KINDS) if h[d]]
    if missing is not None:
        lacking = [d for d in candidates if R.suit_of(d) == missing]
        if lacking:
            candidates = lacking
    best_key: Optional[Tuple[int, int]] = None
    best_kind = -1
    for d in candidates:
        h[d] -= 1
        sh = _sh(h, melds, missing)
        uke = 0                                   # 进张：能让向听数变小的牌还剩几张
        for x in range(R.KINDS):
            if R.suit_of(x) == missing or not _near_hand(h, x):
                continue
            left = R.COPIES - h[x] - visible[x] - (1 if x == d else 0)
            if left <= 0:
                continue
            h[x] += 1
            if _sh(h, melds, missing) < sh:
                uke += left
            h[x] -= 1
        h[d] += 1
        key = (sh, -uke)
        if best_key is None or key < best_key:
            best_key = key
            best_kind = d
    return best_kind


def decide_claim(h: Sequence[int], melds: int, visible: Sequence[int],
                 options: Sequence[str], kind: int, missing: Optional[int] = None) -> str:
    """别人打出一张牌时，选 hu / gang_ming / pong / pass。"""
    if "hu" in options:
        return "hu"
    now = _sh(h, melds, missing)
    if "gang_ming" in options:
        h2 = list(h)
        h2[kind] -= 3
        if _sh(h2, melds + 1, missing) <= now:
            return "gang_ming"
    if "pong" in options:
        h2 = list(h)
        h2[kind] -= 2
        if _best_discard_shanten(h2, melds + 1, missing) < now:
            return "pong"
    return "pass"


def decide_self(h: Sequence[int], melds: int, visible: Sequence[int],
                options: List[dict], missing: Optional[int] = None) -> Tuple[str, int]:
    """轮到自己（已摸牌）时，返回 (动作, 牌种)。动作是 hu / gang_an / gang_jia / discard。

    电脑不主动明牌：明牌会让别人知道手牌，对电脑的打法没有好处。
    """
    for o in options:
        if o["action"] == "hu":
            return "hu", -1
    gangs = [o for o in options if o["action"] in ("gang_an", "gang_jia")]
    if gangs:
        before = _best_discard_shanten(list(h), melds, missing)
        for o in gangs:
            k = o["kind"]
            h2 = list(h)
            if o["action"] == "gang_an":
                h2[k] -= 4
                if _sh(h2, melds + 1, missing) <= before:
                    return "gang_an", k
            else:
                h2[k] -= 1
                if _sh(h2, melds, missing) <= before:
                    return "gang_jia", k
    return "discard", choose_discard(h, melds, visible, missing)
