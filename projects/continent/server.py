"""大陆争霸的服务器部分：页面和三个接口。挂载在 /apps/continent/ 下。

- GET  /api/catalog   ：单位、建筑、研究的数值（所有人都一样，客户端只取一次）
- GET  /api/state     ：自己能看到的世界（会顺便让玩家加入游戏、推进时间）
- POST /api/command   ：下命令（移动、攻击、建造、生产……），返回操作之后的世界

游戏世界在内存里，只有一份，所有玩家共享。用一把锁保护，因为 FastAPI 的同步接口
会在线程池里并行跑。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import require_user
from app.db import get_db
from app.pages import html_page

from .game import CATALOG, GameError, World

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"

_seed = os.environ.get("MAP_SEED")
world = World(int(_seed) if _seed else None)
_lock = threading.Lock()


def _who(request: Request):
    """返回 (用户 id, 显示名)。没登录会抛出 401。"""
    with get_db() as db:
        u = require_user(db, request)
        return u.id, u.display_name


@router.get("/")
def index():
    return html_page(STATIC / "index.html")


@router.get("/api/catalog")
def catalog():
    return CATALOG


@router.get("/api/state")
def state(request: Request):
    pid, name = _who(request)
    with _lock:
        world.advance_to(time.monotonic())
        world.join(pid, name)
        return world.view(pid)


@router.post("/api/command")
def command(body: dict, request: Request):
    pid, name = _who(request)
    with _lock:
        world.advance_to(time.monotonic())
        world.join(pid, name)
        try:
            world.command(pid, str(body.get("action", "")), body)
        except GameError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return world.view(pid)
