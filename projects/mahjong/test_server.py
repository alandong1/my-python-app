"""湖北卡五星：页面能打开，和电脑玩能开局并打完一局，多人能进同一个房间。"""
import pytest

from projects.mahjong import room as room_mod


@pytest.fixture(autouse=True)
def fast_bots(monkeypatch):
    """测试里电脑不用停顿。"""
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)
    monkeypatch.setattr(room_mod, "NEXT_ROUND_DELAY", 0)


def next_state(ws, limit=2000):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == "state":
            return msg
        if msg.get("type") == "error":
            raise AssertionError(msg)
    raise AssertionError("没有收到牌局画面")


def test_page_opens_without_login(client):
    r = client.get("/apps/mahjong/")
    assert r.status_code == 200
    assert "static/game.js" in r.text
    assert client.get("/apps/mahjong/static/game.js").status_code == 200
    assert client.get("/apps/mahjong/static/style.css").status_code == 200


def test_store_lists_mahjong(client):
    data = client.get("/api/apps").json()
    card = next(a for a in data["apps"] if a["slug"] == "mahjong")
    assert card["url"] == "/apps/mahjong/"
    assert card["requiresLogin"] is False


def test_solo_game_plays_a_full_round_to_the_end(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "name": "测试", "rounds": 1})
        state = None
        dinged = False
        for _ in range(4000):
            state = next_state(ws)
            if state["state"] in ("round_end", "match_end"):
                break
            rnd = state["round"]
            if rnd["phase"] == "ding":
                if not dinged:
                    ws.send_json({"type": "ding", "suit": 0})
                    dinged = True
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


def test_hidden_hands_of_others_are_not_sent(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "name": "甲", "rounds": 1})
        state = next_state(ws)
        rnd = state["round"]
        assert len(rnd["hand"]) == 14
        assert rnd["handCounts"][0] == 14
        assert rnd["openHands"] == [None, None, None]
        assert "hands" not in rnd


def test_two_humans_and_a_computer_share_a_room(client):
    with client.websocket_connect("/apps/mahjong/ws") as host:
        host.send_json({"type": "create", "name": "房主", "rounds": 4})
        code = host.receive_json()["code"]
        first = next_state(host)
        assert first["code"] == code
        assert first["isHost"] is True
        with client.websocket_connect("/apps/mahjong/ws") as guest:
            guest.send_json({"type": "join", "code": code.lower(), "name": "朋友"})
            guest.receive_json()
            seen = next_state(guest)
            assert sum(1 for s in seen["seats"] if s) == 2
            assert seen["isHost"] is False
            assert next_state(host)["seats"][1]["name"] == "朋友"   # 房主也收到了加入的画面
            host.send_json({"type": "start"})
            started = next_state(host)
            assert started["state"] == "playing"
            assert all(s is not None for s in started["seats"])
            assert [s["bot"] for s in started["seats"]] == [False, False, True]


def test_third_human_is_refused_only_when_room_is_full_of_humans(client):
    """三人版：房间里已经有三名真人，第四个人加入会被拒绝。"""
    sockets = []
    try:
        ws0 = client.websocket_connect("/apps/mahjong/ws").__enter__()
        sockets.append(ws0)
        ws0.send_json({"type": "create", "name": "a", "rounds": 1})
        code = ws0.receive_json()["code"]
        next_state(ws0)
        for name in ("b", "c"):
            ws = client.websocket_connect("/apps/mahjong/ws").__enter__()
            sockets.append(ws)
            ws.send_json({"type": "join", "code": code, "name": name})
            ws.receive_json()
            next_state(ws)
        ws3 = client.websocket_connect("/apps/mahjong/ws").__enter__()
        sockets.append(ws3)
        ws3.send_json({"type": "join", "code": code, "name": "d"})
        msg = ws3.receive_json()
        assert msg["type"] == "error" and "房间已满" in msg["text"]
    finally:
        for ws in reversed(sockets):
            ws.__exit__(None, None, None)


def test_joining_unknown_room_reports_error(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "join", "code": "NOPE", "name": "x"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "没有这个房间" in msg["text"]
