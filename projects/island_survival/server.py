"""荒岛求生的服务器部分：页面、WebSocket、游戏主循环、存档。

挂载在 /apps/island-survival/ 下（见 projects/island_survival/__init__.py）。

世界一直在运行，不管有没有人在线：树会长、动物会走、火会灭。
每 60 秒存一次档，服务器关闭前再存一次；启动时读回最近的存档。
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
from app.persistence import dump_world, load_latest, save_snapshot

from .game import DT, Game, GameError

log = logging.getLogger("island-survival")
STATIC = Path(__file__).resolve().parent / "static"

SLUG = "island-survival"                    # 存档里用来区分不同项目
SEED = int(os.environ.get("ISLAND_SEED", "2026"))
SAVE_EVERY = 60                             # 每 60 秒自动存档一次
RESOURCE_EVERY = 10                         # 资源列表每 10 个 tick（1 秒）发一次，省流量

game = Game(SEED)
clients: Dict[WebSocket, int] = {}          # 连接 → 玩家编号
_loop_task: Optional[asyncio.Task] = None
_save_task: Optional[asyncio.Task] = None


async def load_world() -> Game:
    """启动时读档；没有存档或版本不对，就从种子开始一个新世界。"""
    try:
        data = await run_in_threadpool(load_latest, SLUG)
    except Exception:
        log.exception("读取存档失败，使用新世界")
        return Game(SEED)
    if not data:
        return Game(SEED)
    try:
        return Game.from_dict(data)
    except (ValueError, KeyError, TypeError):
        log.exception("存档格式不对，使用新世界")
        return Game(SEED)


async def save_now() -> None:
    """拍一张快照（在主循环线程里，保证是同一时刻的完整状态），然后在线程池里写数据库。"""
    data = game.to_dict()
    payload = dump_world(data)
    try:
        size = await run_in_threadpool(save_snapshot, SLUG, Game.SAVE_VERSION, data["tick"], payload)
        log.info("世界已存档：tick %s，%.1f KB", data["tick"], size / 1024)
    except Exception:
        log.exception("存档失败")


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


async def autosave_loop() -> None:
    while True:
        await asyncio.sleep(SAVE_EVERY)
        await save_now()


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
    global game, _loop_task, _save_task
    game = await load_world()
    _loop_task = asyncio.create_task(game_loop())
    _save_task = asyncio.create_task(autosave_loop())


async def shutdown() -> None:
    """关闭（包括 Render 部署新版本时）：停止循环，存最后一次档，再断开所有人。"""
    for task in (_loop_task, _save_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await save_now()
    clients.clear()


def health() -> dict:
    return {"online": len(clients), "survivors": len(game.players),
            "saved_characters": len(game.saved), "tick": game.tick_no, "seed": game.seed}


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
