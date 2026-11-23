"""突击行动的服务器部分：页面、大厅、房间、WebSocket、广播循环。

挂载在 /apps/strike/ 下（见 projects/strike/__init__.py）。需要登录（游客也可以），注册用户才能建房。

协议（JSON）：
  浏览器 → 服务器（大厅）
    {"t":"lobby"}                          刷新房间列表
    {"t":"create","name":"房间名"}         建房（只有注册用户；每人同时只能有一个）
    {"t":"join","room":"房间 id"}          加入房间（房主回来时也用这个）
    {"t":"leave"}                          离开房间；房主离开 = 解散房间
  浏览器 → 服务器（房间里）
    {"t":"in","seq":1,"fwd":1,"side":0,"yaw":0,"pitch":0,"dt":0.033}   移动输入
    {"t":"fire"} / {"t":"buy","weapon":"smg"} / {"t":"equip","slot":"primary"} / {"t":"scope","on":true}
    {"t":"kick","id":玩家编号}             房主：踢人
    {"t":"bots","delta":1}                 房主：加一台电脑（-1 为减一台）
    {"t":"disband"}                        房主：解散房间
  服务器 → 浏览器
    {"t":"lobby","me":{...},"rooms":[...],"notice":"可选的提示"}
    {"t":"welcome","id":...,"room":{...},"map":{...},"sim":{...}}
    {"t":"state","you":{...},"players":[...],"events":[...],"teams":[...],"room":{...}}   每 0.05 秒一次
    {"t":"error","text":"..."}
"""
from __future__ import annotations

import asyncio
import logging
import random
import math
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, user_from_token, ws_same_origin
from app.db import get_db
from app.pages import html_page

from . import config as C
from .room import Room, RoomError, new_room_id

log = logging.getLogger("strike")
STATIC = Path(__file__).resolve().parent / "static"

router = APIRouter()
rooms: Dict[str, Room] = {}
conns: Dict[WebSocket, "Conn"] = {}
_loop_task: Optional[asyncio.Task] = None

MAP = {"half": C.ARENA_HALF, "walls": C.WALLS, "spawns": C.SPAWNS}
SIM = {
    "radius": C.PLAYER_RADIUS, "height": C.PLAYER_HEIGHT, "eye": C.EYE_HEIGHT,
    "head": C.HEAD_HEIGHT, "speed": C.MOVE_SPEED, "maxDt": C.MAX_DT,
    "maxPitch": C.MAX_PITCH, "maxHp": C.MAX_HP,
    "respawn": C.RESPAWN_SECONDS, "tick": C.TICK_SECONDS,
    "weapons": C.WEAPONS, "interp": int(C.LAG_COMP * 1000),
}


class Conn:
    """一个浏览器连接：它是哪个账户、现在在哪个房间、在房间里的玩家编号。"""

    def __init__(self, ws: WebSocket, user_id: int, name: str, is_guest: bool):
        self.ws = ws
        self.user_id = user_id
        self.name = name
        self.is_guest = is_guest
        self.room_id: Optional[str] = None
        self.player_id: Optional[int] = None


@router.get("/")
def index():
    return html_page(STATIC / "index.html")


# ------------------------------------------------------------------ 账户

def _account(token: Optional[str]):
    """返回 (用户 id, 显示名, 是否游客)；没登录返回 None。"""
    with get_db() as db:
        u = user_from_token(db, token)
        return (u.id, u.display_name, u.is_guest) if u else None


def _num(msg: dict, key: str, lo: float, hi: float) -> float:
    """从消息里取一个有限的数字，并限制在 [lo, hi] 之间。不是数字就抛出 ValueError。"""
    v = msg.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"字段 {key} 不合法")
    return min(max(float(v), lo), hi)


def _clean_room_name(raw: Any, default: str) -> str:
    name = str(raw or "").strip()[:16]
    return name or default


# ------------------------------------------------------------------ 发给浏览器的数据

def _my_room(conn: Conn) -> Optional[Room]:
    return rooms.get(conn.room_id) if conn.room_id else None


