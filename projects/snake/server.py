"""贪吃蛇的服务器部分：只返回页面。游戏逻辑全部在浏览器里运行（static/game.js）。

挂载在 /apps/snake/ 下（见 projects/snake/__init__.py）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.pages import html_page

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"


@router.get("/")
def index():
    return html_page(STATIC / "index.html")
