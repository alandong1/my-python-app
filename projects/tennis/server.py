"""网球的服务器部分：大厅、房间、WebSocket、比赛主循环。

挂载在 /apps/tennis/ 下（见 projects/tennis/__init__.py）。
房间和比赛只存在内存里，服务器重启会清空（见 REQUIREMENTS.md）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, ws_same_origin, user_from_token
from app.db import get_db
from app.pages import html_page

from .game import Room, RoomError, new_room_id

log = logging.getLogger("tennis")
STATIC = Path(__file__).resolve().parent / "static"
TICK = 1 / 30                      # 比赛每秒模拟 30 次
MAX_ROOMS_PER_HOST = 1             # 每个注册用户同时只能开一个房间

router = APIRouter()
rooms: Dict[str, Room] = {}
room_members: Dict[str, Dict[WebSocket, int]] = {}   # 房间 -> {连接: 用户 id}
conns: Dict[WebSocket, dict] = {}                    # 连接 -> {"id","name","room"}
lobby_conns: Set[WebSocket] = set()                  # 在大厅里的连接（会收到房间列表更新）
_loop_task: Optional[asyncio.Task] = None


# ------------------------------------------------------------------ 账户

def _account(token: Optional[str]):
    """返回 (用户 id, 显示名, 是否游客)；没登录返回 None。"""
    with get_db() as db:
        u = user_from_token(db, token)
        return (u.id, u.display_name, u.is_guest) if u else None


# ------------------------------------------------------------------ 发给前端的数据

def _room_meta(room: Room) -> dict:
    return {"id": room.id, "name": room.name, "mode": room.mode, "ai": room.ai,
            "modeName": "单打" if room.mode == "single" else "双打",
            "host": room.host_name, "hostId": room.host_id, "capacity": room.capacity}


def _room_msg(room: Room) -> dict:
    msg = room.snapshot()          # 注意：snapshot 会清空这一帧的事件
    msg["room"] = _room_meta(room)
    return msg


def _lobby_msg() -> dict:
    # 人机房间只有房主自己能进，不出现在大厅
    return {"type": "lobby", "rooms": [r.summary() for r in rooms.values() if not r.ai]}


async def _send(ws: WebSocket, msg: dict):
    try:
        await ws.send_json(msg)
    except Exception:              # 对方已经断开，忽略
        pass


async def _broadcast_lobby():
    msg = _lobby_msg()
    for ws in list(lobby_conns):
        await _send(ws, msg)


async def _send_room(room: Room):
    msg = _room_msg(room)
    for ws in list(room_members.get(room.id, {})):
        await _send(ws, msg)


# ------------------------------------------------------------------ 房间的加入、离开、解散

async def _close_room(room: Room, text: str):
    """解散房间：通知所有人，把人送回大厅。"""
    members = room_members.pop(room.id, {})
    rooms.pop(room.id, None)
    for ws in list(members):
        info = conns.get(ws)
        if info:
            info["room"] = None
        lobby_conns.add(ws)
        await _send(ws, {"type": "closed", "text": text})
        await _send(ws, _lobby_msg())
    await _broadcast_lobby()


async def _leave(ws: WebSocket, me: dict):
    """离开当前房间。房主离开、或比赛中途有人离开，都会解散房间。"""
    room_id = me.get("room")
    if not room_id or room_id not in rooms:
        me["room"] = None
        return
    room = rooms[room_id]
    if room.host_id == me["id"]:
        await _close_room(room, f"房主 {me['name']} 已离开，房间已解散")
        return
    if room.status != "waiting":
        await _close_room(room, f"{me['name']} 离开了，房间已解散")
        return
    room.leave(me["id"])
    room_members.get(room_id, {}).pop(ws, None)
    me["room"] = None
    lobby_conns.add(ws)
    await _send(ws, _lobby_msg())
    await _send_room(room)
    await _broadcast_lobby()


# ------------------------------------------------------------------ 页面与接口

@router.get("/")
async def page():
    return html_page(STATIC / "index.html")


class RoomIn(BaseModel):
    name: str
    mode: str                 # "single" 单打 / "double" 双打
    opponent: str = "player"  # "player" 开放给玩家 / "ai" 电脑（人机，只能单打）


@router.get("/api/rooms")
async def list_rooms(request: Request):
    if not await run_in_threadpool(_account, request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(401, "请先登录")
    return _lobby_msg()


@router.post("/api/rooms")
async def create_room(body: RoomIn, request: Request):
    acc = await run_in_threadpool(_account, request.cookies.get(SESSION_COOKIE))
    if not acc:
        raise HTTPException(401, "请先登录")
    uid, uname, is_guest = acc
    if is_guest:
        raise HTTPException(403, "游客不能建房，请先注册账号")
    if body.mode not in ("single", "double"):
        raise HTTPException(400, "请选择单打或双打")
    if body.opponent not in ("player", "ai"):
        raise HTTPException(400, "请选择对手")
    if body.opponent == "ai" and body.mode != "single":
        raise HTTPException(400, "人机对战只能单打")
    name = body.name.strip()
    if not 1 <= len(name) <= 20:
        raise HTTPException(400, "房间名要 1 到 20 个字")
    if sum(1 for r in rooms.values() if r.host_id == uid) >= MAX_ROOMS_PER_HOST:
        raise HTTPException(409, "你已经有一个房间了，先解散它再建新的")
    room = Room(id=new_room_id(), name=name, mode=body.mode, host_id=uid, host_name=uname,
                ai=body.opponent == "ai")
    rooms[room.id] = room
    room_members[room.id] = {}
    await _broadcast_lobby()
    return room.summary()


# ------------------------------------------------------------------ WebSocket

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    acc = await run_in_threadpool(_account, ws.cookies.get(SESSION_COOKIE))
    if not acc:
        await ws.send_json({"type": "auth", "text": "请先登录"})
        await ws.close(code=4401)
        return
    uid, uname, _ = acc
    me = {"id": uid, "name": uname, "room": None}
    conns[ws] = me
    lobby_conns.add(ws)
    await ws.send_json({"type": "hello", "me": {"id": uid, "name": uname}})
    await ws.send_json(_lobby_msg())
    try:
        while True:
            msg = await ws.receive_json()
            try:
                await _handle(ws, me, msg)
            except RoomError as e:
                await _send(ws, {"type": "error", "text": str(e)})
            except (KeyError, ValueError, TypeError, AttributeError):
                await _send(ws, {"type": "error", "text": "无效的操作"})
    except WebSocketDisconnect:
        pass
    finally:
        await _leave(ws, me)
        lobby_conns.discard(ws)
        conns.pop(ws, None)


async def _handle(ws: WebSocket, me: dict, msg: dict):
    kind = msg.get("type")
    if kind == "lobby":
        await _send(ws, _lobby_msg())
        return
    if kind == "join":
        if me["room"]:
            raise RoomError("你已经在一个房间里了")
        room = rooms.get(str(msg.get("roomId", "")))
        if not room:
            raise RoomError("这个房间已经不存在了")
        room.join(me["id"], me["name"])     # 房主的座位建房时就留好了，join 会直接返回它
        me["room"] = room.id
        room_members[room.id][ws] = me["id"]
        lobby_conns.discard(ws)
        await _send(ws, _room_msg(room))
        await _send_room(room)
        await _broadcast_lobby()
        return
    if kind == "leave":
        await _leave(ws, me)
        return

    room = rooms.get(me["room"]) if me["room"] else None
    if not room:
        raise RoomError("你还没有进入房间")
    if kind == "start":
        room.start(me["id"])
        await _send_room(room)
        await _broadcast_lobby()
    elif kind == "restart":
        room.restart(me["id"])
        await _send_room(room)
        await _broadcast_lobby()
    elif kind == "choose":
        room.choose(me["id"], str(msg.get("option", "")))


# ------------------------------------------------------------------ 比赛主循环

async def _game_loop():
    """每 1/30 秒推进一次所有进行中的比赛，并把状态发给房间里的人。"""
    last = time.monotonic()
    while True:
        await asyncio.sleep(TICK)
        now = time.monotonic()
        dt = min(0.1, now - last)
        last = now
        for room in list(rooms.values()):
            if room.status != "playing" or not room_members.get(room.id):
                continue
            try:
                room.tick(dt)
            except Exception:
                log.exception("比赛计算出错，房间 %s 已解散", room.id)
                await _close_room(room, "比赛出现了意外错误，房间已解散")
                continue
            await _send_room(room)
            if room.status == "finished":      # 刚刚打完：大厅里的状态要更新
                await _broadcast_lobby()


async def startup():
    global _loop_task
    _loop_task = asyncio.create_task(_game_loop())


async def shutdown():
    if _loop_task:
        _loop_task.cancel()
        try:
            await _loop_task
        except (asyncio.CancelledError, Exception):
            pass


def health() -> dict:
    return {"rooms": len(rooms), "players": sum(len(m) for m in room_members.values())}
