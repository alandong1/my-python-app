"""卡坦岛的房间和联机流程：用 WebSocket 模拟 3 位玩家（3 个各自独立的 cookie）。"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app.main import app
from projects.catan import server


def guest_client():
    """每位玩家一个独立的 cookie（相当于不同的浏览器），都是游客账号。"""
    c = TestClient(app)
    assert c.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)}).status_code == 200
    return c


def recv_until(ws, pred, limit=30):
    for _ in range(limit):
        msg = ws.receive_json()
        if pred(msg):
            return msg
    raise AssertionError("没有收到期望的消息")


def is_state(msg):
    return msg.get("type") == "state"


def room_state(ws):
    """等到一条「在房间里」的状态（连接后服务器先发一条 room=None 的状态）。"""
    return recv_until(ws, lambda m: is_state(m) and m.get("room"))


def error_text(ws):
    return recv_until(ws, lambda m: m["type"] == "error")["text"]


@pytest.fixture(autouse=True)
def clear_rooms():
    server.rooms.clear()
    server.user_room.clear()
    yield
    server.rooms.clear()
    server.user_room.clear()


@pytest.fixture
def logged_in(client):
    """client 是平台测试的客户端；登录一个游客，用它做房主。"""
    assert client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)}).status_code == 200
    return client


def test_page_opens_and_static_files(client):
    r = client.get("/apps/catan/")
    assert r.status_code == 200
    assert 'id="app"' in r.text
    assert "static/game.js" in r.text
    for path in ("static/game.js", "static/style.css"):
        assert client.get(f"/apps/catan/{path}").status_code == 200, path


def test_store_lists_catan_with_login(client):
    apps = client.get("/api/apps").json()["apps"]
    card = next(a for a in apps if a["slug"] == "catan")
    assert card["url"] == "/apps/catan/" and card["requiresLogin"] is True


def test_websocket_requires_login(client):
    with client.websocket_connect("/apps/catan/ws") as ws:
        assert ws.receive_json()["type"] == "auth"


def test_lobby_join_start_rules(logged_in):
    host = logged_in
    p2, p3 = guest_client(), guest_client()
    with host.websocket_connect("/apps/catan/ws") as w1, \
            p2.websocket_connect("/apps/catan/ws") as w2, \
            p3.websocket_connect("/apps/catan/ws") as w3:
        w1.send_json({"type": "create"})
        code = room_state(w1)["room"]["code"]
        assert len(code) == 5

        w2.send_json({"type": "join", "code": code.lower()})          # 大小写不敏感
        room_state(w2)
        w2.send_json({"type": "start"})                                # 不是房主
        assert error_text(w2) == "只有房主可以开始游戏"
        w2.send_json({"type": "start"})
        w1.send_json({"type": "start"})                                # 只有 2 人
        assert error_text(w1) == "至少需要 3 人才能开始"

        w3.send_json({"type": "join", "code": code})
        lobby = recv_until(w1, lambda m: is_state(m) and m["room"] and len(m["room"]["players"]) == 3)
        assert lobby["room"]["isHost"] is True and lobby["game"] is None
        w1.send_json({"type": "start"})
        started = recv_until(w1, lambda m: is_state(m) and m.get("game"))
        assert started["game"]["phase"] == "setup"
        assert len(started["game"]["board"]["hexes"]) == 19

        p4 = guest_client()                                             # 第 4 位新玩家：游戏开始后不能加入
        with p4.websocket_connect("/apps/catan/ws") as w4:
            room_state_skip = recv_until(w4, is_state)                  # 连接后的初始状态
            assert room_state_skip["room"] is None
            w4.send_json({"type": "join", "code": code})
            assert "已经开始" in error_text(w4)


def _state_of(ws):
    return recv_until(ws, lambda m: is_state(m) and m.get("game"))


def test_full_setup_then_roll_over_websocket(logged_in):
    host = logged_in
    p2, p3 = guest_client(), guest_client()
    with host.websocket_connect("/apps/catan/ws") as w1, \
            p2.websocket_connect("/apps/catan/ws") as w2, \
            p3.websocket_connect("/apps/catan/ws") as w3:
        wss = [w1, w2, w3]
        w1.send_json({"type": "create"})
        code = room_state(w1)["room"]["code"]
        for w in (w2, w3):
            w.send_json({"type": "join", "code": code})
            room_state(w)
        w1.send_json({"type": "start"})
        states = [_state_of(w) for w in wss]
        seat_ws = {s["game"]["me"]["seat"]: w for s, w in zip(states, wss)}

        # 开局：12 个动作（每位玩家一村一路，共 3 轮），每次由当前该放子的人操作
        for _ in range(12):
            g = states[0]["game"]
            w = seat_ws[g["setup"]["seat"]]
            legal = states[wss.index(w)]["game"]["legal"]
            if g["setup"]["sub"] == "settlement":
                w.send_json({"type": "action", "action": "setup_settlement",
                             "vertex": legal["vertices"][0]})
            else:
                w.send_json({"type": "action", "action": "setup_road", "edge": legal["edges"][0]})
            states = [_state_of(x) for x in wss]
        assert states[0]["game"]["phase"] == "roll"

        cur = states[0]["game"]["turn"]
        other = next(w for s, w in seat_ws.items() if s != cur)
        other.send_json({"type": "action", "action": "roll"})
        assert error_text(other) == "现在不是你的回合"

        seat_ws[cur].send_json({"type": "action", "action": "roll"})
        states = [_state_of(x) for x in wss]
        assert states[0]["game"]["dice"] is not None
        assert states[0]["game"]["phase"] in ("play", "discard", "robber")
        # 别人看不到我的手牌，只看到数量
        for st, w in zip(states, wss):
            me = st["game"]["me"]["seat"]
            for p in st["game"]["players"]:
                if p["seat"] != me:
                    assert set(p.keys()) >= {"cards", "devCount"}
                    assert "hand" not in p


def test_leave_lobby_and_reconnect_restores_room(logged_in):
    other = guest_client()
    with logged_in.websocket_connect("/apps/catan/ws") as w1, \
            other.websocket_connect("/apps/catan/ws") as w2:
        w1.send_json({"type": "create"})
        code = room_state(w1)["room"]["code"]
        w2.send_json({"type": "join", "code": code})
        room_state(w2)
        w2.send_json({"type": "leave"})
        assert recv_until(w2, is_state)["room"] is None
        # 房主看到人数变回 1
        assert recv_until(w1, lambda m: is_state(m) and m["room"] and len(m["room"]["players"]) == 1)
    # 房主刷新页面（重新连接），直接回到原来的房间
    with logged_in.websocket_connect("/apps/catan/ws") as w3:
        assert room_state(w3)["room"]["code"] == code


def test_errors_for_missing_room_and_bad_actions(logged_in):
    with logged_in.websocket_connect("/apps/catan/ws") as ws:
        ws.send_json({"type": "join", "code": "NOPE1"})
        assert "没有这个房间" in error_text(ws)
        ws.send_json({"type": "action", "action": "roll"})
        assert error_text(ws) == "你还没有加入房间"
        ws.send_json({"type": "create"})
        room_state(ws)
        ws.send_json({"type": "action", "action": "roll"})
        assert error_text(ws) == "游戏还没有开始"
        ws.send_json({"type": "action", "action": "does_not_exist"})
        assert error_text(ws) == "游戏还没有开始"
