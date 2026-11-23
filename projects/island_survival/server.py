"""荒岛求生的服务器部分：页面、WebSocket、游戏主循环。

挂载在 /apps/island-survival/ 下（见 projects/island-survival/__init__.py）。
游戏状态只在内存里，服务器重启后玩家要重新开始；地图由种子固定，重启后不变。
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, lookup_session_user, ws_same_origin
from app.pages import html_page

from .game import DT, Game, GameError

log = logging.getLogger("island-survival")
STATIC = Path(__file__).resolve().parent / "static"

SEED = int(os.environ.get("ISLAND_SEED", "2026"))
game = Game(SEED)
clients: Dict[WebSocket, int] = {}          # 连接 → 玩家编号
RESOURCE_EVERY = 10                         # 资源列表每 10 个 tick（1 秒）发一次，省流量
_loop_task: Optional[asyncio.Task] = None


async def game_loop() -> None:
    """每 0.1 秒推进一次世界，然后把状态发给每个在线玩家。"""
    while True:
        try:
            game.tick()
            await broadcast()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tick 出错")
        await asyncio.sleep(DT)


async def broadcast() -> None:
    with_res = game.tick_no % RESOURCE_EVERY == 0
    for ws, pid in list(clients.items()):
        p = game.players.get(pid)
        if p is None:
            continue
        try:
            await ws.send_json({"type": "state", **game.view(p, with_res)})
        except Exception:
            clients.pop(ws, None)


async def startup() -> None:
    global _loop_task
    _loop_task = asyncio.create_task(game_loop())


async def shutdown() -> None:
    if _loop_task:
        _loop_task.cancel()
        try:
            await _loop_task
        except asyncio.CancelledError:
            pass
    clients.clear()


def health() -> dict:
    return {"online": len(clients), "survivors": len(game.players), "tick": game.tick_no,
            "seed": SEED}


def _num(msg: dict, key: str) -> float:
    value = float(msg.get(key, 0))
    if value != value or abs(value) > 10:       # 排除 NaN 和离谱的数字
        raise ValueError(key)
    return value


# ------------------------------------------------------------------ 路由

router = APIRouter()


@router.get("/")
async def index():
    return html_page(STATIC / "index.html")


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    player = None
    try:
        account = await run_in_threadpool(lookup_session_user, ws.cookies.get(SESSION_COOKIE))
        if not account:
            await ws.send_json({"type": "auth", "text": "请先登录"})
            await ws.close(code=4401)
            return
        hello = await ws.receive_json()
        if hello.get("type") != "join":
            await ws.close()
            return
        try:
            player = game.join(account[0], account[1], str(hello.get("role", "")))
        except GameError as e:
            await ws.send_json({"type": "error", "text": str(e)})
            await ws.close()
            return
        clients[ws] = player.id
        await ws.send_json({"type": "welcome", "id": player.id, "info": game.static_info(),
                            "state": {"t": 0, **game.view(player, True)}})
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            try:
                if kind == "move":
                    game.set_move(player, _num(msg, "dx"), _num(msg, "dz"))
                elif kind == "action":
                    game.act(player, str(msg.get("action", "")), msg)
            except (GameError, ValueError) as e:
                await ws.send_json({"type": "error", "text": str(e) or "操作无效"})
    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(ws, None)
        if player is not None:
            game.leave(player.id)
