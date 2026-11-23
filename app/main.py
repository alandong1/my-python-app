"""FastAPI 服务器：提供网页 + 账户接口 + WebSocket 实时通信 + 游戏主循环。

运行：uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import config as C
from .auth import SESSION_COOKIE, lookup_session_user
from .auth import router as auth_router
from .db import describe_db, init_db
from .game import Game, GameError, Player

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("game")
STATIC = Path(__file__).resolve().parent.parent / "static"

seed = os.environ.get("MAP_SEED")
game = Game(int(seed) if seed else None)
clients: Dict[WebSocket, Player] = {}


async def game_loop():
    while True:
        await asyncio.sleep(C.TICK_SECONDS)
        try:
            game.tick()
            board = game.scoreboard()
            for ws, p in list(clients.items()):
                msg = game.view_for(p)
                msg["players"] = board
                try:
                    await ws.send_json(msg)
                except Exception:
                    clients.pop(ws, None)
        except Exception:
            log.exception("tick 出错")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("数据库：%s", describe_db())
    await run_in_threadpool(init_db)
    task = asyncio.create_task(game_loop())
    yield
    task.cancel()


app = FastAPI(title="领主战争", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(auth_router)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    return {"ok": True, "players": len(game.players), "online": len(clients), "tick": game.tick_no}


ACTIONS = {
    "expand": lambda p, m: game.expand(p, int(m["x"]), int(m["y"])),
    "build": lambda p, m: game.build(p, int(m["x"]), int(m["y"]), str(m["building"])),
    "upgrade": lambda p, m: game.upgrade(p, int(m["x"]), int(m["y"])),
    "demolish": lambda p, m: game.demolish(p, int(m["x"]), int(m["y"])),
    "train": lambda p, m: game.train(p, str(m["unit"]), int(m.get("count", 1))),
    "research": lambda p, m: game.research(p, str(m["kind"])),
    "move": lambda p, m: game.move(p, int(m["army"]), int(m["x"]), int(m["y"]),
                                   float(m.get("fraction", 1.0))),
    "stop": lambda p, m: game.stop(p, int(m["army"])),
    "respawn": lambda p, m: game.respawn(p),
}


def _same_origin(ws: WebSocket) -> bool:
    """拒绝其他网站发起的 WebSocket 连接（防止别的网站借用玩家的登录状态）。"""
    origin = ws.headers.get("origin")
    if not origin:
        return True  # 非浏览器客户端
    return urlsplit(origin).netloc == ws.headers.get("host")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not _same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    player: Optional[Player] = None
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
        player = game.join(*account)
        player.online += 1
        game._compute_vision(player)
        explored = [[x, y, game.tile(x, y).terrain] for x, y in player.explored]
        await ws.send_json({"type": "welcome", "id": player.id, "name": player.name,
                            "info": game.static_info(), "explored": explored})
        clients[ws] = player
        while True:
            msg = await ws.receive_json()
            fn = ACTIONS.get(msg.get("type"))
            if not fn:
                continue
            try:
                fn(player, msg)
            except GameError as e:
                await ws.send_json({"type": "error", "text": str(e)})
            except (KeyError, ValueError, TypeError):
                await ws.send_json({"type": "error", "text": "无效的指令"})
    except WebSocketDisconnect:
        pass
    except GameError as e:
        await ws.send_json({"type": "error", "text": str(e)})
    finally:
        clients.pop(ws, None)
        if player:
            player.online -= 1
