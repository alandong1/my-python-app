"""湖北卡五星：页面能打开，登录后才能玩，和电脑玩能开局并打完一局，多人能进同一个房间，
私密房间要用房间号，断线后能重新连回，大厅的排行榜和商城能用。"""
import secrets

import pytest

from app.auth import SESSION_COOKIE
from projects.mahjong import room as room_mod


@pytest.fixture(autouse=True)
def fast_bots(monkeypatch):
    """测试里电脑不用停顿。"""
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)
    monkeypatch.setattr(room_mod, "NEXT_ROUND_DELAY", 0)


def new_guest(client):
    """换一个游客账号（之后打开的 WebSocket 就是这个账号）。"""
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    assert r.status_code == 200
    return r.json()


@pytest.fixture
def client_guest(client):
    new_guest(client)
    return client


def next_state(ws, limit=2000):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == "state":
            return msg
        if msg.get("type") == "error":
            raise AssertionError(msg)
    raise AssertionError("没有收到牌局画面")


def test_page_opens(client):
    r = client.get("/apps/mahjong/")
    assert r.status_code == 200
    assert "static/game.js" in r.text
    assert client.get("/apps/mahjong/static/game.js").status_code == 200
    assert client.get("/apps/mahjong/static/style.css").status_code == 200


def test_store_lists_mahjong_and_requires_login(client):
    data = client.get("/api/apps").json()
    card = next(a for a in data["apps"] if a["slug"] == "mahjong")
    assert card["url"] == "/apps/mahjong/"
    assert card["requiresLogin"] is True


def test_websocket_refuses_anonymous_players(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and "请先登录" in msg["text"]


def test_lobby_needs_login_and_shows_wallet(client_guest):
    r = client_guest.get("/apps/mahjong/api/lobby")
    assert r.status_code == 200
    data = r.json()
    assert data["me"]["points"] == 0
    assert set(data["shop"]) == {"swap", "lucky_pong", "miracle_hu"}
    assert data["myRoom"] is None and data["rooms"] == []


def test_buying_without_points_is_refused(client_guest):
    r = client_guest.post("/apps/mahjong/api/shop/buy", json={"item": "swap"})
    assert r.json() == {"ok": False, "text": "积分不够"}


def test_solo_game_plays_a_full_round_to_the_end(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "rounds": 1})
        state = None
        for _ in range(4000):
            state = next_state(ws)
            if state["state"] in ("round_end", "match_end"):
                break
            rnd = state["round"]
            if rnd["phase"] == "predraw" and rnd["turn"] == state["you"]:
                ws.send_json({"type": "predraw", "action": "skip"})
            elif rnd["phase"] == "discard" and rnd["turn"] == state["you"]:
                hu = [o for o in rnd["self"] if o["action"] == "hu"]
                if hu:
                    ws.send_json({"type": "self", "action": "hu"})
                else:
                    ws.send_json({"type": "discard", "kind": rnd["hand"][-1]})
            elif rnd["claim"]:
                ws.send_json({"type": "claim", "action": "pass"})
        assert state["state"] == "match_end"
        assert sum(state["scores"]) == 0
        assert len(state["seats"]) == 3
        assert [s["bot"] for s in state["seats"][1:]] == [True, True]


def test_hidden_hands_of_others_are_not_sent(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "rounds": 1})
        state = next_state(ws)
        rnd = state["round"]
        assert len(rnd["hand"]) in (13, 14)
        assert rnd["openHands"] == [None, None, None]
        assert "hands" not in rnd


def test_private_room_joined_by_four_digit_code(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as host:
        host.send_json({"type": "create", "rounds": 4, "visibility": "private"})
        code = host.receive_json()["code"]
        assert len(code) == 4 and code.isdigit()
        first = next_state(host)
        assert first["visibility"] == "private" and first["isHost"] is True
        # 私密房间不出现在大厅的公开列表里
        assert all(r["code"] != code for r in client_guest.get("/apps/mahjong/api/lobby").json()["rooms"])

        new_guest(client_guest)
        with client_guest.websocket_connect("/apps/mahjong/ws") as guest:
            guest.send_json({"type": "join", "code": code})
            guest.receive_json()
            seen = next_state(guest)
            assert sum(1 for s in seen["seats"] if s) == 2
            assert seen["isHost"] is False
            assert next_state(host)["seats"][1] is not None
            host.send_json({"type": "start", "items": False})
            started = next_state(host)
            assert started["state"] == "playing"
            assert [s["bot"] for s in started["seats"]] == [False, False, True]


def test_public_room_appears_in_lobby(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as host:
        host.send_json({"type": "create", "rounds": 1, "visibility": "public"})
        code = host.receive_json()["code"]
        next_state(host)
        listed = client_guest.get("/apps/mahjong/api/lobby").json()["rooms"]
        assert any(r["code"] == code and r["seats"] == 1 for r in listed)


def test_reconnect_after_drop_resumes_the_game(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "rounds": 4})
        first = next_state(ws)
        code = first["code"]
    # 掉线之后：大厅会显示正在进行的游戏
    lobby = client_guest.get("/apps/mahjong/api/lobby").json()
    assert lobby["myRoom"] == code
    with client_guest.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "resume", "code": code})
        ws.receive_json()                       # joined
        back = next_state(ws)
        assert back["state"] == "playing" and back["you"] == 0
        assert back["seats"][0]["away"] is False


def test_third_human_is_refused_when_room_is_full(client_guest):
    sockets = []
    try:
        ws0 = client_guest.websocket_connect("/apps/mahjong/ws").__enter__()
        sockets.append(ws0)
        ws0.send_json({"type": "create", "rounds": 1, "visibility": "private"})
        code = ws0.receive_json()["code"]
        next_state(ws0)
        for _ in range(2):
            new_guest(client_guest)
            ws = client_guest.websocket_connect("/apps/mahjong/ws").__enter__()
            sockets.append(ws)
            ws.send_json({"type": "join", "code": code})
            ws.receive_json()
            next_state(ws)
        new_guest(client_guest)
        ws3 = client_guest.websocket_connect("/apps/mahjong/ws").__enter__()
        sockets.append(ws3)
        ws3.send_json({"type": "join", "code": code})
        msg = ws3.receive_json()
        assert msg["type"] == "error" and "房间已满" in msg["text"]
    finally:
        for ws in reversed(sockets):
            ws.__exit__(None, None, None)


def test_joining_unknown_room_reports_error(client_guest):
    with client_guest.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "join", "code": "9999"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "没有这个房间" in msg["text"]
