"""突击行动：页面能打开、不需要登录、静态文件能访问、WebSocket 联机、中英文译文齐全。"""
import re
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from projects.strike import server

HERE = Path(__file__).resolve().parent


def lang_keys():
    text = (HERE / "static" / "lang.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)*)":', text, re.M))


def receive_until(ws, kind, limit=200):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("t") == kind:
            return msg
    raise AssertionError(f"没有收到 {kind} 消息")


@pytest.fixture(autouse=True)
def fresh_arena():
    server.arena.players.clear()
    server.arena.events.clear()
    yield
    server.arena.players.clear()
    server.arena.events.clear()


# ---------------------------------------------------------------- 页面和接口

def test_page_opens_without_login(client):
    r = client.get("/apps/strike/")
    assert r.status_code == 200
    assert 'id="view"' in r.text
    assert 'type="module" src="static/game.js' in r.text
    assert "static/vendor/three.module.min.js" in r.text
    assert "/static/i18n.js" in r.text
    assert "data-lang-toggle" in r.text


def test_static_files_are_served(client):
    for path in ("static/game.js", "static/style.css", "static/lang.js",
                 "static/vendor/three.module.min.js", "static/vendor/THREE-LICENSE.txt"):
        assert client.get(f"/apps/strike/{path}").status_code == 200, path


def test_store_lists_strike_without_login(client):
    data = client.get("/api/apps").json()
    card = next(a for a in data["apps"] if a["slug"] == "strike")
    assert card["url"] == "/apps/strike/"
    assert card["requiresLogin"] is False


def test_health_reports_players(client):
    assert client.get("/health").json()["projects"]["strike"] == {"players": 0, "max": 12}


def test_script_strings_are_translated():
    """game.js 里 tr("...") 的每个中文参数，都要在 lang.js 里有译文。"""
    game = (HERE / "static" / "game.js").read_text(encoding="utf-8")
    literals = set(re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', game))
    assert len(literals) >= 5, "没有找到足够的 tr(...) 调用，检查测试或代码"
    missing = sorted(literals - lang_keys())
    assert not missing, missing


def test_page_text_is_translated():
    """index.html 里 data-i18n 的文字也要有译文（属性类的 data-i18n-ph 等也一起检查）。"""
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    texts = set(re.findall(r"<[^>]*\sdata-i18n>([^<]+)<", html))
    texts |= set(re.findall(r'data-i18n-(?:ph|title|aria)="([^"]+)"', html))
    texts.add("突击行动 · Dev Lab")   # <title> 里的文字
    missing = sorted(t.strip() for t in texts if t.strip() and t.strip() not in lang_keys()
                     and t.strip() not in {"Dev Lab"})
    assert not missing, missing


# ---------------------------------------------------------------- WebSocket 联机

def test_join_gets_welcome_then_state(client):
    with client.websocket_connect("/apps/strike/ws") as ws:
        ws.send_json({"t": "join", "name": "甲"})
        welcome = ws.receive_json()
        assert welcome["t"] == "welcome"
        assert welcome["map"]["walls"] and welcome["map"]["spawns"]
        assert welcome["sim"]["speed"] > 0
        state = receive_until(ws, "state")
        assert state["you"]["alive"] is True
        assert any(p["id"] == welcome["id"] and p["name"] == "甲" for p in state["players"])


def test_two_players_see_each_other_and_shots_are_broadcast(client):
    with client.websocket_connect("/apps/strike/ws") as a, client.websocket_connect("/apps/strike/ws") as b:
        a.send_json({"t": "join", "name": "甲"})
        ida = a.receive_json()["id"]
        b.send_json({"t": "join", "name": "乙"})
        idb = b.receive_json()["id"]
        state = receive_until(b, "state")
        names = {p["id"]: p["name"] for p in state["players"]}
        assert names == {ida: "甲", idb: "乙"}

        # 甲开火：乙会收到这一发的子弹轨迹（对方没有挡住时也会显示）
        a.send_json({"t": "fire"})
        for _ in range(200):
            msg = b.receive_json()
            if msg.get("t") == "state" and any(e["e"] == "shot" and e["by"] == ida for e in msg["events"]):
                break
        else:
            raise AssertionError("乙没有收到甲的射击事件")


def test_leaving_removes_player(client):
    with client.websocket_connect("/apps/strike/ws") as a:
        a.send_json({"t": "join", "name": "甲"})
        a.receive_json()
    assert len(server.arena.players) == 0


def test_bad_first_message_is_rejected(client):
    with client.websocket_connect("/apps/strike/ws") as ws:
        ws.send_json({"t": "hi"})
        assert ws.receive_json()["t"] == "error"


def test_bad_input_values_are_rejected(client):
    with client.websocket_connect("/apps/strike/ws") as ws:
        ws.send_json({"t": "join", "name": "甲"})
        ws.receive_json()
        ws.send_json({"t": "in", "seq": "not-a-number", "fwd": 0, "side": 0, "yaw": 0, "pitch": 0, "dt": 0})
        assert receive_until(ws, "error")["t"] == "error"


def test_foreign_origin_is_refused(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/apps/strike/ws", headers={"origin": "https://evil.example"}):
            pass


def test_long_name_is_trimmed():
    assert len(server._clean_name("名" * 40)) == 12
    assert server._clean_name("   ") == "匿名玩家"
