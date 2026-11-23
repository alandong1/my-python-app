"""突击行动：页面、大厅、建房权限、房间规则（房主、踢人、电脑、解散、房主断线保留）、翻译齐全。"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from projects.strike import config as C
from projects.strike import server as srv

HERE = Path(__file__).resolve().parent
WS = "/apps/strike/ws"


@pytest.fixture(autouse=True)
def clean_rooms():
    """房间只在内存里：每个测试前后清空，避免互相影响。"""
    srv.rooms.clear()
    srv.conns.clear()
    yield
    srv.rooms.clear()
    srv.conns.clear()


def lang_keys():
    text = (HERE / "static" / "lang.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)*)":', text, re.M))


def registered(client, name):
    r = client.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"session": r.cookies["session"]}


def guest(client):
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    assert r.status_code == 200, r.text
    return {"session": r.cookies["session"]}


def connect(client, cookies):
    return client.websocket_connect(WS, headers={"cookie": f"session={cookies['session']}"})


def expect(ws, kind, limit=300):
    """读消息，直到收到某种类型的消息（中间的状态消息会被跳过）。"""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("t") == kind:
            return msg
    raise AssertionError(f"没有收到 {kind}")


def lobby_rooms(client, cookies):
    with connect(client, cookies) as ws:
        return expect(ws, "lobby")["rooms"]


# ---------------------------------------------------------------- 页面和接口

def test_page_opens_and_static_files_are_served(client):
    r = client.get("/apps/strike/")
    assert r.status_code == 200
    assert 'id="view"' in r.text and 'type="module" src="static/game.js' in r.text
    for path in ("static/game.js", "static/style.css", "static/lang.js", "static/assets/city.exr",
                 "static/vendor/three.module.min.js"):
        assert client.get(f"/apps/strike/{path}").status_code == 200, path


def test_store_lists_strike_and_requires_login(client):
    card = next(a for a in client.get("/api/apps").json()["apps"] if a["slug"] == "strike")
    assert card["url"] == "/apps/strike/"
    assert card["requiresLogin"] is True


def test_websocket_needs_login(client):
    client.cookies.clear()
    with client.websocket_connect(WS) as ws:
        assert ws.receive_json()["t"] == "error"


def test_health_reports_rooms(client):
    info = client.get("/health").json()["projects"]["strike"]
    assert info["rooms"] == 0 and info["max"] == 12


def test_script_strings_are_translated():
    game = (HERE / "static" / "game.js").read_text(encoding="utf-8")
    literals = set(re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', game))
    assert len(literals) >= 5
    missing = sorted(literals - lang_keys())
    assert not missing, missing


def test_page_text_is_translated():
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    texts = set(re.findall(r"<[^>]*\sdata-i18n>([^<]+)<", html))
    texts |= set(re.findall(r'data-i18n-(?:ph|title|aria)="([^"]+)"', html))
    texts.add("突击行动 · Dev Lab")
    missing = sorted(t.strip() for t in texts if t.strip() and t.strip() not in lang_keys() and t.strip() != "Dev Lab")
    assert not missing, missing


# ---------------------------------------------------------------- 建房权限和大厅

def test_guest_cannot_create_room(client):
    with connect(client, guest(client)) as ws:
        expect(ws, "lobby")
        ws.send_json({"t": "create", "name": "游客的房"})
        assert expect(ws, "error")["text"] == "注册账号后才能建房"
    assert srv.rooms == {}


def test_registered_user_creates_room_and_everyone_sees_it(client):
    host = registered(client, "strike_host")
    with connect(client, host) as hws:
        expect(hws, "lobby")
        hws.send_json({"t": "create", "name": "夜战"})
        welcome = expect(hws, "welcome")
        assert welcome["room"]["isHost"] is True and welcome["room"]["name"] == "夜战"
    rooms = lobby_rooms(client, guest(client))
    assert [r["name"] for r in rooms] == ["夜战"]


def test_one_room_per_host(client):
    host = registered(client, "strike_one")
    with connect(client, host) as ws:
        expect(ws, "lobby")
        ws.send_json({"t": "create", "name": "A"})
        expect(ws, "welcome")
        ws.send_json({"t": "leave"})               # 房主离开 = 解散
        expect(ws, "lobby")
        ws.send_json({"t": "create", "name": "B"})
        expect(ws, "welcome")
        ws.send_json({"t": "create", "name": "C"})
        assert "已经" in expect(ws, "error")["text"]


# ---------------------------------------------------------------- 房间规则

def create_room(client, host, name="房间"):
    ws = connect(client, host).__enter__()
    expect(ws, "lobby")
    ws.send_json({"t": "create", "name": name})
    welcome = expect(ws, "welcome")
    return ws, welcome


def test_host_fills_room_with_bots_and_guests_join_freely(client):
    host = registered(client, "strike_fill")
    hws, welcome = create_room(client, host, "填满")
    room_id = welcome["room"]["id"]
    assert srv.rooms[room_id].human_count() == 1
    assert len(srv.rooms[room_id].arena.players) == C.MIN_ONLINE    # 一个人 + 七台电脑
    g = guest(client)
    with connect(client, g) as gws:
        expect(gws, "lobby")
        gws.send_json({"t": "join", "room": room_id})
        expect(gws, "welcome")
        assert srv.rooms[room_id].human_count() == 2
        assert len(srv.rooms[room_id].arena.players) == C.MIN_ONLINE    # 踢掉一台电脑，总数不变
    assert srv.rooms[room_id].human_count() == 1                        # 游客离开，房间还在
    hws.__exit__(None, None, None)


def test_host_can_kick_and_others_cannot(client):
    host = registered(client, "strike_kick")
    hws, welcome = create_room(client, host, "踢人")
    room_id = welcome["room"]["id"]
    g = guest(client)
    gws = connect(client, g).__enter__()
    expect(gws, "lobby")
    gws.send_json({"t": "join", "room": room_id})
    gwel = expect(gws, "welcome")
    # 游客不能踢人
    gws.send_json({"t": "kick", "id": welcome["id"]})
    assert "只有房主" in expect(gws, "error")["text"]
    # 房主踢游客
    hws.send_json({"t": "kick", "id": gwel["id"]})
    notice = expect(gws, "lobby")
    assert "请出了房间" in notice["notice"]
    assert srv.rooms[room_id].human_count() == 1
    gws.__exit__(None, None, None)
    hws.__exit__(None, None, None)


def test_host_adds_and_removes_bots(client):
    host = registered(client, "strike_bots")
    hws, welcome = create_room(client, host, "电脑")
    room = srv.rooms[welcome["room"]["id"]]
    before = room.bot_count()
    hws.send_json({"t": "bots", "delta": 1})
    hws.send_json({"t": "bots", "delta": 1})
    hws.send_json({"t": "bots", "delta": -1})
    state = expect(hws, "state")                 # 房间里的人看到的是房间状态，不是大厅
    assert room.bot_count() == before + 1
    assert state["room"]["botExtra"] == 1
    hws.__exit__(None, None, None)


def test_host_disconnect_keeps_room_and_host_comes_back(client):
    host = registered(client, "strike_back")
    hws, welcome = create_room(client, host, "留着")
    room_id = welcome["room"]["id"]
    hws.__exit__(None, None, None)              # 房主关闭网页
    assert room_id in srv.rooms                  # 房间还在
    assert srv.rooms[room_id].host_online is False
    assert srv.rooms[room_id].human_count() == 0
    # 房主回来：仍然是他的房间
    with connect(client, host) as ws:
        expect(ws, "lobby")
        ws.send_json({"t": "join", "room": room_id})
        welcome = expect(ws, "welcome")
        assert welcome["room"]["isHost"] is True
        assert srv.rooms[room_id].host_online is True


def test_non_host_leave_keeps_room(client):
    host = registered(client, "strike_stay")
    hws, welcome = create_room(client, host, "留人")
    room_id = welcome["room"]["id"]
    g = guest(client)
    with connect(client, g) as gws:
        expect(gws, "lobby")
        gws.send_json({"t": "join", "room": room_id})
        expect(gws, "welcome")
        gws.send_json({"t": "leave"})
        expect(gws, "lobby")
    assert room_id in srv.rooms
    hws.__exit__(None, None, None)


def test_host_disband_sends_everyone_to_lobby(client):
    host = registered(client, "strike_disband")
    hws, welcome = create_room(client, host, "解散")
    room_id = welcome["room"]["id"]
    g = guest(client)
    gws = connect(client, g).__enter__()
    expect(gws, "lobby")
    gws.send_json({"t": "join", "room": room_id})
    expect(gws, "welcome")
    hws.send_json({"t": "disband"})
    notice = expect(gws, "lobby")
    assert "解散" in notice["notice"]
    assert room_id not in srv.rooms
    gws.__exit__(None, None, None)
    hws.__exit__(None, None, None)


def test_state_carries_room_and_team_info(client):
    host = registered(client, "strike_state")
    hws, welcome = create_room(client, host, "状态")
    state = expect(hws, "state")
    assert state["room"]["isHost"] is True
    assert len(state["teams"]) == 2
    assert state["you"]["team"] in (0, 1)
    hws.__exit__(None, None, None)
