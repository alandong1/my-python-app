"""湖北卡五星（三人版）的牌和规则计算：胡牌判断、向听数、番数。

牌用 0~29 的整数表示（叫「牌种」）：
  0~8    一万 ~ 九万
  9~17   一条 ~ 九条
  18~26  一筒 ~ 九筒
  27~29  中、发、白（字牌只能成刻子或对子，不能成顺子）
一种牌 4 张，共 120 张。没有东南西北，也没有花牌。


这里是按负责人给的规则实现的一版，细节见 projects/mahjong/REQUIREMENTS.md 的「规则」一节。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

KINDS = 30          # 牌种数量
COPIES = 4          # 每种几张
HONOR_START = 27    # 字牌从 27 开始
SUIT_CHARS = "万条筒"
HONOR_NAMES = ("中", "发", "白")
SUIT_NAMES = ("万", "条", "筒")   # 缺门只可能是这三门，字牌不能缺


def suit_of(k: int) -> int:
    """0 万、1 条、2 筒、3 字牌。"""
    return k // 9 if k < HONOR_START else 3


def kind_name(k: int) -> str:
    """牌种编号 -> 显示名，例如 4 -> 五万，27 -> 中。"""
    if k >= HONOR_START:
        return HONOR_NAMES[k - HONOR_START]
    return f"{k % 9 + 1}{SUIT_CHARS[k // 9]}"


def counts_of(kinds: Sequence[int]) -> List[int]:
    """把一组牌种编号变成 30 长度的计数数组。"""
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
    if i < HONOR_START and i % 9 <= 6 and c[i + 1] and c[i + 2]:
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
    """暗牌 c 加上 melds 组明牌（碰或杠）能不能和牌（只看牌型，不看缺门和番数）。

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
def _table(cnt: Tuple[int, ...], honor: bool) -> Dict[Tuple[int, int], int]:
    """单一花色（9 种数牌，或 3 种字牌）的拆法表。

    返回 {(面子数, 是否有对子): 最多能有几个搭子}。
    数牌可以成顺子，搭子包括两面、嵌张和对子；字牌只能成刻子，搭子只有对子。
    """
    c = list(cnt)
    L = len(c)
    best: Dict[Tuple[int, int], int] = {}

    def rec(i: int, sets: int, taatsu: int, pair: int) -> None:
        while i < L and c[i] == 0:
            i += 1
        if i >= L:
            key = (sets, pair)
            if best.get(key, -1) < taatsu:
                best[key] = taatsu
            return
        n = c[i]
        if n >= 3:                                  # 刻子
            c[i] -= 3
            rec(i, sets + 1, taatsu, pair)
            c[i] += 3
        if not honor and i <= L - 3 and c[i + 1] and c[i + 2]:   # 顺子
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
            if not honor and i <= L - 2 and c[i + 1]:    # 两面搭子 4-5
                c[i] -= 1
                c[i + 1] -= 1
                rec(i, sets, taatsu + 1, pair)
                c[i] += 1
                c[i + 1] += 1
            if not honor and i <= L - 3 and c[i + 2]:    # 嵌张搭子 4-6
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
    tables = [
        _table(tuple(c[0:9]), False),
        _table(tuple(c[9:18]), False),
        _table(tuple(c[18:27]), False),
        _table(tuple(c[27:30]), True),
    ]
    # 按花色依次合并：状态是 (面子数, 对子数) -> 最多搭子数
    state: Dict[Tuple[int, int], int] = {(melds, 0): 0}
    for t in tables:
        new: Dict[Tuple[int, int], int] = {}
        for (s, p), tt in state.items():
            for (s2, p2), x in t.items():
                pp = p + p2
                if pp > 1:
                    continue
                key = (s + s2, pp)
                if new.get(key, -1) < tt + x:
                    new[key] = tt + x
        state = new
    best = 8
    for (s, p), tt in state.items():
        if s > 4:
            continue
        taatsu = min(tt, 4 - s)
        best = min(best, 8 - 2 * s - taatsu - p)
    if melds == 0:  # 七对向听数
        pairs = sum(1 for x in c if x >= 2)
        best = min(best, 6 - min(pairs, 7))
    return best


# ------------------------------------------------------------------ 番数

def _one_suit(hand: Sequence[int], melds: List[dict]) -> bool:
    """清一色：所有牌（暗牌加明牌）都是同一门数牌，没有字牌。"""
    kinds = {k for k in range(KINDS) if hand[k]}
    kinds.update(m["kind"] for m in melds)
    if not kinds or any(k >= HONOR_START for k in kinds):
        return False
    return len({suit_of(k) for k in kinds}) == 1


def score_win(hand: Sequence[int], melds: List[dict], self_draw: bool,
              opened: bool = False) -> Tuple[int, List[Tuple[str, int]], int]:
    """算一手和牌的翻数。

    规则：屁胡不翻（底分 1 分）；每一翻，分数翻一倍。
      清一色 2 翻、七对 2 翻、明四归一 1 翻、暗四归一 2 翻，
      自摸 1 翻，明牌 1 翻。
    hand 是和牌时的暗牌计数（包含胡的那张），melds 是明牌列表。

    返回 (总翻数, [(名目, 翻数), ...], 大胡翻数)。
    大胡翻数只算牌型本身（七对、清一色、四归一），不含自摸和明牌。
    它决定能不能点炮：大胡翻数至少 2，或者已经明牌，才能点炮。
    """
    items: List[Tuple[str, int]] = []
    pattern = 0
    if not melds and all(x % 2 == 0 for x in hand):
        items.append(("七对", 2))
        pattern += 2
    if _one_suit(hand, melds):
        items.append(("清一色", 2))
        pattern += 2
    for m in melds:
        if m["type"] == "gang_an":
            items.append(("暗四归一", 2))
            pattern += 2
        elif m["type"] in ("gang_ming", "gang_jia"):
            items.append(("明四归一", 1))
            pattern += 1
    if self_draw:
        items.append(("自摸", 1))
    if opened:
        items.append(("明牌", 1))
    return sum(v for _, v in items), items, pattern
