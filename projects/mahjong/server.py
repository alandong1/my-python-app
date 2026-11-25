"""麻将的服务器部分：页面、大厅接口、商城、WebSocket 和房间表。

挂载在 /apps/mahjong/ 下（见 projects/mahjong/__init__.py）。
身份用平台账号：游客也有账号（浏览器里的游客凭证），所以同一个浏览器重新打开还是同一个人。

WebSocket 的第一条消息决定做什么：
  create   建房（公开或私密）
  solo     和电脑玩
  join     按房间号加入
  resume   断线后重新连回正在进行的房间
之后的消息都交给所在的房间处理。
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, lookup_session_user, require_user, ws_same_origin
from app.db import get_db
from app.pages import html_page

from . import rules_catalog, store
from .engine import GameError
from .room import ROUND_CHOICES, Room

log = logging.getLogger("mahjong")
STATIC = Path(__file__).resolve().parent / "static"

rooms: Dict[str, Room] = {}   # 房间号 -> 房间（只在内存里，服务器重启后清空）

router = APIRouter()


async def startup() -> None:
    """服务器启动时：给所有已有账号发一次起始积分（只发一次）。"""
    await run_in_threadpool(store.grant_once)


@router.get("/")
async def index():
    return html_page(STATIC / "index.html")


def _new_code() -> str:
    """四位房间号（1000~9999），不和正在用的房间重复。"""
    while True:
        code = str(secrets.randbelow(9000) + 1000)
        if code not in rooms:
            return code


def _clean_rounds(raw) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4
    return n if n in ROUND_CHOICES else 4


def _account_from_request(request: Request) -> Tuple[int, str]:
    with get_db() as db:
        u = require_user(db, request)
        return u.id, u.display_name


@router.get("/api/lobby")
async def lobby(request: Request):
    """大厅需要的数据：我的积分和道具、排行榜、公开的房间、我正在进行的房间。"""
    uid, name = await run_in_threadpool(_account_from_request, request)
    wallet = await run_in_threadpool(store.wallet, uid)
    board = await run_in_threadpool(store.leaderboard)
    public = [r.summary() for r in rooms.values() if r.visibility == "public" and r.state() == "waiting"]
    mine = next((r.code for r in rooms.values() if r.seat_of(str(uid)) is not None and r.in_game()), None)
    return {
        "rules": rules_catalog.RULES,
        "me": {"name": name, "points": wallet["points"], "items": wallet["items"]},
        "shop": {k: {"name": v["name"], "price": v["price"]} for k, v in store.ITEMS.items()},
        "leaderboard": board,
        "rooms": public,
        "myRoom": mine,
    }


class BuyIn(BaseModel):
    item: str


def _buy(uid: int, item: str) -> dict:
    if item not in store.ITEMS:
        raise GameError("没有这个道具")
    if not store.buy(uid, item):
        raise GameError("积分不够")
    return store.wallet(uid)


@router.post("/api/shop/buy")
async def shop_buy(body: BuyIn, request: Request):
    uid, _ = await run_in_threadpool(_account_from_request, request)
    try:
        wallet = await run_in_threadpool(_buy, uid, body.item)
    except GameError as e:
        return {"ok": False, "text": str(e)}
    return {"ok": True, "points": wallet["points"], "items": wallet["items"]}


async def _enter(ws: WebSocket, pid: str, name: str, msg: dict) -> Room:
    kind = msg["type"]
    if kind in ("create", "solo"):
        rule = str(msg.get("rule") or "hubei")
        if not rules_catalog.is_available(rule):
            raise GameError("这个玩法还没有开放，规则确认后再上线")
        room = Room(_new_code(), "public" if msg.get("visibility") == "public" else "private")
        room.rule = rule
        room.rounds = _clean_rounds(msg.get("rounds"))
        rooms[room.code] = room
        await ws.send_json({"type": "joined", "code": room.code})
        if kind == "solo":
            await room.attach(pid, name, ws, items=bool(msg.get("items")))
        else:
            await room.attach(pid, name, ws)
        return room
    if kind == "join":
        code = str(msg.get("code", "")).strip()
        room = rooms.get(code)
        if room is None:
            raise GameError("没有这个房间，请检查房间号")
        room.check_joinable(pid)
        await ws.send_json({"type": "joined", "code": room.code})
        await room.attach(pid, name, ws)
        return room
    # resume
    code = str(msg.get("code", "")).strip()
    room = rooms.get(code)
    if room is None or room.seat_of(pid) is None:
        raise GameError("这个房间已经没有你的座位了")
    await ws.send_json({"type": "joined", "code": room.code})
    await room.reconnect(pid, ws)
    return room


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    account = await run_in_threadpool(lookup_session_user, ws.cookies.get(SESSION_COOKIE))
    if not account:
        await ws.send_json({"type": "error", "text": "请先登录"})
        await ws.close(code=4401)
        return
    uid, name = account
    pid = str(uid)
    room: Optional[Room] = None
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
                    if msg.get("type") not in ("create", "solo", "join", "resume"):
                        continue
                    room = await _enter(ws, pid, name, msg)
                else:
                    await room.handle(pid, msg)
            except GameError as e:
                await ws.send_json({"type": "error", "text": str(e)})
            except (KeyError, TypeError, ValueError):
                await ws.send_json({"type": "error", "text": "无效的指令"})
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None:
            await room.drop(pid)
            # 没有真人了：等待中的房间直接关闭；正在进行的牌局保留（暂停），等玩家回来继续
            if not room.humans() and not room.in_game():
                rooms.pop(room.code, None)
                log.info("房间 %s 已空，关闭", room.code)
