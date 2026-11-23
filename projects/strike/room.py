"""突击行动的房间：一个房间就是一个竞技场（Arena），加上房主、人类玩家的座位和电脑的数量设置。

规则（和网球的房间相似，但有一点不同）：
- 只有注册用户能建房；所有登录用户（含游客）都能加入。
- 房主关闭网页（断线）不会解散房间：房主离开座位，房间保留；房主再次进入时，还是他的房间。
- 只有房主主动「解散」房间，或者房间没人、房主也不在超过 ROOM_IDLE_SECONDS，房间才会关闭。
- 电脑：默认让「人类玩家 + 电脑」保持 MIN_ONLINE 人；房主可以用 bot_extra 手动多加或少加。
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from . import config as C
from .game import Arena


class RoomError(Exception):
    """给玩家看的错误提示（中文）。"""


def new_room_id() -> str:
    return secrets.token_urlsafe(6)


@dataclass
class Room:
    id: str
    name: str
    host_id: int                 # 房主的账户 id
    host_name: str
    clock: Callable[[], float]
    rng: object
    arena: Arena = field(init=False)
    seats: Dict[int, int] = field(default_factory=dict)   # 账户 id → 玩家 id（只有人类玩家）
    host_online: bool = True
    bot_extra: int = 0           # 房主手动调整的电脑数量（正数加、负数减）
    last_active: float = 0.0

    def __post_init__(self):
        self.arena = Arena(clock=self.clock, rng=self.rng)
        self.last_active = self.clock()
        self.arena.balance_bots(extra=self.bot_extra)

    # ---- 座位

    def human_count(self) -> int:
        return len(self.seats)

    def bot_count(self) -> int:
        return sum(1 for p in self.arena.players.values() if p.is_bot)

    def join(self, user_id: int, name: str) -> int:
        """进入房间，返回玩家 id。已经在房间里就直接返回原来的座位。"""
        if user_id in self.seats:
            return self.seats[user_id]
        if self.human_count() >= C.MAX_PLAYERS:
            raise RoomError("房间已满")
        # 房间里有电脑占着位置：先踢掉电脑，给人腾出位置
        while len(self.arena.players) >= C.MAX_PLAYERS:
            if not self.arena.remove_one_bot():
                raise RoomError("房间已满")
        p = self.arena.add_player(name)
        self.seats[user_id] = p.id
        if user_id == self.host_id:
            self.host_online = True
        self._rebalance()
        self.touch()
        return p.id

    def leave(self, user_id: int) -> None:
        pid = self.seats.pop(user_id, None)
        if pid is not None:
            self.arena.remove_player(pid)
        self._rebalance()
        self.touch()

    def disconnect_host(self) -> None:
        """房主关闭网页或断线：离开座位，但房间保留。"""
        self.leave(self.host_id)
        self.host_online = False

    def kick(self, player_id: int) -> Optional[int]:
        """房主踢掉一个人类玩家（不能踢房主自己）。返回被踢的账户 id；没找到返回 None。"""
        for uid, pid in list(self.seats.items()):
            if pid == player_id and uid != self.host_id:
                self.leave(uid)
                return uid
        return None

    def adjust_bots(self, delta: int) -> None:
        """房主加一台电脑（delta=1）或减一台（delta=-1）。"""
        limit = C.MAX_PLAYERS
        self.bot_extra = max(-limit, min(limit, self.bot_extra + delta))
        self._rebalance()
        self.touch()

    def _rebalance(self) -> None:
        self.arena.balance_bots(extra=self.bot_extra)

    def touch(self) -> None:
        self.last_active = self.clock()

    def idle_expired(self, now: float) -> bool:
        """没有人类玩家、房主也不在，并且超过了空闲时间。"""
        return self.human_count() == 0 and not self.host_online and now - self.last_active > C.ROOM_IDLE_SECONDS

    # ---- 给前端的数据

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "host": self.host_name, "hostId": self.host_id,
                "hostOnline": self.host_online, "humans": self.human_count(), "bots": self.bot_count(),
                "capacity": C.MAX_PLAYERS}

    def state_for(self, user_id: int) -> dict:
        return {"id": self.id, "name": self.name, "isHost": user_id == self.host_id,
                "hostOnline": self.host_online, "humans": self.human_count(), "bots": self.bot_count(),
                "botExtra": self.bot_extra, "hostName": self.host_name}
