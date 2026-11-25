"""湖北卡五星的牌和规则计算：胡牌判断、向听数（还差几步听牌）、番数。

牌用 0~26 的整数表示（叫「牌种」）：
  0~8   一万 ~ 九万
  9~17  一条 ~ 九条
  18~26 一筒 ~ 九筒
一副牌每种 4 张，共 108 张，没有字牌和花牌。
「五星」指五万、五条、五筒（编号 4、13、22）。

这里是我们目前采用的一版规则，细节见 projects/mahjong/REQUIREMENTS.md 的「规则」一节。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

KINDS = 27          # 牌种数量
COPIES = 4          # 每种几张
FIVE_KINDS = (4, 13, 22)
SUIT_CHARS = "万条筒"


def kind_name(k: int) -> str:
    """牌种编号 -> 显示名，例如 4 -> 五万。"""
    return f"{k % 9 + 1}{SUIT_CHARS[k // 9]}"


def counts_of(kinds: Sequence[int]) -> List[int]:
    """把一组牌种编号变成 27 长度的计数数组。"""
    c = [0] * KINDS
    for k in kinds:
        c[k] += 1
    return c


def expand(counts: Sequence[int]) -> List[int]:
    """计数数组 -> 排好序的牌种列表（给界面用）。"""
    out: List[int] = []
    for k, n in enumerate(counts):
        out.extend([k] * n)
    return out


# ------------------------------------------------------------------ 胡牌判断

def _sets_ok(c: List[int], n: int) -> bool:
    """能否把 c 恰好拆成 n 组（刻子或顺子）。"""
    i = next((j for j in range(KINDS) if c[j]), None)
    if i is None:
        return n == 0
    if n == 0:
        return False
    if c[i] >= 3:
        c[i] -= 3
        ok = _sets_ok(c, n - 1)
        c[i] += 3
        if ok:
            return True
    if i % 9 <= 6 and c[i + 1] and c[i + 2]:
        c[i] -= 1
        c[i + 1] -= 1
        c[i + 2] -= 1
        ok = _sets_ok(c, n - 1)
        c[i] += 1
        c[i + 1] += 1
        c[i + 2] += 1
        if ok:
            return True
    return False


def is_win(c: Sequence[int], melds: int) -> bool:
    """手里的暗牌 c 加上 melds 组明牌（碰或杠）能不能和牌。

    暗牌数量必须正好是 3 * (4 - melds) + 2：每组 3 张，再加一对将。
    和牌牌型：4 组面子 + 1 对将，或者七对（只在没有明牌时）。
    """
    if sum(c) != 3 * (4 - melds) + 2:
        return False
    if melds == 0 and all(x % 2 == 0 for x in c):
        return True  # 七对（一种牌 4 张算两对）
    cc = list(c)
    for p in range(KINDS):
        if cc[p] >= 2:
            cc[p] -= 2
            ok = _sets_ok(cc, 4 - melds)
            cc[p] += 2
            if ok:
                return True
    return False


# ------------------------------------------------------------------ 向听数

@lru_cache(maxsize=None)
def _suit_table(cnt: Tuple[int, ...]) -> Dict[Tuple[int, int], int]:
    """单一花色（9 种牌）的拆法表。

    返回 {(面子数, 是否有对子): 最多能有几个搭子}。
    搭子 = 两张可能成顺或成刻的牌（如 4、5 或 6、6）。
    把三个花色的表合起来，就能算出整手牌的向听数。
    """
    c = list(cnt)
    best: Dict[Tuple[int, int], int] = {}

    def rec(i: int, sets: int, taatsu: int, pair: int) -> None:
        while i < 9 and c[i] == 0:
            i += 1
        if i >= 9:
            key = (sets, pair)
            if best.get(key, -1) < taatsu:
                best[key] = taatsu
            return
        n = c[i]
        if n >= 3:                                  # 刻子
            c[i] -= 3
            rec(i, sets + 1, taatsu, pair)
            c[i] += 3
        if i <= 6 and c[i + 1] and c[i + 2]:        # 顺子
            c[i] -= 1
            c[i + 1] -= 1
            c[i + 2] -= 1
            rec(i, sets + 1, taatsu, pair)
            c[i] += 1
            c[i + 1] += 1
            c[i + 2] += 1
        if sets + taatsu < 4:
            if n >= 2:
                if not pair:                        # 对子（将）
                    c[i] -= 2
                    rec(i, sets, taatsu, 1)
                    c[i] += 2
                c[i] -= 2                           # 对子当搭子
                rec(i, sets, taatsu + 1, pair)
                c[i] += 2
            if i <= 7 and c[i + 1]:                 # 两面搭子 4-5
                c[i] -= 1
                c[i + 1] -= 1
                rec(i, sets, taatsu + 1, pair)
                c[i] += 1
                c[i + 1] += 1
            if i <= 6 and c[i + 2]:                 # 嵌张搭子 4-6
                c[i] -= 1
                c[i + 2] -= 1
                rec(i, sets, taatsu + 1, pair)
                c[i] += 1
                c[i + 2] += 1
        saved = c[i]                                # 这种牌当孤张放弃
        c[i] = 0
        rec(i + 1, sets, taatsu, pair)
        c[i] = saved

    rec(0, 0, 0, 0)
    return best


def shanten(c: Sequence[int], melds: int = 0) -> int:
    """向听数：离听牌还差几步。-1 = 已经和牌，0 = 听牌（一张就能和）。

    c 是暗牌的计数，melds 是已经亮出的面子数（碰或杠）。
    对任意张数的手牌都成立：给电脑选牌时，会拿「打掉一张之后」的手牌来算。
    """
    t1 = _suit_table(tuple(c[0:9]))
    t2 = _suit_table(tuple(c[9:18]))
    t3 = _suit_table(tuple(c[18:27]))
    best = 8
    for (s1, p1), x1 in t1.items():
        for (s2, p2), x2 in t2.items():
            if p1 + p2 > 1:
                continue
            for (s3, p3), x3 in t3.items():
                pair = p1 + p2 + p3
                if pair > 1:
                    continue
                sets = melds + s1 + s2 + s3
                if sets > 4:
                    continue
                taatsu = min(x1 + x2 + x3, 4 - sets)
                v = 8 - 2 * sets - taatsu - pair
                if v < best:
                    best = v
    if melds == 0:  # 七对向听数
        pairs = sum(1 for x in c if x >= 2)
        best = min(best, 6 - min(pairs, 7))
    return best


# ------------------------------------------------------------------ 番数

def score_win(hand: Sequence[int], melds: List[dict], self_draw: bool) -> Tuple[int, List[Tuple[str, int]]]:
    """算一手和牌的番数。

    hand 是和牌时的暗牌计数（包含胡的那张），melds 是明牌列表。
    返回 (总番数, [(名目, 番数), ...])。
    """
    items: List[Tuple[str, int]] = []
    if not melds and all(x % 2 == 0 for x in hand):
        items.append(("七对", 2))
    else:
        items.append(("平胡", 1))
    if self_draw:
        items.append(("自摸", 1))
    fives = sum(hand[k] for k in FIVE_KINDS)
    for m in melds:
        if m["kind"] in FIVE_KINDS:
            fives += 4 if m["type"].startswith("gang") else 3
    if fives:
        items.append(("五星", fives))
    return sum(v for _, v in items), items
