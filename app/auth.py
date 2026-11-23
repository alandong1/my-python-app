"""账户系统：游客登录、用户名密码注册/登录、绑定邮箱、第三方登录（OAuth）。

登录成功后，服务器在浏览器里设置一个 HttpOnly 的 cookie「session」。
- HttpOnly：网页里的 JavaScript 读不到它，就算页面被注入恶意脚本也偷不走
- 数据库只保存 token 的 SHA-256 哈希，数据库泄露也无法拿来登录
WebSocket 连接时浏览器会自动带上这个 cookie，服务器据此知道是谁。
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Deque, Dict, Optional
from urllib.parse import quote

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from . import settings
from .db import EmailVerification, LoginSession, OAuthAccount, User, get_db, utcnow
from .mailer import send_email
from .oauth import PROVIDERS, OAuthError, enabled_providers

log = logging.getLogger("auth")
router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "session"
STATE_COOKIE = "oauth_state"
USERNAME_RE = re.compile(r"\w{3,20}")          # 字母、数字、下划线、中文
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
GUEST_KEY_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")


# ------------------------------------------------------------------ 工具函数

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    return bcrypt.checkpw(pw.encode(), hashed.encode())


# 用户不存在时也做一次 bcrypt 比较，让「用户不存在」和「密码错误」耗时一样，
# 防止别人通过响应快慢判断某个用户名是否已注册
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def validate_password(pw: str):
    if len(pw) < 8:
        raise HTTPException(400, "密码至少 8 位")
    if len(pw.encode()) > 72:
        raise HTTPException(400, "密码太长（最多 72 字节）")


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "邮箱格式不正确")
    return email


class RateLimiter:
    """简单的内存限流：同一个 key 在 window 秒内最多 limit 次。"""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.hits: Dict[str, Deque[float]] = defaultdict(deque)

    def hit(self, key: str):
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "操作太频繁，请稍后再试")
        q.append(now)


login_limiter = RateLimiter(10, 600)       # 每个 IP / 每个用户名 10 分钟 10 次
register_limiter = RateLimiter(10, 3600)
guest_limiter = RateLimiter(30, 3600)
email_limiter = RateLimiter(5, 3600)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# ------------------------------------------------------------------ 会话

def _set_cookie(resp: Response, name: str, value: str, max_age: int, samesite: str = "lax",
                path: str = "/"):
    resp.set_cookie(name, value, max_age=max_age, httponly=True, secure=settings.COOKIE_SECURE,
                    samesite=samesite, path=path)


def start_session(db, user: User, resp: Response):
    token = secrets.token_urlsafe(32)
    now = utcnow()
    # 顺手清理这个用户已过期的会话
    for s in db.scalars(select(LoginSession).where(LoginSession.user_id == user.id,
                                                   LoginSession.expires_at < now)):
        db.delete(s)
    db.add(LoginSession(token_hash=sha256(token), user_id=user.id,
                        expires_at=now + timedelta(days=settings.SESSION_DAYS)))
    user.last_login_at = now
    _set_cookie(resp, SESSION_COOKIE, token, settings.SESSION_DAYS * 86400)


def user_from_token(db, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    s = db.scalar(select(LoginSession).where(LoginSession.token_hash == sha256(token)))
    if not s or s.expires_at < utcnow():
        return None
    return db.get(User, s.user_id)


def lookup_session_user(token: Optional[str]):
    """给 WebSocket 用：返回 (user_id, 显示名)，未登录返回 None。"""
    with get_db() as db:
        u = user_from_token(db, token)
        return (u.id, u.display_name) if u else None


def require_user(db, request: Request) -> User:
    u = user_from_token(db, request.cookies.get(SESSION_COOKIE))
    if not u:
        raise HTTPException(401, "请先登录")
    return u


def user_info(db, u: User) -> dict:
    linked = db.scalars(select(OAuthAccount.provider).where(OAuthAccount.user_id == u.id)).all()
    pending = db.scalar(select(EmailVerification.email).where(
        EmailVerification.user_id == u.id, EmailVerification.expires_at > utcnow()))
    return {
        "id": u.id, "displayName": u.display_name, "username": u.username,
        "email": u.email, "pendingEmail": pending, "isGuest": u.is_guest,
        "hasPassword": bool(u.password_hash), "linked": sorted(set(linked)),
    }


# ------------------------------------------------------------------ 邮箱验证

def start_email_verification(db, user: User, email: str):
    taken = db.scalar(select(User).where(User.email == email, User.id != user.id))
    if taken:
        raise HTTPException(400, "该邮箱已被其他账号绑定")
    for old in db.scalars(select(EmailVerification).where(EmailVerification.user_id == user.id)):
        db.delete(old)
    token = secrets.token_urlsafe(32)
    db.add(EmailVerification(user_id=user.id, email=email, token_hash=sha256(token),
                             expires_at=utcnow() + timedelta(hours=24)))
    link = f"{settings.PUBLIC_BASE_URL}/api/auth/verify-email?token={token}"
    send_email(email, "验证你的邮箱 · 领主战争",
               f"你好 {user.display_name}，\n\n点击下面的链接完成邮箱绑定（24 小时内有效）：\n{link}\n\n"
               "如果这不是你本人的操作，请忽略这封邮件。")


# ------------------------------------------------------------------ 接口：账号

class GuestIn(BaseModel):
    guest_key: str


class RegisterIn(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginIn(BaseModel):
    username: str   # 也可以填已验证的邮箱
    password: str


class EmailIn(BaseModel):
    email: str


@router.get("/providers")
def providers():
    return {"providers": enabled_providers()}


@router.get("/me")
def me(request: Request):
    with get_db() as db:
        return user_info(db, require_user(db, request))


@router.post("/guest")
def guest_login(body: GuestIn, request: Request, response: Response):
    """游客登录：浏览器 localStorage 里的随机字符串就是游客的身份凭证。"""
    if not GUEST_KEY_RE.fullmatch(body.guest_key):
        raise HTTPException(400, "无效的游客凭证")
    with get_db() as db:
        u = db.scalar(select(User).where(User.guest_key_hash == sha256(body.guest_key)))
        if not u:
            guest_limiter.hit(client_ip(request))
            u = User(display_name=f"游客{secrets.randbelow(9000) + 1000}", is_guest=True,
                     guest_key_hash=sha256(body.guest_key))
            db.add(u)
            db.flush()
        start_session(db, u, response)
        return user_info(db, u)


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response):
    register_limiter.hit(client_ip(request))
    username = body.username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(400, "用户名需 3–20 个字符，只能包含字母、数字、下划线或中文")
    validate_password(body.password)
    email = normalize_email(body.email) if body.email and body.email.strip() else None
    with get_db() as db:
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            raise HTTPException(400, "用户名已被占用")
        u = User(username=username, display_name=username,
                 password_hash=hash_password(body.password))
        db.add(u)
        db.flush()
        if email:
            start_email_verification(db, u, email)
        start_session(db, u, response)
        return user_info(db, u)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ident = body.username.strip()
    login_limiter.hit("ip:" + client_ip(request))
    login_limiter.hit("user:" + ident.lower())
    with get_db() as db:
        if "@" in ident:
            u = db.scalar(select(User).where(User.email == ident.lower()))
        else:
            u = db.scalar(select(User).where(func.lower(User.username) == ident.lower()))
        if not u or not u.password_hash:
            check_password(body.password, _DUMMY_HASH)
            raise HTTPException(401, "用户名或密码错误")
        if not check_password(body.password, u.password_hash):
            raise HTTPException(401, "用户名或密码错误")
        start_session(db, u, response)
        return user_info(db, u)


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with get_db() as db:
            s = db.scalar(select(LoginSession).where(LoginSession.token_hash == sha256(token)))
            if s:
                db.delete(s)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/email")
def bind_email(body: EmailIn, request: Request):
    """绑定或更换邮箱：先发验证邮件，点了链接才算绑定成功。"""
    email = normalize_email(body.email)
    with get_db() as db:
        u = require_user(db, request)
        if u.is_guest:
            raise HTTPException(400, "游客不能绑定邮箱，请先注册正式账号")
        email_limiter.hit(f"user:{u.id}")
        if u.email == email:
            raise HTTPException(400, "已经绑定了这个邮箱")
        start_email_verification(db, u, email)
        return user_info(db, u)


@router.get("/verify-email")
def verify_email(token: str = ""):
    with get_db() as db:
        v = db.scalar(select(EmailVerification).where(EmailVerification.token_hash == sha256(token)))
        if not v or v.expires_at < utcnow():
            return _redirect_msg(error="验证链接无效或已过期")
        if db.scalar(select(User).where(User.email == v.email, User.id != v.user_id)):
            db.delete(v)
            return _redirect_msg(error="该邮箱已被其他账号绑定")
        u = db.get(User, v.user_id)
        u.email = v.email
        db.delete(v)
    return _redirect_msg(info="邮箱验证成功")


def _redirect_msg(info: str = "", error: str = "") -> RedirectResponse:
    q = f"info={quote(info)}" if info else f"error={quote(error)}"
    return RedirectResponse(f"/?{q}", status_code=303)


# ------------------------------------------------------------------ 接口：第三方登录

# 进行中的 OAuth 请求：state -> 信息。存在服务器内存里（10 分钟过期），
# 浏览器 cookie 里只放 state 本身，用来确认回来的是同一个浏览器（防 CSRF）。
_pending: Dict[str, dict] = {}
OAUTH_STATE_TTL = 600


def _state_cookie_samesite() -> str:
    # Apple 是从 appleid.apple.com 跨站 POST 回来的，SameSite=Lax 的 cookie 不会被带上，
    # 所以线上（https）要用 None；本地 http 下浏览器不允许 None，只能用 Lax
    return "none" if settings.COOKIE_SECURE else "lax"


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str, request: Request, link: int = 0):
    p = PROVIDERS.get(provider)
    if not p or not p.enabled():
        raise HTTPException(404, "未启用该登录方式")
    now = time.time()
    for k in [k for k, v in _pending.items() if v["expires"] < now]:
        del _pending[k]
    link_user_id = None
    if link:
        with get_db() as db:
            link_user_id = require_user(db, request).id
    state = secrets.token_urlsafe(24)
    _pending[state] = {"provider": provider, "link_user_id": link_user_id,
                       "expires": now + OAUTH_STATE_TTL}
    resp = RedirectResponse(p.authorize_url(state), status_code=302)
    _set_cookie(resp, STATE_COOKIE, state, OAUTH_STATE_TTL,
                samesite=_state_cookie_samesite(), path="/api/auth/oauth")
    return resp


@router.api_route("/oauth/{provider}/callback", methods=["GET", "POST"])
async def oauth_callback(provider: str, request: Request):
    params = dict(request.query_params)
    if request.method == "POST":
        params.update({k: str(v) for k, v in (await request.form()).items()})
    return await run_in_threadpool(_finish_oauth, provider, params,
                                   request.cookies.get(STATE_COOKIE))


def _finish_oauth(provider: str, params: Dict[str, str], cookie_state: Optional[str]):
    p = PROVIDERS.get(provider)
    if not p or not p.enabled():
        return _redirect_msg(error="未启用该登录方式")
    state = params.get("state", "")
    pending = _pending.pop(state, None)
    if (not pending or pending["provider"] != provider or pending["expires"] < time.time()
            or not cookie_state or not secrets.compare_digest(cookie_state, state)):
        return _oauth_done(_redirect_msg(error="登录请求已过期，请重试"))
    if params.get("error") or not params.get("code"):
        return _oauth_done(_redirect_msg(error="已取消登录"))
    try:
        ident = p.fetch_identity(params["code"], params)
    except (OAuthError, KeyError, ValueError) as e:
        log.warning("OAuth %s 失败：%s", provider, e)
        return _oauth_done(_redirect_msg(error=f"{p.label} 登录失败，请重试"))
    except Exception:
        log.exception("OAuth %s 出错", provider)
        return _oauth_done(_redirect_msg(error=f"{p.label} 登录失败，请重试"))

    with get_db() as db:
        acct = db.scalar(select(OAuthAccount).where(OAuthAccount.provider == provider,
                                                   OAuthAccount.provider_user_id == ident.provider_user_id))
        # 绑定模式：给已登录的账号加一个第三方登录方式
        if pending["link_user_id"]:
            if acct and acct.user_id != pending["link_user_id"]:
                return _oauth_done(_redirect_msg(error=f"这个 {p.label} 账号已绑定了其他用户"))
            if not acct:
                db.add(OAuthAccount(user_id=pending["link_user_id"], provider=provider,
                                    provider_user_id=ident.provider_user_id, email=ident.email))
                # 游客绑定了第三方账号，就成为正式账号
                db.get(User, pending["link_user_id"]).is_guest = False
            return _oauth_done(_redirect_msg(info=f"已绑定 {p.label} 账号"))

        # 登录模式：已绑定过就登录那个账号，没有就新建一个
        if acct:
            u = db.get(User, acct.user_id)
        else:
            name = (ident.name or f"{p.label}用户").strip()[:20]
            u = User(display_name=name)
            # 第三方确认过的邮箱，且没被别人占用，就直接作为已验证邮箱
            if ident.email and ident.email_verified:
                email = ident.email.lower()
                if not db.scalar(select(User).where(User.email == email)):
                    u.email = email
            db.add(u)
            db.flush()
            db.add(OAuthAccount(user_id=u.id, provider=provider,
                                provider_user_id=ident.provider_user_id, email=ident.email))
        resp = RedirectResponse("/", status_code=303)
        start_session(db, u, resp)
        return _oauth_done(resp)


def _oauth_done(resp: Response) -> Response:
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/oauth")
    return resp
