"""卡坦岛的服务器部分：房间、WebSocket、把对局状态发给每位玩家。

挂载在 /apps/catan/ 下（见 __init__.py）。
- 房间和对局都在内存里。服务器重新部署后房间会清空（这是已知限制，见 REQUIREMENTS.md）。
- 账号用平台的登录 cookie 识别（和领主战争一样），不需要另外登录。
- 每位玩家只收到自己该看到的信息（见 Game.view）。
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, lookup_session_user, ws_same_origin
from app.pages import html_page

from . import config as C
from .game import Game, GameError

log = logging.getLogger("catan")
STATIC = Path(__file__).resolve().parent / "static"
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 去掉了容易混淆的 0/O、1/I

router = APIRouter()


@dataclass
class Room:
    code: str
    host: int                                        # 房主的账号 ID
    members: List[Tuple[int, str]] = field(default_factory=list)   # (账号 ID, 显示名)，按加入顺序
    game: Optional[Game] = None
    conns: Dict[int, WebSocket] = field(default_factory=dict)      # 在线的连接：账号 ID → WebSocket

    def online(self) -> set:
        return set(self.conns)


rooms: Dict[str, Room] = {}
user_room: Dict[int, str] = {}                       # 账号 ID → 所在房间的代码


def _new_code() -> str:
    while True:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
        if code not in rooms:
            return code


def _room_of(uid: int) -> Optional[Room]:
    code = user_room.get(uid)
    return rooms.get(code) if code else None


def _leave(uid: int):
    """离开当前房间。游戏已经开始时不能离开（否则局面会卡住）。"""
    room = _room_of(uid)
    if not room:
        return
    if room.game is not None and room.game.winner is None:
        raise GameError("游戏进行中，不能离开房间")
    room.members = [m for m in room.members if m[0] != uid]
    user_room.pop(uid, None)
    room.conns.pop(uid, None)
    if not room.members:
        rooms.pop(room.code, None)
    elif room.host == uid:
        room.host = room.members[0][0]


def _state_for(uid: int, room: Optional[Room]) -> dict:
    if room is None:
        return {"type": "state", "room": None}
    info = {"code": room.code, "isHost": room.host == uid, "min": C.MIN_PLAYERS, "max": C.MAX_PLAYERS}
    if room.game is None:
        info["players"] = [{"name": name, "online": uid_ in room.conns, "host": uid_ == room.host,
                            "isMe": uid_ == uid}
                           for uid_, name in room.members]
        return {"type": "state", "room": info, "game": None}
    return {"type": "state", "room": info, "game": room.game.view(uid, room.online()),
            "config": _client_config()}


def _client_config() -> dict:
    """前端需要的规则数值（费用、名字等），只读，不含内部信息。"""
    return {"cost": C.COST, "resourceNames": C.RESOURCE_NAMES, "terrainNames": C.TERRAIN_NAMES,
            "devNames": C.DEV_NAMES, "vpToWin": C.VP_TO_WIN, "resources": list(C.RESOURCES),
            "pieceLimit": C.PIECE_LIMIT}


async def _broadcast(room: Room):
    for uid, ws in list(room.conns.items()):
        try:
            await ws.send_json(_state_for(uid, room))
        except Exception:
            room.conns.pop(uid, None)


async def _send_error(ws: WebSocket, text: str):
    await ws.send_json({"type": "error", "text": text})


# ------------------------------------------------------------------ 房间操作

def _create(uid: int, name: str) -> Room:
    if _room_of(uid) and _room_of(uid).game is not None and _room_of(uid).game.winner is None:
        raise GameError("你正在一局游戏中，请先结束它")
    _leave(uid)
    room = Room(code=_new_code(), host=uid, members=[(uid, name)])
    rooms[room.code] = room
    user_room[uid] = room.code
    return room


def _join(uid: int, name: str, code: str) -> Room:
    room = rooms.get((code or "").strip().upper())
    if not room:
        raise GameError("没有这个房间（代码不对，或者服务器已经重启）")
    if any(m[0] == uid for m in room.members):
        user_room[uid] = room.code
        return room                      # 已经是房间成员（比如刷新页面），直接回到房间
    if room.game is not None:
        raise GameError("这个房间的游戏已经开始了")
    if len(room.members) >= C.MAX_PLAYERS:
        raise GameError("房间满了")
    _leave(uid)
    room.members.append((uid, name))
    user_room[uid] = room.code
    return room


def _start(uid: int, room: Room):
    if room.host != uid:
        raise GameError("只有房主可以开始游戏")
    if room.game is not None:
        raise GameError("游戏已经开始了")
    if len(room.members) < C.MIN_PLAYERS:
        raise GameError(f"至少需要 {C.MIN_PLAYERS} 人才能开始")
    room.game = Game(room.members)
    log.info("房间 %s 开始游戏，%d 人", room.code, len(room.members))


# 游戏操作：客户端发 {"type": "action", "action": 名字, ...参数}
ACTIONS: Dict[str, Callable[[Game, int, dict], None]] = {
    "setup_settlement": lambda g, u, m: g.setup_settlement(u, int(m["vertex"])),
    "setup_road": lambda g, u, m: g.setup_road(u, int(m["edge"])),
    "roll": lambda g, u, m: g.roll(u),
    "discard": lambda g, u, m: g.discard(u, m.get("cards")),
    "move_robber": lambda g, u, m: g.move_robber(
        u, int(m["hex"]), None if m.get("victim") is None else int(m["victim"])),
    "knight": lambda g, u, m: g.play_knight(u),
    "road_building": lambda g, u, m: g.play_road_building(u),
    "free_road": lambda g, u, m: g.place_free_road(u, int(m["edge"])),
    "year_of_plenty": lambda g, u, m: g.year_of_plenty(u, str(m["first"]), str(m["second"])),
    "monopoly": lambda g, u, m: g.monopoly(u, str(m["resource"])),
    "build_road": lambda g, u, m: g.build_road(u, int(m["edge"])),
    "build_settlement": lambda g, u, m: g.build_settlement(u, int(m["vertex"])),
    "build_city": lambda g, u, m: g.build_city(u, int(m["vertex"])),
    "buy_dev": lambda g, u, m: g.buy_dev(u),
    "bank_trade": lambda g, u, m: g.bank_trade(u, str(m["give"]), str(m["get"])),
    "offer_trade": lambda g, u, m: g.offer_trade(u, m.get("give"), m.get("want")),
    "accept_trade": lambda g, u, m: g.accept_trade(u),
    "confirm_trade": lambda g, u, m: g.confirm_trade(u, int(m["partner"])),
    "cancel_trade": lambda g, u, m: g.cancel_trade(u),
    "end_turn": lambda g, u, m: g.end_turn(u),
}


# ------------------------------------------------------------------ WebSocket

@router.get("/")
async def index():
    return html_page(STATIC / "index.html")


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    account = await run_in_threadpool(lookup_session_user, ws.cookies.get(SESSION_COOKIE))
    if not account:
        await ws.send_json({"type": "auth", "text": "请先登录"})
        await ws.close(code=4401)
        return
    uid, name = account
    try:
        room = _room_of(uid)
        if room:
            room.conns[uid] = ws                 # 刷新页面或断线重连：直接回到原来的房间
            await room_changed(room)
        else:
            await ws.send_json(_state_for(uid, None))
        while True:
            msg = await ws.receive_json()
            await _handle(uid, name, ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        room = _room_of(uid)
        if room and room.conns.get(uid) is ws:
            del room.conns[uid]
            await _broadcast(room)               # 让别人看到「离线」状态


async def room_changed(room: Room):
    await _broadcast(room)


async def _broadcast_old(old: Optional[Room], new: Room):
    """玩家换了房间：通知原来的房间，让里面的人看到他已经离开。"""
    if old and old.code != new.code and old.code in rooms:
        await _broadcast(old)


async def _handle(uid: int, name: str, ws: WebSocket, msg: dict):
    kind = msg.get("type")
    try:
        if kind == "create":
            old = _room_of(uid)
            room = _create(uid, name)
            room.conns[uid] = ws
            await _broadcast(room)
            await _broadcast_old(old, room)
        elif kind == "join":
            old = _room_of(uid)
            room = _join(uid, name, str(msg.get("code", "")))
            room.conns[uid] = ws
            await _broadcast(room)
            await _broadcast_old(old, room)
        elif kind == "leave":
            room = _room_of(uid)
            _leave(uid)
            if room and room.code in rooms:
                await _broadcast(room)
            await ws.send_json({"type": "state", "room": None})
        elif kind == "start":
            room = _room_of(uid)
            if not room:
                raise GameError("你还没有加入房间")
            _start(uid, room)
            await _broadcast(room)
        elif kind == "action":
            room = _room_of(uid)
            if not room:
                raise GameError("你还没有加入房间")
            if room.game is None:
                raise GameError("游戏还没有开始")
            fn = ACTIONS.get(msg.get("action"))
            if not fn:
                raise GameError("无效的指令")
            fn(room.game, uid, msg)
            await _broadcast(room)
        else:
            return
    except GameError as e:
        await _send_error(ws, str(e))
    except (KeyError, ValueError, TypeError):
        await _send_error(ws, "无效的指令")


def health() -> dict:
    return {"rooms": len(rooms), "games": sum(1 for r in rooms.values() if r.game is not None),
            "online": sum(len(r.conns) for r in rooms.values())}