def _lobby_msg(conn: Conn, notice: str = "") -> dict:
    owned = next((r.id for r in rooms.values() if r.host_id == conn.user_id), None)
    msg = {
        "t": "lobby",
        "me": {"id": conn.user_id, "name": conn.name, "isGuest": conn.is_guest,
               "canCreate": (not conn.is_guest) and owned is None and conn.room_id is None,
               "ownedRoom": owned, "room": conn.room_id},
        "rooms": [r.summary() for r in rooms.values()],
    }
    if notice:
        msg["notice"] = notice
    return msg


async def _send(ws: WebSocket, msg: dict) -> None:
    with suppress(Exception):
        await ws.send_json(msg)


async def _broadcast_lobby() -> None:
    """房间列表变了：告诉所有不在房间里的人。"""
    for ws, conn in list(conns.items()):
        if conn.room_id is None:
            await _send(ws, _lobby_msg(conn))


async def _dissolve(room: Room, notice: str) -> None:
    """解散房间：房间里的人都回到大厅，并收到提示。"""
    rooms.pop(room.id, None)
    for ws, conn in list(conns.items()):
        if conn.room_id == room.id:
            conn.room_id = None
            conn.player_id = None
            await _send(ws, _lobby_msg(conn, notice))
    await _broadcast_lobby()


# ------------------------------------------------------------------ WebSocket

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    acc = await run_in_threadpool(_account, ws.cookies.get(SESSION_COOKIE))
    if not acc:
        await _send(ws, {"t": "error", "text": "请先登录"})
        await ws.close(code=4401)
        return
    uid, uname, is_guest = acc
    conn = Conn(ws, uid, uname, is_guest)
    conns[ws] = conn
    await _send(ws, _lobby_msg(conn))
    try:
        while True:
            msg = await ws.receive_json()
            try:
                await _handle(conn, msg)
            except RoomError as e:
                await _send(ws, {"t": "error", "text": str(e)})
            except (KeyError, ValueError, TypeError, AttributeError):
                await _send(ws, {"t": "error", "text": "无效的操作"})
    except WebSocketDisconnect:
        pass
    finally:
        room = _my_room(conn)
        if room is not None:
            if conn.user_id == room.host_id:
                room.disconnect_host()           # 房主断线：房间保留，等他回来
            else:
                room.leave(conn.user_id)
        conn.room_id = None
        conn.player_id = None
        conns.pop(ws, None)
        await _broadcast_lobby()


async def _enter(conn: Conn, room: Room) -> None:
    pid = room.join(conn.user_id, conn.name)
    conn.room_id = room.id
    conn.player_id = pid
    await _send(conn.ws, {"t": "welcome", "id": pid, "room": room.state_for(conn.user_id),
                          "map": MAP, "sim": SIM})


