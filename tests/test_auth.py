"""账户系统测试：游客、注册登录、邮箱验证、WebSocket 鉴权、限流。"""
import re
import secrets


def register(client, username, password="secret123", email=None):
    return client.post("/api/auth/register",
                       json={"username": username, "password": password, "email": email})


def login(client, username, password="secret123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/providers").json() == {"providers": []}


def test_guest_same_key_same_user(client):
    key = secrets.token_urlsafe(32)
    r = client.post("/api/auth/guest", json={"guest_key": key})
    first = r.json()
    assert r.status_code == 200 and first["isGuest"] and first["displayName"].startswith("游客")
    assert "httponly" in r.headers["set-cookie"].lower()
    client.cookies.clear()
    assert client.post("/api/auth/guest", json={"guest_key": key}).json()["id"] == first["id"]
    assert client.post("/api/auth/guest", json={"guest_key": "short"}).status_code == 400


def test_guest_cannot_bind_email(client):
    client.post("/api/auth/guest", json={"guest_key": secrets.token_urlsafe(32)})
    assert client.post("/api/auth/email", json={"email": "a@b.co"}).status_code == 400


def test_register_validation(client):
    assert register(client, "ab").status_code == 400                       # 用户名太短
    assert register(client, "valid_name", password="123").status_code == 400  # 密码太短
    assert register(client, "Dup_User").status_code == 200
    client.cookies.clear()
    assert register(client, "dup_user").status_code == 400                 # 大小写不敏感重复


def test_register_login_logout(client):
    u = register(client, "领主小明").json()
    assert u["username"] == "领主小明" and not u["isGuest"]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, "领主小明", "wrongpass").status_code == 401
    assert login(client, "nobody_here", "wrongpass").status_code == 401
    r = login(client, "领主小明")
    assert r.status_code == 200 and r.json()["id"] == u["id"]


def test_email_verification_flow(client, sent_emails):
    u = register(client, "mail_user", email="Mail@Example.com").json()
    assert u["pendingEmail"] == "mail@example.com" and u["email"] is None
    to, body = sent_emails[-1]
    token = re.search(r"token=(\S+)", body).group(1)
    assert to == "mail@example.com"

    r = client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
    assert r.status_code == 303 and "info=" in r.headers["location"]
    assert client.get("/api/auth/me").json()["email"] == "mail@example.com"
    # 链接只能用一次
    r = client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
    assert r.headers["location"].startswith("/?error")
    # 可以用邮箱登录
    client.post("/api/auth/logout")
    assert login(client, "MAIL@example.com").json()["id"] == u["id"]
    # 别人不能绑定同一个邮箱
    client.post("/api/auth/logout")
    register(client, "other_user")
    assert client.post("/api/auth/email", json={"email": "mail@example.com"}).status_code == 400
    assert client.post("/api/auth/email", json={"email": "not-an-email"}).status_code == 400


def test_websocket_requires_login_and_keeps_kingdom(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "auth"
    register(client, "ws_user")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "join"})
        first = ws.receive_json()
        assert first["type"] == "welcome" and first["name"] == "ws_user"
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "join"})
        assert ws.receive_json()["id"] == first["id"]


def test_websocket_rejects_other_sites(client):
    register(client, "origin_user")
    accepted = False
    try:
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.send_json({"type": "join"})
            accepted = ws.receive_json().get("type") == "welcome"
    except Exception:
        pass  # 连接被服务器拒绝，符合预期
    assert not accepted, "跨站 WebSocket 连接应被拒绝"
    # 同站连接正常
    with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"type": "join"})
        assert ws.receive_json()["type"] == "welcome"


def test_login_rate_limit(client):
    codes = [login(client, "spam_target", "xxxxxxxx").status_code for _ in range(12)]
    assert 429 in codes


def test_version_and_index(client):
    v = client.get("/version").json()
    assert v["db"] == "sqlite" and v["commit"]
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache"
    assert f"/static/game.js?v={v['commit']}" in r.text
