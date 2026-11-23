"""网球服务器测试：建房权限、大厅、先到先得、房主解散、比赛开始。"""
from __future__ import annotations

import secrets

import pytest
from starlette.websockets import WebSocketDisconnect

from . import server as srv

WS = "/apps/tennis/ws"


@pytest.fixture(autouse=True)
def clean_rooms():
    """房间只在内存里：每个测试开始前清空，避免互相影响。"""
    srv.rooms.clear()
    srv.room_members.clear()
    srv.conns.clear()
    srv.lobby_conns.clear()
    yield
    srv.rooms.clear()
    srv.room_members.clear()
    srv.conns.clear()
    srv.lobby_conns.clear()


def registered(client, name):
    r = client.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"session": r.cookies["session"]}, r.json()


def guest(client):
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    assert r.status_code == 200, r.text
    return {"session": r.cookies["session"]}, r.json()


def create(client, cookies, name="球场", mode="single"):
    return client.post("/apps/tennis/api/rooms", json={"name": name, "mode": mode}, cookies=cookies)


def connect(client, cookies):
    return client.websocket_connect(WS, headers={"cookie": f"session={cookies['session']}"})


def expect(ws, kind, limit=200, where=None):
    """读消息，直到遇到指定类型（并满足条件）的消息。比赛循环会不断发 state，旧消息会跳过。"""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind and (where is None or where(msg)):
            return msg
    raise AssertionError(f"没有收到 {kind}")


def test_guest_cannot_create_room(client):
    cookies, _ = guest(client)
    r = create(client, cookies)
    assert r.status_code == 403
    assert "注册" in r.json()["detail"]


def test_anonymous_cannot_list_or_create(client):
    client.cookies.clear()
    assert client.get("/apps/tennis/api/rooms").status_code == 401
    assert client.post("/apps/tennis/api/rooms", json={"name": "x", "mode": "single"}).status_code == 401


def test_registered_user_creates_room_and_everyone_sees_it(client):
    host_cookies, _ = registered(client, "tennis_host")
    r = create(client, host_cookies, "周末来一局", "double")
    assert r.status_code == 200, r.text
    room = r.json()
    assert room["mode"] == "double" and room["capacity"] == 4 and room["players"] == 1
    guest_cookies, _ = guest(client)
    rooms = client.get("/apps/tennis/api/rooms", cookies=guest_cookies).json()["rooms"]
    assert [x["name"] for x in rooms] == ["周末来一局"]


def test_one_room_per_host_and_validation(client):
    cookies, _ = registered(client, "tennis_one")
    assert create(client, cookies, "A").status_code == 200
    assert create(client, cookies, "B").status_code == 409
    other, _ = registered(client, "tennis_two")
    assert create(client, other, "").status_code == 400
    assert create(client, other, "x", "triple").status_code == 400


def test_first_come_first_served_seats(client):
    host, _ = registered(client, "tennis_fcfs")
    room_id = create(client, host, "先到先得").json()["id"]
    a, _ = guest(client)
    b, _ = guest(client)
    with connect(client, host) as hws, connect(client, a) as aws, connect(client, b) as bws:
        expect(hws, "hello"); expect(aws, "hello"); expect(bws, "hello")
        hws.send_json({"type": "join", "roomId": room_id})
        assert expect(hws, "state")["room"]["id"] == room_id
        aws.send_json({"type": "join", "roomId": room_id})          # 第 2 个人：成功
        assert expect(aws, "state")["room"]["id"] == room_id
        bws.send_json({"type": "join", "roomId": room_id})          # 房间已满
        assert expect(bws, "error")["text"] == "房间已满"


def test_host_leaving_dissolves_room_for_others(client):
    host, _ = registered(client, "tennis_dissolve")
    room_id = create(client, host, "会解散").json()["id"]
    guest_cookies, _ = guest(client)
    with connect(client, host) as hws, connect(client, guest_cookies) as gws:
        expect(hws, "hello"); expect(gws, "hello")
        hws.send_json({"type": "join", "roomId": room_id})
        expect(hws, "state")
        gws.send_json({"type": "join", "roomId": room_id})
        expect(gws, "state")
        hws.send_json({"type": "leave"})
        msg = expect(gws, "closed")
        assert "解散" in msg["text"]
    assert client.get("/apps/tennis/api/rooms", cookies=guest_cookies).json()["rooms"] == []


def test_match_starts_when_full_and_only_host_can_start(client):
    host, _ = registered(client, "tennis_start")
    room_id = create(client, host, "开赛").json()["id"]
    guest_cookies, _ = guest(client)
    with connect(client, host) as hws, connect(client, guest_cookies) as gws:
        expect(hws, "hello"); expect(gws, "hello")
        hws.send_json({"type": "join", "roomId": room_id}); expect(hws, "state")
        hws.send_json({"type": "start"})
        assert expect(hws, "error")["text"] == "人还没坐满，不能开始"
        gws.send_json({"type": "join", "roomId": room_id}); expect(gws, "state")
        gws.send_json({"type": "start"})
        assert expect(gws, "error")["text"] == "只有房主可以开始比赛"
        hws.send_json({"type": "start"})
        state = expect(gws, "state")
        assert state["status"] == "playing"
        assert state["phase"] == "serve_wait"
        # 发球人抛球，正在上升的球要被服务器计算
        server_seat = state["serveSeat"]
        server_ws = hws if server_seat == 0 else gws
        server_ws.send_json({"type": "stick", "f": 1, "r": 1})          # 发球时不能移动
        server_ws.send_json({"type": "swing", "stroke": "top", "aimR": 0, "aimF": 0})
        expect(server_ws, "state", where=lambda m: m["phase"] == "toss")


def test_guest_can_join_but_websocket_needs_login(client):
    host, _ = registered(client, "tennis_auth")
    room_id = create(client, host, "需要登录").json()["id"]
    client.cookies.clear()
    try:
        with client.websocket_connect(WS) as ws:
            assert expect(ws, "auth")["text"] == "请先登录"
    except WebSocketDisconnect:
        pass
    guest_cookies, _ = guest(client)
    with connect(client, guest_cookies) as gws:
        expect(gws, "hello")
        gws.send_json({"type": "join", "roomId": room_id})
        assert expect(gws, "state")["room"]["id"] == room_id
