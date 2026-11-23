"""第三方登录测试。不访问真实的 Google/Apple/微信，用 httpx.MockTransport 模拟它们的服务器。"""
import json
import re
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app import oauth, settings


def state_of(location: str) -> str:
    return re.search(r"state=([^&#]+)", location).group(1)


def start(client, provider, link=False):
    r = client.get(f"/api/auth/oauth/{provider}/start" + ("?link=1" if link else ""),
                    follow_redirects=False)
    return r


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(oauth, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "gsecret")

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=") for x in req.content.decode().split("&"))
            assert form["code"] == "goodcode" and form["client_secret"] == "gsecret"
            return httpx.Response(200, json={"access_token": "AT"})
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json={"sub": "g-123", "email": "Gina@gmail.com",
                                         "email_verified": True, "name": "Gina"})
    mock_http(monkeypatch, handler)


@pytest.fixture
def wechat(monkeypatch):
    monkeypatch.setattr(settings, "WECHAT_APP_ID", "wxid")
    monkeypatch.setattr(settings, "WECHAT_APP_SECRET", "wxsecret")

    def handler(req):
        if req.url.path.endswith("access_token"):
            return httpx.Response(200, text=json.dumps(
                {"access_token": "WXAT", "openid": "o1", "unionid": "u-wx-1"}))
        return httpx.Response(200, text=json.dumps({"nickname": "微信玩家", "unionid": "u-wx-1"}))
    mock_http(monkeypatch, handler)


def test_google_login(client, google):
    assert [p["id"] for p in client.get("/api/auth/providers").json()["providers"]] == ["google"]
    r = start(client, "google")
    assert r.headers["location"].startswith("https://accounts.google.com/")
    state = state_of(r.headers["location"])
    r = client.get(f"/api/auth/oauth/google/callback?code=goodcode&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["displayName"] == "Gina" and me["email"] == "gina@gmail.com" and me["linked"] == ["google"]

    # state 不能重复使用
    r = client.get(f"/api/auth/oauth/google/callback?code=goodcode&state={state}", follow_redirects=False)
    assert "error=" in r.headers["location"]

    # 再次登录还是同一个用户
    client.post("/api/auth/logout")
    state = state_of(start(client, "google").headers["location"])
    client.get(f"/api/auth/oauth/google/callback?code=goodcode&state={state}", follow_redirects=False)
    assert client.get("/api/auth/me").json()["id"] == me["id"]


def test_oauth_rejects_other_browser_and_cancel(client, google):
    state = state_of(start(client, "google").headers["location"])
    client.cookies.clear()  # 模拟另一个浏览器（没有 state cookie）
    r = client.get(f"/api/auth/oauth/google/callback?code=goodcode&state={state}", follow_redirects=False)
    assert "error=" in r.headers["location"]

    state = state_of(start(client, "google").headers["location"])
    r = client.get(f"/api/auth/oauth/google/callback?error=access_denied&state={state}",
                   follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_wechat_link_upgrades_guest(client, wechat):
    guest = client.post("/api/auth/guest", json={"guest_key": "k" * 40}).json()
    r = start(client, "wechat", link=True)
    assert "#wechat_redirect" in r.headers["location"]
    state = state_of(r.headers["location"])
    r = client.get(f"/api/auth/oauth/wechat/callback?code=c&state={state}", follow_redirects=False)
    assert "info=" in r.headers["location"]
    me = client.get("/api/auth/me").json()
    assert me["id"] == guest["id"] and me["linked"] == ["wechat"] and not me["isGuest"]

    # 同一个微信不能再绑定到别的账号
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "wx_other", "password": "secret123"})
    state = state_of(start(client, "wechat", link=True).headers["location"])
    r = client.get(f"/api/auth/oauth/wechat/callback?code=c&state={state}", follow_redirects=False)
    assert "error=" in r.headers["location"]

    client.post("/api/auth/logout")
    assert start(client, "wechat", link=True).status_code == 401  # 绑定需要先登录


def test_apple_login_verifies_tokens(client, monkeypatch):
    ec_key = ec.generate_private_key(ec.SECP256R1())
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, "APPLE_CLIENT_ID", "com.test.web")
    monkeypatch.setattr(settings, "APPLE_TEAM_ID", "TEAM123")
    monkeypatch.setattr(settings, "APPLE_KEY_ID", "KEY123")
    monkeypatch.setattr(settings, "APPLE_PRIVATE_KEY", ec_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())

    def id_token(aud="com.test.web"):
        now = int(time.time())
        return jwt.encode({"iss": "https://appleid.apple.com", "aud": aud, "sub": "apple-001",
                           "email": "x@privaterelay.appleid.com", "email_verified": "true",
                           "exp": now + 600, "iat": now}, rsa_key, algorithm="RS256")

    current = {"token": id_token()}

    def handler(req):
        form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
        secret = jwt.decode(form["client_secret"], ec_key.public_key(), algorithms=["ES256"],
                            audience="https://appleid.apple.com")
        assert secret["iss"] == "TEAM123" and secret["sub"] == "com.test.web"
        assert jwt.get_unverified_header(form["client_secret"])["kid"] == "KEY123"
        return httpx.Response(200, json={"id_token": current["token"]})
    mock_http(monkeypatch, handler)

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _):
            return type("Key", (), {"key": rsa_key.public_key()})()
    monkeypatch.setattr(oauth.PROVIDERS["apple"], "_jwks", FakeJWKS())

    r = start(client, "apple")
    assert "response_mode=form_post" in r.headers["location"]
    r = client.post("/api/auth/oauth/apple/callback", follow_redirects=False, data={
        "code": "ac", "state": state_of(r.headers["location"]),
        "user": json.dumps({"name": {"firstName": "Tim", "lastName": "C"}})})
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["displayName"] == "Tim C" and me["linked"] == ["apple"]

    # 令牌的接收方不对，必须拒绝
    current["token"] = id_token(aud="someone.else")
    client.post("/api/auth/logout")
    state = state_of(start(client, "apple").headers["location"])
    r = client.post("/api/auth/oauth/apple/callback", data={"code": "ac", "state": state},
                    follow_redirects=False)
    assert "error=" in r.headers["location"]
