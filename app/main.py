"""FastAPI 服务器：提供网页 + 账户接口 + WebSocket 实时通信 + 游戏主循环。

运行：uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import config as C
from . import settings
from .auth import SESSION_COOKIE, lookup_session_user
from .auth import router as auth_router
from .db import describe_db, init_db
from .game import Game, GameError, Player
from .persistence import dump_world, load_latest, save_snapshot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("game")
STATIC = Path(__file__).resolve().parent.parent / "static"

GAME_APP = "lordwar"          # 存档里用来区分不同游戏/应用
SAVE_INTERVAL = 30            # 有玩家在线时，每 30 秒存一次档
IDLE_SAVE_INTERVAL = 300      # 没人在线时，5 分钟存一次（离线玩家的资源仍在增长）

seed = os.environ.get("MAP_SEED")
game = Game(int(seed) if seed else None)   # 启动时如果有存档，会在 lifespan 里替换掉
clients: Dict[WebSocket, Player] = {}


class Saver:
    """负责定期存档。同一时间只允许一次写入。"""

    def __init__(self):
        self.last = time.monotonic()
        self.active_since_save = False   # 上次存档后是否有人在线
        self.task: Optional[asyncio.Task] = None

    def due(self) -> bool:
        if self.task and not self.task.done():
            return False
        elapsed = time.monotonic() - self.last
        return elapsed >= IDLE_SAVE_INTERVAL or (elapsed >= SAVE_INTERVAL and self.active_since_save)

    def start(self):
        """在游戏线程里拍快照，然后在后台写数据库，不耽误游戏运行。"""
        data = game.to_dict()
        payload = dump_world(data)
        self.last = time.monotonic()
        self.active_since_save = bool(clients)
        self.task = asyncio.create_task(self._write(data["version"], data["tick"], payload))

    async def _write(self, version, tick, payload):
        try:
            size = await run_in_threadpool(save_snapshot, GAME_APP, version, tick, payload)
            log.info("世界已存档：tick %s，%.1f KB", tick, size / 1024)
        except Exception:
            log.exception("存档失败")

    async def flush(self):
        """关闭服务器前调用：等正在进行的写入完成，再存最后一次。"""
        if self.task:
            await self.task
        self.start()
        await self.task


saver = Saver()


async def load_world() -> Game:
    try:
        data = await run_in_threadpool(load_latest, GAME_APP)
    except Exception:
        log.exception("读取存档失败，开一个新世界")
        data = None
    if data is None:
        log.info("没有存档，生成新世界")
        return game
    try:
        g = Game.from_dict(data)
        log.info("已读取存档：tick %s，%d 名玩家", g.tick_no, len(g.players))
        return g
    except (ValueError, KeyError, TypeError, IndexError) as e:
        log.warning("存档无法读取（%s），开一个新世界。新世界的存档会逐渐替换掉旧存档。", e)
        return game


async def game_loop():
    while True:
        await asyncio.sleep(C.TICK_SECONDS)
        try:
            game.tick()
            if clients:
                saver.active_since_save = True
            if saver.due():
                saver.start()
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
    log.info("版本：%s，数据库：%s", settings.GIT_COMMIT, describe_db())
    if settings.IS_RENDER and settings.DATABASE_URL.startswith("sqlite"):
        # 线上用 SQLite 的话，数据会在每次重启时丢失。宁可启动失败，也不要悄悄丢数据
        log.error("线上环境没有配置 DATABASE_URL！请在 Render 的 Environment 里添加 Neon 连接字符串。")
        raise RuntimeError("DATABASE_URL is required on Render")
    await run_in_threadpool(init_db)
    global game
    game = await load_world()
    task = asyncio.create_task(game_loop())
    yield
    # 关闭（包括 Render 部署新版本时）：先停止游戏循环，再存最后一次档
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await saver.flush()
    log.info("关闭前已存档")


app = FastAPI(title="领主战争", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(auth_router)


BOOT_TIME = datetime.now(timezone.utc)


@app.get("/")
async def index():
    # 给 js/css 地址加上版本号：每次部署后浏览器会自动加载新文件，不会用缓存里的旧版本
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for f in ("game.js", "style.css"):
        html = html.replace(f"/static/{f}", f"/static/{f}?v={settings.GIT_COMMIT}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health():
    return {"ok": True, "players": len(game.players), "online": len(clients), "tick": game.tick_no}


@app.get("/version")
async def version():
    """当前运行的是哪个 git 提交，用来确认新版本是否已经部署上线。"""
    return {
        "commit": settings.GIT_COMMIT,
        "started": BOOT_TIME.isoformat(timespec="seconds"),
        "db": "postgresql" if settings.DATABASE_URL.startswith("postgresql") else "sqlite",
    }


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
