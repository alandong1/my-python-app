"""麻将：页面能打开，和电脑玩能开局并打完一局，多人能进同一个房间。"""
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
        for _ in range(3000):
            state = next_state(ws)
            if state["state"] in ("round_end", "match_end"):
                break
            rnd = state["round"]
            if rnd["phase"] == "discard" and rnd["turn"] == state["you"]:
                if any(o["action"] == "hu" for o in rnd["self"]):
                    ws.send_json({"type": "self", "action": "hu"})
                else:
                    ws.send_json({"type": "discard", "kind": rnd["hand"][-1]})
            elif rnd["claim"]:
                ws.send_json({"type": "claim", "action": "pass"})
        assert state["state"] == "match_end"
        assert sum(state["scores"]) == 0
        assert len(state["seats"]) == 4 and all(s["bot"] for s in state["seats"][1:])


def test_hidden_hands_of_others_are_not_sent(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "solo", "name": "甲", "rounds": 1})
        state = next_state(ws)
        rnd = state["round"]
        assert len(rnd["hand"]) == 14
        assert rnd["handCounts"][0] == 14
        assert "hands" not in rnd


def test_two_humans_share_a_room(client):
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
            assert [s["bot"] for s in started["seats"]] == [False, False, True, True]


def test_joining_unknown_room_reports_error(client):
    with client.websocket_connect("/apps/mahjong/ws") as ws:
        ws.send_json({"type": "join", "code": "NOPE", "name": "x"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "没有这个房间" in msg["text"]
