"""电脑玩家的打法（「正常」难度）。

思路：和牌的核心是让向听数尽量小（离听牌还差得少），在向听数相同时，
选择「进张」多的打法（能让向听数变小的牌剩得多，摸到的机会大）。
碰和杠只在能让向听数变好时才做；能和就一定和。

这不是穷举最优解，而是常用的高效打法：每一步都做出当前能算出来的最好选择。
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from . import rules as R


def _best_discard_shanten(h: List[int], melds: int) -> int:
    """假设打掉一张牌，最好能达到的向听数。"""
    best = 99
    for d in range(R.KINDS):
        if h[d]:
            h[d] -= 1
            best = min(best, R.shanten(h, melds))
            h[d] += 1
    return best


def _near_hand(h: Sequence[int], x: int) -> bool:
    """同花色里，x 前后两张（含 x 自己）有没有手牌。"""
    lo = (x // 9) * 9
    return any(h[y] for y in range(max(lo, x - 2), min(lo + 9, x + 3)))


def choose_discard(h: Sequence[int], melds: int, visible: Sequence[int]) -> int:
    """从暗牌里选一张打出去：先看向听数，再看进张数。"""
    h = list(h)
    best_key = None
    best_kind = -1
    for d in range(R.KINDS):
        if not h[d]:
            continue
        h[d] -= 1
        sh = R.shanten(h, melds)
        uke = 0                                  # 进张：能让向听数变小的牌还剩几张
        for x in range(R.KINDS):
            if not _near_hand(h, x):
                continue                          # 同花色里前后两张都没有的牌，不可能帮上忙，跳过省时间
            left = R.COPIES - h[x] - visible[x] - (1 if x == d else 0)
            if left <= 0:
                continue
            h[x] += 1
            if R.shanten(h, melds) < sh:
                uke += left
            h[x] -= 1
        h[d] += 1
        key = (sh, -uke)
        if best_key is None or key < best_key:
            best_key = key
            best_kind = d
    return best_kind


def decide_claim(h: Sequence[int], melds: int, visible: Sequence[int],
                 options: Sequence[str], kind: int) -> str:
    """别人打出一张牌时，选 hu / gang_ming / pong / pass。"""
    if "hu" in options:
        return "hu"
    now = R.shanten(h, melds)
    if "gang_ming" in options:
        h2 = list(h)
        h2[kind] -= 3
        if R.shanten(h2, melds + 1) <= now:
            return "gang_ming"
    if "pong" in options:
        h2 = list(h)
        h2[kind] -= 2
        if _best_discard_shanten(h2, melds + 1) < now:
            return "pong"
    return "pass"


def decide_self(h: Sequence[int], melds: int, visible: Sequence[int],
                options: List[dict]) -> Tuple[str, int]:
    """轮到自己（已摸牌）时，返回 (动作, 牌种)。动作是 hu / gang_an / gang_jia / discard。"""
    for o in options:
        if o["action"] == "hu":
            return "hu", -1
    if options:
        before = _best_discard_shanten(list(h), melds)
        for o in options:
            k = o["kind"]
            h2 = list(h)
            if o["action"] == "gang_an":
                h2[k] -= 4
                if R.shanten(h2, melds + 1) <= before:
                    return "gang_an", k
            else:
                h2[k] -= 1
                if R.shanten(h2, melds) <= before:
                    return "gang_jia", k
    return "discard", choose_discard(h, melds, visible)
