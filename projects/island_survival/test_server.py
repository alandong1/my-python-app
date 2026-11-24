"""荒岛求生的网络部分：登录、选角色、收发消息。"""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

WS = "/apps/island-survival/ws"


def receive_until(ws, kind: str, tries: int = 60) -> dict:
    """游戏循环一直在发 state 消息，这里跳过它们，直到等到想要的类型。"""
    for _ in range(tries):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"没有收到 {kind}")


def test_requires_login(client):
    with client.websocket_connect(WS) as ws:
        assert ws.receive_json()["type"] == "auth"


def test_rejects_other_websites(client):
    client.post("/api/auth/register", json={"username": "island_cross", "password": "secret123"})
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(WS, headers={"origin": "https://evil.example"}):
            pass


def test_join_with_a_role_and_play(client):
    client.post("/api/auth/register", json={"username": "island_player", "password": "secret123"})
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "join", "role": "doctor"})
        welcome = receive_until(ws, "welcome")
        info = welcome["info"]
        assert info["w"] == 200 and info["h"] == 200
        assert len(info["terrain"]) == 200 * 200              # 整张地图都发给了客户端
        assert info["roles"]["doctor"] == "医生"
        me = welcome["state"]["me"]
        assert me["role"] == "doctor" and me["health"] == 100 and me["dead"] is False
        assert me["name"]                                       # 名字来自平台账户

        # 制药需要草本植物，一开始没有：服务器应该返回一条错误，而不是崩溃
        ws.send_json({"type": "action", "action": "craft", "recipe": "medicine"})
        err = receive_until(ws, "error")
        assert "草本植物" in err["text"]

        # 移动消息不回复，但之后的状态里位置会变
        ws.send_json({"type": "move", "dx": 1, "dz": 0})
        state = receive_until(ws, "state")
        assert state["me"]["id"] == me["id"]
        assert any(p[0] == me["id"] for p in state["players"])


def test_bad_role_is_refused(client):
    client.post("/api/auth/register", json={"username": "island_badrole", "password": "secret123"})
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "join", "role": "warrior"})
        err = receive_until(ws, "error")
        assert "角色" in err["text"]


def test_garbage_numbers_do_not_crash_server(client):
    client.post("/api/auth/register", json={"username": "island_garbage", "password": "secret123"})
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "join", "role": "chef"})
        receive_until(ws, "welcome")
        ws.send_json({"type": "move", "dx": "abc", "dz": 0})
        err = receive_until(ws, "error")
        assert err["text"]
        ws.send_json({"type": "move", "dx": 1e9, "dz": 0})
        receive_until(ws, "error")


def test_world_is_saved_and_loaded(client):
    import asyncio
    from projects.island_survival import server
    asyncio.run(server.save_now())
    loaded = asyncio.run(server.load_world())
    assert loaded.seed == server.game.seed
    assert loaded.tick_no > 0                            # 世界一直在跑，存的是跑了一段时间之后的状态
    assert len(loaded.res) == len(server.game.res)
