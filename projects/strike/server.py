"""突击行动的服务器部分：页面、WebSocket、广播循环。

挂载在 /apps/strike/ 下（见 projects/strike/__init__.py）。
协议（JSON）：
  浏览器 → 服务器
    {"t":"join","name":"昵称"}
    {"t":"in","seq":1,"fwd":1,"side":0,"yaw":0,"pitch":0,"dt":0.033}   移动输入（约每秒 30 次）
    {"t":"fire"}                                                       开火
    {"t":"buy","weapon":"smg"}                                         买武器（自动装备）
    {"t":"equip","slot":"primary"}                                     切换主武器 / 副武器
    {"t":"scope","on":true}                                            开 / 关狙击镜
  服务器 → 浏览器
    {"t":"welcome","id":1,"map":{...},"sim":{...}}                     进入房间时发一次
    {"t":"state","you":{...},"players":[...],"events":[...],"teams":[红队击杀,蓝队击杀]}   每 0.05 秒一次
    {"t":"error","text":"..."}
"""
from __future__ import annotations

import asyncio
import logging
import math
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import ws_same_origin
from app.pages import html_page

from . import config as C
from .game import Arena

log = logging.getLogger("strike")
STATIC = Path(__file__).resolve().parent / "static"

router = APIRouter()
arena = Arena()
clients: Dict[WebSocket, int] = {}     # 连接 → 玩家 id
_loop_task: Optional[asyncio.Task] = None

MAP = {"half": C.ARENA_HALF, "walls": C.WALLS, "spawns": C.SPAWNS}
SIM = {
    "radius": C.PLAYER_RADIUS, "height": C.PLAYER_HEIGHT, "eye": C.EYE_HEIGHT,
    "head": C.HEAD_HEIGHT, "speed": C.MOVE_SPEED, "maxDt": C.MAX_DT,
    "maxPitch": C.MAX_PITCH, "maxHp": C.MAX_HP,
    "respawn": C.RESPAWN_SECONDS, "tick": C.TICK_SECONDS,
    "weapons": C.WEAPONS,
}


@router.get("/")
def index():
    return html_page(STATIC / "index.html")


def _num(msg: dict, key: str, lo: float, hi: float) -> float:
    """从消息里取一个有限的数字，并限制在 [lo, hi] 之间。不是数字就抛出 ValueError。"""
    v = msg.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"字段 {key} 不合法")
    return min(max(float(v), lo), hi)


def _clean_name(raw: Any) -> str:
    name = str(raw or "").strip()[: C.MAX_NAME]
    return name or "匿名玩家"


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not ws_same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    pid: Optional[int] = None
    try:
        hello = await ws.receive_json()
        if not isinstance(hello, dict) or hello.get("t") != "join":
            await ws.send_json({"t": "error", "text": "第一条消息必须是 join"})
            await ws.close(code=4400)
            return
        if arena.human_count() >= C.MAX_PLAYERS:
            await ws.send_json({"t": "error", "text": "房间已满，请稍后再来"})
            await ws.close(code=4409)
            return
        player = arena.add_player(_clean_name(hello.get("name")))
        arena.balance_bots()          # 有人加入：踢掉相应数量的电脑，保持总人数
        pid = player.id
        # 先发欢迎消息，再加入广播名单，保证浏览器总是先收到地图再收到状态
        await ws.send_json({"t": "welcome", "id": pid, "map": MAP, "sim": SIM})
        clients[ws] = pid
        log.info("玩家加入：%s（%d 人在线）", player.name, len(arena.players))

        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                raise ValueError("消息必须是对象")
            t = msg.get("t")
            if t == "in":
                arena.input(
                    pid,
                    seq=int(_num(msg, "seq", 0, 1e12)),
                    fwd=_num(msg, "fwd", -1, 1),
                    side=_num(msg, "side", -1, 1),
                    yaw=_num(msg, "yaw", -1e6, 1e6),
                    pitch=_num(msg, "pitch", -C.MAX_PITCH, C.MAX_PITCH),
                    dt=_num(msg, "dt", 0, C.MAX_DT),
                )
            elif t == "fire":
                arena.fire(pid)
            elif t == "buy":
                wid = msg.get("weapon")
                if isinstance(wid, str):
                    arena.buy(pid, wid)
            elif t == "equip":
                slot = msg.get("slot")
                if isinstance(slot, str):
                    arena.equip(pid, slot)
            elif t == "scope":
                arena.set_scope(pid, msg.get("on") is True)
            # 其他类型的消息直接忽略，保持向前兼容
    except WebSocketDisconnect:
        pass
    except ValueError as e:            # 包括 JSON 解析错误（json.JSONDecodeError 是 ValueError）
        log.info("玩家发来无效消息：%s", e)
        with suppress(Exception):
            await ws.send_json({"t": "error", "text": f"消息格式不对：{e}"})
            await ws.close(code=4400)
    finally:
        clients.pop(ws, None)
        if pid is not None:
            arena.remove_player(pid)
            arena.balance_bots()      # 有人离开：补回电脑，保持总人数
            log.info("玩家离开（%d 人在线）", len(arena.players))


async def game_loop():
    """每 TICK_SECONDS 秒：复活到期的人，然后把状态发给所有人。一个玩家出错不影响其他人。"""
    while True:
        await asyncio.sleep(C.TICK_SECONDS)
        try:
            arena.tick()
            events = arena.take_events()
            if not clients:
                continue
            players = arena.roster()
            for ws, pid in list(clients.items()):
                msg = {"t": "state", "you": arena.you(pid), "players": players, "events": events,
                       "teams": arena.team_kills}
                try:
                    await ws.send_json(msg)
                except Exception:
                    clients.pop(ws, None)
        except Exception:
            log.exception("突击行动的广播出错")


async def startup():
    global _loop_task
    arena.balance_bots()          # 房间刚启动时，先放上电脑玩家
    _loop_task = asyncio.create_task(game_loop())


async def shutdown():
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await _loop_task
        _loop_task = None
    for ws in list(clients):
        with suppress(Exception):
            await ws.close(code=1001)
    clients.clear()


def health() -> dict:
    return {"players": len(arena.players), "humans": arena.human_count(), "max": C.MAX_PLAYERS}
