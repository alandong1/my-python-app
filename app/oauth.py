"""第三方登录（OAuth 2.0 授权码流程）：Google、Apple、微信。

流程（三家都一样）：
1. 浏览器访问 /api/auth/oauth/{provider}/start，我们跳转到第三方的授权页面
2. 用户在第三方同意授权后，第三方把浏览器带回 /api/auth/oauth/{provider}/callback，附带一个一次性的 code
3. 我们的服务器拿 code + 密钥，直接向第三方换取用户身份（这一步浏览器看不到，密钥不会泄露）

每家只有在环境变量里配置了密钥才会启用。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx
import jwt

from . import settings


class OAuthError(Exception):
    pass


@dataclass
class Identity:
    provider_user_id: str
    email: Optional[str] = None
    email_verified: bool = False
    name: Optional[str] = None


def _http() -> httpx.Client:
    return httpx.Client(timeout=15)


class Provider:
    id = ""
    label = ""
    # Apple 用 POST 表单回调，其他用 GET
    callback_method = "GET"

    def enabled(self) -> bool:
        raise NotImplementedError

    def redirect_uri(self) -> str:
        return f"{settings.PUBLIC_BASE_URL}/api/auth/oauth/{self.id}/callback"

    def authorize_url(self, state: str) -> str:
        raise NotImplementedError

    def fetch_identity(self, code: str, form: Dict[str, str]) -> Identity:
        raise NotImplementedError


# ------------------------------------------------------------------ Google

class Google(Provider):
    id, label = "google", "Google"

    def enabled(self):
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

    def authorize_url(self, state):
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        })

    def fetch_identity(self, code, form):
        with _http() as c:
            r = c.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": self.redirect_uri(),
                "grant_type": "authorization_code",
            })
            if r.status_code != 200:
                raise OAuthError(f"Google 换取 token 失败：{r.text[:200]}")
            access_token = r.json()["access_token"]
            r = c.get("https://openidconnect.googleapis.com/v1/userinfo",
                      headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code != 200:
                raise OAuthError("获取 Google 用户信息失败")
            info = r.json()
        return Identity(
            provider_user_id=str(info["sub"]),
            email=info.get("email"),
            email_verified=bool(info.get("email_verified")),
            name=info.get("name"),
        )


# ------------------------------------------------------------------ Apple

class Apple(Provider):
    id, label = "apple", "Apple"
    callback_method = "POST"
    ISSUER = "https://appleid.apple.com"

    def __init__(self):
        self._jwks: Optional[jwt.PyJWKClient] = None

    def enabled(self):
        return all([settings.APPLE_CLIENT_ID, settings.APPLE_TEAM_ID,
                    settings.APPLE_KEY_ID, settings.APPLE_PRIVATE_KEY])

    def authorize_url(self, state):
        return f"{self.ISSUER}/auth/authorize?" + urlencode({
            "client_id": settings.APPLE_CLIENT_ID,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "response_mode": "form_post",   # 请求邮箱/姓名时 Apple 要求用 POST 回调
            "scope": "name email",
            "state": state,
        })

    def _client_secret(self) -> str:
        """Apple 的 client_secret 不是固定字符串，而是用私钥签名的短期 JWT。"""
        now = int(time.time())
        return jwt.encode(
            {"iss": settings.APPLE_TEAM_ID, "iat": now, "exp": now + 300,
             "aud": self.ISSUER, "sub": settings.APPLE_CLIENT_ID},
            settings.APPLE_PRIVATE_KEY, algorithm="ES256",
            headers={"kid": settings.APPLE_KEY_ID},
        )

    def _verify_id_token(self, id_token: str) -> dict:
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(f"{self.ISSUER}/auth/keys")
        key = self._jwks.get_signing_key_from_jwt(id_token)
        return jwt.decode(id_token, key.key, algorithms=["RS256"],
                          audience=settings.APPLE_CLIENT_ID, issuer=self.ISSUER)

    def fetch_identity(self, code, form):
        with _http() as c:
            r = c.post(f"{self.ISSUER}/auth/token", data={
                "code": code,
                "client_id": settings.APPLE_CLIENT_ID,
                "client_secret": self._client_secret(),
                "redirect_uri": self.redirect_uri(),
                "grant_type": "authorization_code",
            })
        if r.status_code != 200:
            raise OAuthError(f"Apple 换取 token 失败：{r.text[:200]}")
        try:
            claims = self._verify_id_token(r.json()["id_token"])
        except jwt.PyJWTError as e:
            raise OAuthError(f"Apple 身份令牌校验失败：{e}")
        # 姓名只在用户第一次授权时，随回调表单的 user 字段发来一次
        name = None
        try:
            u = json.loads(form.get("user") or "{}").get("name") or {}
            name = " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or None
        except (ValueError, AttributeError):
            pass
        verified = claims.get("email_verified") in (True, "true")
        return Identity(provider_user_id=str(claims["sub"]), email=claims.get("email"),
                        email_verified=verified, name=name)


# ------------------------------------------------------------------ 微信

class WeChat(Provider):
    """微信开放平台「网站应用」扫码登录。需要企业认证的开放平台账号。"""
    id, label = "wechat", "微信"

    def enabled(self):
        return bool(settings.WECHAT_APP_ID and settings.WECHAT_APP_SECRET)

    def authorize_url(self, state):
        return "https://open.weixin.qq.com/connect/qrconnect?" + urlencode({
            "appid": settings.WECHAT_APP_ID,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }) + "#wechat_redirect"

    def fetch_identity(self, code, form):
        with _http() as c:
            r = c.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={
                "appid": settings.WECHAT_APP_ID,
                "secret": settings.WECHAT_APP_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            })
            tok = json.loads(r.text)  # 微信返回的 Content-Type 不一定是 JSON
            if "errcode" in tok:
                raise OAuthError(f"微信换取 token 失败：{tok.get('errmsg')}")
            r = c.get("https://api.weixin.qq.com/sns/userinfo", params={
                "access_token": tok["access_token"], "openid": tok["openid"]})
            info = json.loads(r.text)
        if "errcode" in info:
            info = {}
        # unionid 在同一开放平台下的所有应用里都相同，优先用它
        uid = tok.get("unionid") or info.get("unionid") or tok["openid"]
        return Identity(provider_user_id=str(uid), name=info.get("nickname"))


PROVIDERS: Dict[str, Provider] = {p.id: p for p in (Google(), Apple(), WeChat())}


def enabled_providers():
    return [{"id": p.id, "label": p.label} for p in PROVIDERS.values() if p.enabled()]