async def _handle(conn: Conn, msg: dict) -> None:
    kind = msg.get("t")
    if kind == "lobby":
        await _send(conn.ws, _lobby_msg(conn))

    elif kind == "create":
        if conn.is_guest:
            raise RoomError("注册账号后才能建房")
        if conn.room_id is not None:
            raise RoomError("你已经在一个房间里了")
        if sum(1 for r in rooms.values() if r.host_id == conn.user_id) >= C.MAX_ROOMS_PER_HOST:
            raise RoomError("你已经有一个房间了，先进去或者解散它")
        room = Room(id=new_room_id(), name=_clean_room_name(msg.get("name"), f"{conn.name}的房间"),
                    host_id=conn.user_id, host_name=conn.name, clock=time.monotonic,
                    rng=random.Random())
        rooms[room.id] = room
        await _enter(conn, room)
        await _broadcast_lobby()

    elif kind == "join":
        if conn.room_id is not None:
            raise RoomError("你已经在一个房间里了")
        room = rooms.get(str(msg.get("room", "")))
        if room is None:
            raise RoomError("这个房间已经不存在了")
        await _enter(conn, room)
        await _broadcast_lobby()

    elif kind == "leave":
        room = _my_room(conn)
        if room is None:
            return
        if conn.user_id == room.host_id:
            await _dissolve(room, f"房主 {conn.name} 解散了房间")
            return
        room.leave(conn.user_id)
        conn.room_id = None
        conn.player_id = None
        await _send(conn.ws, _lobby_msg(conn))
        await _broadcast_lobby()

    elif kind == "disband":
        room = _my_room(conn)
        if room is None or conn.user_id != room.host_id:
            raise RoomError("只有房主可以解散房间")
        await _dissolve(room, f"房主 {conn.name} 解散了房间")

    elif kind == "kick":
        room = _my_room(conn)
        if room is None or conn.user_id != room.host_id:
            raise RoomError("只有房主可以踢人")
        uid = room.kick(int(msg.get("id")))
        if uid is None:
            raise RoomError("找不到这个玩家")
        for ws, other in list(conns.items()):
            if other.user_id == uid and other.room_id == room.id:
                other.room_id = None
                other.player_id = None
                await _send(ws, _lobby_msg(other, "你被房主请出了房间"))
        await _broadcast_lobby()

    elif kind == "bots":
        room = _my_room(conn)
        if room is None or conn.user_id != room.host_id:
            raise RoomError("只有房主可以加减电脑")
        delta = int(_num(msg, "delta", -1, 1))
        if delta:
            room.adjust_bots(delta)
        await _broadcast_lobby()

    elif kind in ("in", "fire", "buy", "equip", "scope"):
        room = _my_room(conn)
        if room is None or conn.player_id is None:
            return
        arena = room.arena
        pid = conn.player_id
        if kind == "in":
            arena.input(pid,
                        seq=int(_num(msg, "seq", 0, 1e12)),
                        fwd=_num(msg, "fwd", -1, 1),
                        side=_num(msg, "side", -1, 1),
                        yaw=_num(msg, "yaw", -1e6, 1e6),
                        pitch=_num(msg, "pitch", -C.MAX_PITCH, C.MAX_PITCH),
                        dt=_num(msg, "dt", 0, C.MAX_DT))
        elif kind == "fire":
            arena.fire(pid)
        elif kind == "buy":
            wid = msg.get("weapon")
            if isinstance(wid, str):
                arena.buy(pid, wid)
        elif kind == "equip":
            slot = msg.get("slot")
            if isinstance(slot, str):
                arena.equip(pid, slot)
        elif kind == "scope":
            arena.set_scope(pid, msg.get("on") is True)
    # 其他类型的消息直接忽略，保持向前兼容


# ------------------------------------------------------------------ 广播循环

async def game_loop():
    """每 TICK_SECONDS 秒：每个房间各自前进一步，然后把状态发给房间里的每个人。一个房间出错不影响其他房间。"""
    while True:
        await asyncio.sleep(C.TICK_SECONDS)
        for room in list(rooms.values()):
            try:
                room.arena.tick()
                events = room.arena.take_events()
                members = [(ws, c) for ws, c in list(conns.items()) if c.room_id == room.id and c.player_id]
                if not members:
                    continue
                roster = room.arena.roster()
                for ws, conn in members:
                    msg = {"t": "state", "you": room.arena.you(conn.player_id), "players": roster,
                           "events": events, "teams": room.arena.team_kills,
                           "room": room.state_for(conn.user_id)}
                    await _send(ws, msg)
            except Exception:
                log.exception("房间 %s 的广播出错", room.id)
        now = time.monotonic()
        for room in list(rooms.values()):
            if room.idle_expired(now):
                await _dissolve(room, "房间太久没有人，已经关闭")


async def startup():
    global _loop_task
    _loop_task = asyncio.create_task(game_loop())


async def shutdown():
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await _loop_task
        _loop_task = None
    for ws in list(conns):
        with suppress(Exception):
            await ws.close(code=1001)
    conns.clear()
    rooms.clear()


def health() -> dict:
    humans = sum(r.human_count() for r in rooms.values())
    players = sum(len(r.arena.players) for r in rooms.values())
    return {"rooms": len(rooms), "humans": humans, "players": players, "max": C.MAX_PLAYERS}
