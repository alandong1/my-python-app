"""大陆争霸的接口测试：登录、状态、下命令，以及页面能正常打开。"""
import secrets


def guest(client):
    r = client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    assert r.status_code == 200
    return r


def test_api_requires_login(client):
    assert client.get("/apps/continent/api/state").status_code == 401
    assert client.post("/apps/continent/api/command", json={"action": "move"}).status_code == 401


def test_page_uses_relative_static_paths(client):
    r = client.get("/apps/continent/")
    assert r.status_code == 200
    assert "static/game.js" in r.text and "static/style.css" in r.text
    assert "/static/" not in r.text


def test_catalog_is_public_data(client):
    r = client.get("/apps/continent/api/catalog")
    assert r.status_code == 200
    data = r.json()
    assert "tank" in data["units"] and "barracks" in data["buildings"]
    assert data["queueMax"] >= 1 and "infantry" in data["research"]


def test_state_joins_and_shows_own_base(client):
    guest(client)
    r = client.get("/apps/continent/api/state")
    assert r.status_code == 200
    d = r.json()
    assert d["me"]["gold"] > 0 and d["me"]["hq"] is not None
    assert len(d["terrain"]) == d["w"] * d["h"] and len(d["visible"]) == d["w"] * d["h"]
    assert any(u["mine"] for u in d["units"])
    assert any(p["id"] == d["me"]["id"] for p in d["players"])


def test_command_success_and_error(client):
    guest(client)
    d = client.get("/apps/continent/api/state").json()
    inf = next(u for u in d["units"] if u["mine"] and u["kind"] == "infantry")
    x, y = d["me"]["hq"]
    # 合法命令：返回操作之后的世界
    r = client.post("/apps/continent/api/command",
                    json={"action": "move", "units": [inf["id"]], "x": x, "y": y})
    assert r.status_code == 200 and r.json()["me"]["id"] == d["me"]["id"]
    # 不合法命令：400 + 中文错误信息
    r = client.post("/apps/continent/api/command", json={"action": "hack"})
    assert r.status_code == 400 and "未知" in r.json()["error"]
    r = client.post("/apps/continent/api/command",
                    json={"action": "train", "building": 999999, "kind": "tank"})
    assert r.status_code == 400
