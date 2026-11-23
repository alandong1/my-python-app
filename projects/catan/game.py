"""卡坦岛的规则引擎：纯 Python，不涉及网络，可以直接单元测试。

所有玩家的操作都通过 Game 的方法完成，方法里做完全部检查才会修改状态；
检查不过就抛出 GameError（带中文提示），状态保持不变。

对外统一用「座位号」（0, 1, 2, 3，也就是玩家在桌子上的位置）表示玩家；
账号 ID（uid）只在服务器内部用来认人，不发给其他玩家。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

from . import config as C
from .board import Board, generate


class GameError(Exception):
    """操作不合法（例如钱不够、位置不对）。消息会直接显示给玩家。"""


def _cards(d: Optional[dict]) -> Dict[str, int]:
    """把玩家发来的资源字典整理成 {资源名: 非负整数}，不合法就报错。"""
    out = {r: 0 for r in C.RESOURCES}
    for k, v in (d or {}).items():
        if k not in out:
            raise GameError("资源名不对")
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise GameError("数量要是非负整数")
        out[k] = v
    return out


def _total(d: Dict[str, int]) -> int:
    return sum(d.values())


class Seat:
    """一位玩家的状态。"""

    def __init__(self, uid: int, name: str, index: int):
        self.uid = uid
        self.name = name
        self.index = index
        self.hand: Dict[str, int] = {r: 0 for r in C.RESOURCES}
        self.dev: Dict[str, int] = {}        # 可以打出的发展卡（上一回合及以前买的）
        self.dev_new: Dict[str, int] = {}    # 这一回合刚买的（要到下一回合才能打出）
        self.knights = 0                     # 已经打出的骑士数
        self.roads_left = C.PIECE_LIMIT["road"]
        self.settlements_left = C.PIECE_LIMIT["settlement"]
        self.cities_left = C.PIECE_LIMIT["city"]
        self.has_longest = False
        self.has_army = False


class Game:
    def __init__(self, players: Sequence[Tuple[int, str]], rng: Optional[random.Random] = None):
        if not C.MIN_PLAYERS <= len(players) <= C.MAX_PLAYERS:
            raise ValueError("人数不对")
        self.rng = rng or random.Random()
        self.board: Board = generate(self.rng)
        order = list(players)
        self.rng.shuffle(order)                  # 随机决定座位
        self.seats: List[Seat] = [Seat(uid, name, i) for i, (uid, name) in enumerate(order)]
        n = len(self.seats)

        self.buildings: Dict[int, Tuple[int, str]] = {}   # 顶点 id → (座位, "settlement" / "city")
        self.roads: Dict[int, int] = {}                   # 边 id → 座位
        self.bank: Dict[str, int] = {r: C.BANK_START for r in C.RESOURCES}
        deck = [k for k, cnt in C.DEV_DECK.items() for _ in range(cnt)]
        self.rng.shuffle(deck)
        self.dev_deck: List[str] = deck
        self.robber: int = self.board.desert()

        # 阶段：setup（开局摆子）→ roll（等待掷骰子）→ play（行动）
        #       discard（7 点后弃牌）、robber（移动强盗）、road_building（道路建设卡）→ ended
        self.phase = "setup"
        self.turn = 0
        self.turn_count = 0
        self.setup_order = list(range(n)) + list(reversed(range(n)))  # 蛇形顺序：来一圈，再倒回来
        self.setup_step = 0
        self.setup_sub = "settlement"           # 这一步先放村庄，再放道路
        self.last_settlement: Optional[int] = None
        self.turn = self.setup_order[0]
        self.dice: Optional[List[int]] = None
        self.discard_need: Dict[int, int] = {}  # 座位 → 需要弃几张
        self.resume = "play"                    # 移动强盗之后回到哪个阶段
        self.road_left = 0                      # 道路建设卡还能放几条路
        self.trade: Optional[dict] = None       # 玩家之间的交易提议
        self.dev_played_turn = -1               # 这一回合已经打出过发展卡（每回合只能一张）
        self.winner: Optional[int] = None
        self.log_lines: List[str] = []

    # ------------------------------------------------------------ 小工具

    def _log(self, text: str):
        self.log_lines.append(text)
        del self.log_lines[:-60]

    def _seat(self, uid: int) -> Seat:
        for s in self.seats:
            if s.uid == uid:
                return s
        raise GameError("你不在这局游戏里")

    def _my_turn(self, uid: int) -> Seat:
        s = self._seat(uid)
        if s.index != self.turn:
            raise GameError("现在不是你的回合")
        return s

    def _require(self, *phases: str):
        if self.phase not in phases:
            raise GameError("现在不能做这个操作")

    def _pay(self, s: Seat, cost: Dict[str, int]):
        for r, n in cost.items():
            if s.hand[r] < n:
                raise GameError("资源不够")
        for r, n in cost.items():
            s.hand[r] -= n
            self.bank[r] += n

    def _vertex_owner(self, vid: int) -> Optional[int]:
        b = self.buildings.get(vid)
        return b[0] if b else None

    def _spaced(self, vid: int) -> bool:
        """距离规则：村庄不能放在已有村庄/城市的角上，或它的相邻角上。"""
        if vid in self.buildings:
            return False
        return all(n not in self.buildings for n in self.board.vertices[vid]["adj"])

    def _connected_to(self, idx: int, vid: int) -> bool:
        """顶点 vid 是否和座位 idx 的道路连着（或本身就是它的建筑）。
        别人的村庄会切断道路：角上是别人的建筑时，不能从那里继续连路。"""
        owner = self._vertex_owner(vid)
        if owner is not None:
            return owner == idx
        return any(self.roads.get(e) == idx for e in self.board.vertices[vid]["edges"])

    def _road_legal(self, idx: int, eid: int) -> bool:
        if eid in self.roads:
            return False
        e = self.board.edges[eid]
        return self._connected_to(idx, e["a"]) or self._connected_to(idx, e["b"])

    def _settlement_legal_main(self, idx: int, vid: int) -> bool:
        if not self._spaced(vid):
            return False
        return any(self.roads.get(e) == idx for e in self.board.vertices[vid]["edges"])

    def _ports(self, idx: int) -> set:
        """这位玩家拥有的港口类型（港口的两个角上有他的建筑）。"""
        out = set()
        for h in self.board.harbors:
            e = self.board.edges[h["edge"]]
            if self._vertex_owner(e["a"]) == idx or self._vertex_owner(e["b"]) == idx:
                out.add(h["type"])
        return out

    def trade_rate(self, idx: int, give: str) -> int:
        """用 give 资源向银行换 1 张，需要几张：有对应港口 2 张，有任意港口 3 张，否则 4 张。"""
        ports = self._ports(idx)
        if give in ports:
            return 2
        if "any" in ports:
            return 3
        return 4

    def vp(self, s: Seat, hidden: bool = True) -> int:
        """胜利点。hidden=True 时包含手里的胜利点发展卡（别人看不到，但赢的时候要算）。"""
        points = sum(1 if t == "settlement" else 2
                     for (o, t) in self.buildings.values() if o == s.index)
        points += 2 * s.has_longest + 2 * s.has_army
        if hidden:
            points += s.dev.get("vp", 0) + s.dev_new.get("vp", 0)
        return points

    def _check_win(self, s: Seat):
        if self.vp(s) >= C.VP_TO_WIN and self.winner is None:
            self.winner = s.index
            self.phase = "ended"
            self._log(f"🏆 {s.name} 获得 {C.VP_TO_WIN} 分，赢得了胜利！")

    # ------------------------------------------------------------ 最长道路 / 最大骑士团

    def _longest_road(self, idx: int) -> int:
        """这位玩家最长的一条连续道路（路上不能穿过别人的建筑）。"""
        mine = [e for e, o in self.roads.items() if o == idx]
        if not mine:
            return 0
        adj: Dict[int, List[int]] = {}
        for e in mine:
            ed = self.board.edges[e]
            adj.setdefault(ed["a"], []).append(e)
            adj.setdefault(ed["b"], []).append(e)
        best = 0

        def dfs(v: int, used: set):
            nonlocal best
            best = max(best, len(used))
            # 走到别人的建筑处就停在这里，不能再往外走
            if used and self._vertex_owner(v) not in (None, idx):
                return
            for e in adj.get(v, []):
                if e in used:
                    continue
                ed = self.board.edges[e]
                nxt = ed["b"] if ed["a"] == v else ed["a"]
                used.add(e)
                dfs(nxt, used)
                used.remove(e)

        for v in adj:
            dfs(v, set())
        return best

    @staticmethod
    def _award(holder: Optional[int], values: List[int], minimum: int) -> Optional[int]:
        """奖励归属：达到最低要求的最高者拿。平手时，原持有人保留；否则无人持有。"""
        best = max(values)
        if best < minimum:
            return None
        top = [i for i, v in enumerate(values) if v == best]
        if holder is not None and values[holder] == best:
            return holder
        return top[0] if len(top) == 1 else None

    def _update_awards(self):
        roads = self._award(self._holder("longest"), [self._longest_road(s.index) for s in self.seats],
                            C.LONGEST_ROAD_MIN)
        army = self._award(self._holder("army"), [s.knights for s in self.seats], C.LARGEST_ARMY_MIN)
        for s in self.seats:
            s.has_longest = (s.index == roads)
            s.has_army = (s.index == army)

    def _holder(self, which: str) -> Optional[int]:
        for s in self.seats:
            if (which == "longest" and s.has_longest) or (which == "army" and s.has_army):
                return s.index
        return None

    # ------------------------------------------------------------ 开局摆子

    def setup_settlement(self, uid: int, vid: int):
        self._require("setup")
        s = self._seat(uid)
        if s.index != self.setup_order[self.setup_step] or self.setup_sub != "settlement":
            raise GameError("现在不是你放村庄")
        if not (0 <= vid < len(self.board.vertices)) or not self._spaced(vid):
            raise GameError("这里不能放村庄（已被占，或离别人太近）")
        self.buildings[vid] = (s.index, "settlement")
        s.settlements_left -= 1
        self.last_settlement = vid
        # 第二轮放的村庄，马上拿到它周围地块的资源
        if self.setup_step >= len(self.seats):
            for hid in self.board.vertices[vid]["hexes"]:
                res = C.TERRAIN_RESOURCE.get(self.board.hexes[hid]["terrain"])
                if res and self.bank[res] > 0:
                    s.hand[res] += 1
                    self.bank[res] -= 1
        self.setup_sub = "road"
        self._log(f"{s.name} 放下了村庄")

    def setup_road(self, uid: int, eid: int):
        self._require("setup")
        s = self._seat(uid)
        if s.index != self.setup_order[self.setup_step] or self.setup_sub != "road":
            raise GameError("现在不是你放道路")
        if not (0 <= eid < len(self.board.edges)) or eid in self.roads:
            raise GameError("这条路不能放")
        ed = self.board.edges[eid]
        if self.last_settlement not in (ed["a"], ed["b"]):
            raise GameError("开局的道路要连着刚放的村庄")
        self.roads[eid] = s.index
        s.roads_left -= 1
        self.setup_step += 1
        self.setup_sub = "settlement"
        if self.setup_step == len(self.setup_order):
            self.phase = "roll"
            self.turn = 0                     # 蛇形顺序的最后一位是 0 号，由他先掷骰子
            self._log("开局摆子完成，游戏开始！")
        else:
            self.turn = self.setup_order[self.setup_step]
        self._update_awards()

    # ------------------------------------------------------------ 掷骰子与产出

    def roll(self, uid: int):
        self._require("roll")
        s = self._my_turn(uid)
        d = [self.rng.randint(1, 6), self.rng.randint(1, 6)]
        self.dice = d
        total = sum(d)
        self._log(f"{s.name} 掷出了 {d[0]} + {d[1]} = {total}")
        if total == 7:
            self.discard_need = {st.index: _total(st.hand) // 2
                                 for st in self.seats if _total(st.hand) > 7}
            self.resume = "play"
            if self.discard_need:
                self.phase = "discard"
                self._log("掷出了 7：手牌超过 7 张的玩家需要弃牌")
            else:
                self.phase = "robber"
        else:
            self._produce(total)
            self.phase = "play"

    def _produce(self, total: int):
        """按点数发放资源。银行不够时：如果只有一个人应得这种资源，就给剩下的；有多人应得，谁也拿不到。"""
        want: Dict[str, Dict[int, int]] = {r: {} for r in C.RESOURCES}
        for h in self.board.hexes:
            if h["number"] != total or h["id"] == self.robber:
                continue
            res = C.TERRAIN_RESOURCE.get(h["terrain"])
            if not res:
                continue
            for vid in h["corners"]:
                b = self.buildings.get(vid)
                if b:
                    amount = 2 if b[1] == "city" else 1
                    want[res][b[0]] = want[res].get(b[0], 0) + amount
        for res, per_seat in want.items():
            demand = sum(per_seat.values())
            if demand == 0:
                continue
            if demand > self.bank[res]:
                if len(per_seat) > 1:
                    self._log(f"银行的{C.RESOURCE_NAMES[res]}不够分，本次没人拿到")
                    continue
                per_seat = {k: min(v, self.bank[res]) for k, v in per_seat.items()}
            for idx, n in per_seat.items():
                self.seats[idx].hand[res] += n
                self.bank[res] -= n

    # ------------------------------------------------------------ 弃牌与强盗

    def discard(self, uid: int, cards: Optional[dict]):
        self._require("discard")
        s = self._seat(uid)
        if s.index not in self.discard_need:
            raise GameError("你不需要弃牌")
        need = self.discard_need[s.index]
        pick = _cards(cards)
        if _total(pick) != need:
            raise GameError(f"需要弃 {need} 张")
        for r, n in pick.items():
            if s.hand[r] < n:
                raise GameError("手牌不够")
        for r, n in pick.items():
            s.hand[r] -= n
            self.bank[r] += n
        del self.discard_need[s.index]
        self._log(f"{s.name} 弃了 {need} 张牌")
        if not self.discard_need:
            self.phase = "robber"

    def _victims(self, hid: int, me: int) -> List[int]:
        """强盗放在这个地块上，周围可以被抢的玩家（有村庄/城市，并且有手牌）。"""
        found = set()
        for vid in self.board.hexes[hid]["corners"]:
            o = self._vertex_owner(vid)
            if o is not None and o != me and _total(self.seats[o].hand) > 0:
                found.add(o)
        return sorted(found)

    def move_robber(self, uid: int, hid: int, victim: Optional[int] = None):
        """移动强盗并抢劫。victim 是被抢玩家的座位号；只有一个人可抢时可以不填。"""
        self._require("robber")
        s = self._my_turn(uid)
        if not (0 <= hid < len(self.board.hexes)) or hid == self.robber:
            raise GameError("强盗必须放到另一个地块上")
        cands = self._victims(hid, s.index)
        if cands:                                   # 先全部检查，再修改状态
            if victim is None:
                if len(cands) > 1:
                    raise GameError("请选择要抢劫的玩家")
                victim = cands[0]
            if victim not in cands:
                raise GameError("这位玩家不能被抢")
        self.robber = hid
        if cands:
            target = self.seats[victim]
            pool = [r for r in C.RESOURCES for _ in range(target.hand[r])]
            stolen = self.rng.choice(pool)
            target.hand[stolen] -= 1
            s.hand[stolen] += 1
            self._log(f"{s.name} 从 {target.name} 抢走了一张牌")
        else:
            self._log(f"{s.name} 移动了强盗")
        self.phase = self.resume

    # ------------------------------------------------------------ 建造

    def build_road(self, uid: int, eid: int):
        self._require("play")
        s = self._my_turn(uid)
        if s.roads_left <= 0:
            raise GameError("道路已经用完")
        if not (0 <= eid < len(self.board.edges)) or not self._road_legal(s.index, eid):
            raise GameError("这里不能造路（要连着自己的路或村庄）")
        self._pay(s, C.COST["road"])
        self._place_road(s, eid)
        self._log(f"{s.name} 造了一条路")
        self._after_build(s)

    def _place_road(self, s: Seat, eid: int):
        self.roads[eid] = s.index
        s.roads_left -= 1

    def build_settlement(self, uid: int, vid: int):
        self._require("play")
        s = self._my_turn(uid)
        if s.settlements_left <= 0:
            raise GameError("村庄已经用完")
        if not (0 <= vid < len(self.board.vertices)) or not self._settlement_legal_main(s.index, vid):
            raise GameError("这里不能放村庄（要连着自己的路，并且离别人至少隔一个角）")
        self._pay(s, C.COST["settlement"])
        self.buildings[vid] = (s.index, "settlement")
        s.settlements_left -= 1
        self._log(f"{s.name} 建了一个村庄")
        self._after_build(s)

    def build_city(self, uid: int, vid: int):
        self._require("play")
        s = self._my_turn(uid)
        if s.cities_left <= 0:
            raise GameError("城市已经用完")
        if self.buildings.get(vid) != (s.index, "settlement"):
            raise GameError("只能把自己的村庄升级成城市")
        self._pay(s, C.COST["city"])
        self.buildings[vid] = (s.index, "city")
        s.cities_left -= 1
        s.settlements_left += 1          # 村庄退回来
        self._log(f"{s.name} 把村庄升级成了城市")
        self._after_build(s)

    def _after_build(self, s: Seat):
        self._update_awards()
        self._check_win(s)

    def legal_vertices_for_settlement(self, idx: int) -> List[int]:
        return [v["id"] for v in self.board.vertices if self._settlement_legal_main(idx, v["id"])]

    def legal_edges_for_road(self, idx: int) -> List[int]:
        return [e["id"] for e in self.board.edges if self._road_legal(idx, e["id"])]

    def buy_dev(self, uid: int):
        self._require("play")
        s = self._my_turn(uid)
        if not self.dev_deck:
            raise GameError("发展卡已经卖完了")
        self._pay(s, C.COST["dev"])
        kind = self.dev_deck.pop()
        s.dev_new[kind] = s.dev_new.get(kind, 0) + 1
        self._log(f"{s.name} 买了一张发展卡")
        self._check_win(s)

    # ------------------------------------------------------------ 发展卡

    def _use_dev(self, s: Seat, kind: str):
        if self.dev_played_turn == self.turn_count:
            raise GameError("每回合只能打出一张发展卡")
        if s.dev.get(kind, 0) < 1:
            raise GameError("没有这张发展卡（刚买的要到下一回合才能用）")
        s.dev[kind] -= 1
        if s.dev[kind] == 0:
            del s.dev[kind]
        self.dev_played_turn = self.turn_count

    def play_knight(self, uid: int):
        self._require("roll", "play")
        s = self._my_turn(uid)
        self._use_dev(s, "knight")
        s.knights += 1
        self._update_awards()
        self._log(f"{s.name} 打出了骑士，移动强盗")
        self.resume = self.phase
        self.phase = "robber"
        self._check_win(s)

    def play_road_building(self, uid: int):
        self._require("play")
        s = self._my_turn(uid)
        if s.roads_left <= 0:
            raise GameError("道路已经用完")
        self._use_dev(s, "road_building")
        self._log(f"{s.name} 打出了道路建设")
        self.road_left = min(2, s.roads_left)
        self.phase = "road_building"
        if not self.legal_edges_for_road(s.index):
            self._end_road_building()

    def place_free_road(self, uid: int, eid: int):
        self._require("road_building")
        s = self._my_turn(uid)
        if not (0 <= eid < len(self.board.edges)) or not self._road_legal(s.index, eid):
            raise GameError("这里不能造路")
        self._place_road(s, eid)
        self.road_left -= 1
        self._update_awards()
        self._check_win(s)
        if self.phase == "road_building" and (self.road_left == 0 or s.roads_left == 0
                                              or not self.legal_edges_for_road(s.index)):
            self._end_road_building()

    def _end_road_building(self):
        self.road_left = 0
        self.phase = "play"

    def year_of_plenty(self, uid: int, first: str, second: str):
        self._require("play")
        s = self._my_turn(uid)
        want = {r: 0 for r in C.RESOURCES}
        for r in (first, second):
            if r not in want:
                raise GameError("资源名不对")
            want[r] += 1
        for r, n in want.items():          # 先检查，全部通过才消耗发展卡
            if self.bank[r] < n:
                raise GameError("银行的这种资源不够")
        self._use_dev(s, "year_of_plenty")
        for r, n in want.items():
            self.bank[r] -= n
            s.hand[r] += n
        self._log(f"{s.name} 打出了丰收之年，从银行拿了两张牌")

    def monopoly(self, uid: int, res: str):
        self._require("play")
        s = self._my_turn(uid)
        if res not in C.RESOURCES:
            raise GameError("资源名不对")
        self._use_dev(s, "monopoly")
        got = 0
        for other in self.seats:
            if other is not s:
                got += other.hand[res]
                other.hand[res] = 0
        s.hand[res] += got
        self._log(f"{s.name} 打出了垄断，拿走了所有{C.RESOURCE_NAMES[res]}（{got} 张）")

    # ------------------------------------------------------------ 交易

    def bank_trade(self, uid: int, give: str, get: str):
        self._require("play")
        s = self._my_turn(uid)
        if give not in C.RESOURCES or get not in C.RESOURCES:
            raise GameError("资源名不对")
        if give == get:
            raise GameError("不能用同一种资源换")
        rate = self.trade_rate(s.index, give)
        if s.hand[give] < rate:
            raise GameError(f"需要 {rate} 张{C.RESOURCE_NAMES[give]}才能换 1 张")
        if self.bank[get] < 1:
            raise GameError("银行没有这种资源了")
        s.hand[give] -= rate
        self.bank[give] += rate
        s.hand[get] += 1
        self.bank[get] -= 1
        self._log(f"{s.name} 用 {rate} 张{C.RESOURCE_NAMES[give]}向银行换了 1 张{C.RESOURCE_NAMES[get]}")

    def offer_trade(self, uid: int, give: Optional[dict], want: Optional[dict]):
        self._require("play")
        s = self._my_turn(uid)
        if self.trade:
            raise GameError("已经有一个交易在进行中")
        g, w = _cards(give), _cards(want)
        if _total(g) == 0 or _total(w) == 0:
            raise GameError("交易的两边都要有资源")
        for r, n in g.items():
            if s.hand[r] < n:
                raise GameError("你的手牌不够这个交易")
        self.trade = {"from": s.index, "give": g, "want": w, "accepted": []}
        self._log(f"{s.name} 发起了交易提议")

    def accept_trade(self, uid: int):
        self._require("play")
        s = self._seat(uid)
        if not self.trade:
            raise GameError("现在没有交易")
        if s.index == self.trade["from"]:
            raise GameError("不能接受自己的交易")
        for r, n in self.trade["want"].items():
            if s.hand[r] < n:
                raise GameError("你的手牌不够接受这个交易")
        if s.index not in self.trade["accepted"]:
            self.trade["accepted"].append(s.index)
        self._log(f"{s.name} 同意了交易")

    def confirm_trade(self, uid: int, partner: int):
        self._require("play")
        s = self._my_turn(uid)
        t = self.trade
        if not t or t["from"] != s.index:
            raise GameError("现在没有你发起的交易")
        if partner not in t["accepted"]:
            raise GameError("这位玩家还没有同意交易")
        other = self.seats[partner]
        for r, n in t["give"].items():
            if s.hand[r] < n:
                raise GameError("你的手牌不够")
        for r, n in t["want"].items():
            if other.hand[r] < n:
                raise GameError(f"{other.name} 的手牌不够了")
        for r, n in t["give"].items():
            s.hand[r] -= n
            other.hand[r] += n
        for r, n in t["want"].items():
            other.hand[r] -= n
            s.hand[r] += n
        self.trade = None
        self._log(f"{s.name} 和 {other.name} 完成了交易")

    def cancel_trade(self, uid: int):
        self._require("play")
        s = self._my_turn(uid)
        if not self.trade or self.trade["from"] != s.index:
            raise GameError("现在没有你发起的交易")
        self.trade = None

    # ------------------------------------------------------------ 结束回合

    def end_turn(self, uid: int):
        self._require("play")
        s = self._my_turn(uid)
        self.trade = None
        for k, n in s.dev_new.items():
            s.dev[k] = s.dev.get(k, 0) + n
        s.dev_new = {}
        self.turn = (self.turn + 1) % len(self.seats)
        self.turn_count += 1
        self.dice = None
        self.phase = "roll"
        self._log(f"轮到 {self.seats[self.turn].name}")

    # ------------------------------------------------------------ 发给玩家的视图

    def view(self, uid: int, online: set) -> dict:
        """某个玩家能看到的全部信息。别人的手牌和发展卡只给数量；看不见的东西不发过去。"""
        me = self._seat(uid)
        legal = self._legal_for(me)
        players = []
        for s in self.seats:
            players.append({
                "seat": s.index, "name": s.name, "color": C.PLAYER_COLORS[s.index],
                "colorName": C.PLAYER_COLOR_NAMES[s.index], "online": s.uid in online,
                "cards": _total(s.hand), "devCount": sum(s.dev.values()) + sum(s.dev_new.values()),
                "knights": s.knights, "vp": self.vp(s, hidden=False),
                "longest": s.has_longest, "army": s.has_army,
                "roadsLeft": s.roads_left, "settlementsLeft": s.settlements_left,
                "citiesLeft": s.cities_left, "isMe": s.index == me.index,
            })
        return {
            "board": self.board.public(),
            "buildings": {str(v): [o, t] for v, (o, t) in self.buildings.items()},
            "roads": {str(e): o for e, o in self.roads.items()},
            "robber": self.robber,
            "phase": self.phase,
            "turn": self.turn,
            "dice": self.dice,
            "players": players,
            "me": {
                "seat": me.index,
                "hand": dict(me.hand),
                "dev": dict(me.dev),
                "devNew": dict(me.dev_new),
                "rates": {r: self.trade_rate(me.index, r) for r in C.RESOURCES},
                "discard": self.discard_need.get(me.index),
                "devPlayable": self._playable_dev(me),
            },
            "setup": {"seat": self.setup_order[self.setup_step] if self.phase == "setup" else None,
                      "sub": self.setup_sub},
            "roadLeft": self.road_left,
            "bank": dict(self.bank),
            "devDeckLeft": len(self.dev_deck),
            "trade": self._trade_view(),
            "winner": self.winner,
            "legal": legal,
            "log": list(self.log_lines),
        }

    def _playable_dev(self, s: Seat) -> List[str]:
        if self.dev_played_turn == self.turn_count or s.index != self.turn:
            return []
        if self.phase not in ("roll", "play"):
            return []
        kinds = [k for k in ("knight", "road_building", "year_of_plenty", "monopoly") if s.dev.get(k)]
        if self.phase == "roll":
            kinds = [k for k in kinds if k == "knight"]   # 掷骰子前只能打骑士
        return kinds

    def _trade_view(self) -> Optional[dict]:
        if not self.trade:
            return None
        t = self.trade
        return {"from": t["from"], "give": t["give"], "want": t["want"], "accepted": list(t["accepted"])}

    def _legal_for(self, me: Seat) -> dict:
        """当前轮到我能点的地方。前端只按这些高亮，规则判断全在服务器。"""
        out = {"vertices": [], "cities": [], "edges": [], "hexes": {}}
        if self.phase == "setup" and self.setup_order[self.setup_step] == me.index:
            if self.setup_sub == "settlement":
                out["vertices"] = [v["id"] for v in self.board.vertices if self._spaced(v["id"])]
            else:
                ed = self.board.vertices[self.last_settlement]["edges"]
                out["edges"] = [e for e in ed if e not in self.roads]
            return out
        if me.index != self.turn:
            return out
        if self.phase == "play":
            if me.settlements_left > 0:
                out["vertices"] = self.legal_vertices_for_settlement(me.index)
            if me.roads_left > 0:
                out["edges"] = self.legal_edges_for_road(me.index)
            if me.cities_left > 0:
                out["cities"] = [v for v, (o, t) in self.buildings.items()
                                 if o == me.index and t == "settlement"]
        elif self.phase == "road_building":
            out["edges"] = self.legal_edges_for_road(me.index)
        elif self.phase == "robber":
            for hid in range(len(self.board.hexes)):
                if hid != self.robber:
                    out["hexes"][str(hid)] = self._victims(hid, me.index)
        return out
