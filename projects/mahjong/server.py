"""麻将的服务器部分：页面、WebSocket、房间表。

挂载在 /apps/mahjong/ 下（见 projects/mahjong/__init__.py）。
一个 WebSocket 连接对应一名玩家。第一条消息决定是建房（create）、
和电脑玩（solo）还是按房间号加入（join）；之后的消息都交给所在的房间处理。
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import ws_same_origin
from app.pages import html_page

from .engine import GameError
from .room import ROUND_CHOICES, Room

log = logging.getLogger("mahjong")
STATIC = Path(__file__).resolve().parent / "static"

CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 去掉了容易混淆的 I、O、0、1
rooms: Dict[str, Room] = {}

router = APIRouter()


@router.get("/")
async def index():
    return html_page(STATIC / "index.html")


def _new_code() -> str:
    while True:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(4))
        if code not in rooms:
            return code


def _clean_name(raw) -> str:
    name = str(raw or "").strip()[:12]
    return name or "玩家"


def _clean_rounds(raw) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4
    return n if n in ROUND_CHOICES else 4


async def _enter(ws: WebSocket, msg: dict) -> Tuple[Room, str]:
    kind = msg["type"]
    name = _clean_name(msg.get("name"))
    pid = secrets.token_urlsafe(9)
    if kind in ("create", "solo"):
        room = Room(_new_code())
        room.rounds = _clean_rounds(msg.get("rounds"))
        rooms[room.code] = room
    else:
        code = str(msg.get("code", "")).strip().upper()
        room = rooms.get(code)
        if room is None:
            raise GameError("没有这个房间，请检查房间号")
    async with room.lock:
        room.join(pid, name, ws)
        await ws.send_json({"type": "joined", "pid": pid, "code": room.code})
        if kind == "solo":
            room.start(pid)
        await room._changed()
    return room, pid


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    room: Optional[Room] = None
    pid: Optional[str] = None
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                await ws.send_json({"type": "error", "text": "无效的消息"})
                continue
            if not isinstance(msg, dict):
                continue
            try:
                if room is None:
                    if msg.get("type") not in ("create", "solo", "join"):
                        continue
                    room, pid = await _enter(ws, msg)
                else:
                    await room.handle(pid, msg)
            except GameError as e:
                await ws.send_json({"type": "error", "text": str(e)})
            except (KeyError, TypeError, ValueError):
                await ws.send_json({"type": "error", "text": "无效的指令"})
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None and pid is not None:
            await room.drop(pid)
            if not room.humans():
                rooms.pop(room.code, None)
                log.info("房间 %s 已空，关闭", room.code)
