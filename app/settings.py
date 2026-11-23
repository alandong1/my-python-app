"""从环境变量读取配置。本地开发时会自动读取项目根目录的 .env 文件。

密钥类的东西（数据库地址、OAuth 密钥）只放在 .env 或 Render 的环境变量里，
绝对不要写进代码、也不要提交到 GitHub。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _normalize_db_url(url: str) -> str:
    """Neon 给的是 postgresql://...，SQLAlchemy 需要指明驱动 psycopg。"""
    if not url:
        return f"sqlite:///{ROOT / 'dev.db'}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalize_db_url(_env("DATABASE_URL"))

# Render 会自动设置这两个环境变量
IS_RENDER = _env("RENDER") == "true"
GIT_COMMIT = _env("RENDER_GIT_COMMIT")[:7] or "dev"

# 网站对外的地址，OAuth 回调地址由它拼出来。本地是 http://localhost:8000
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# 线上（https）必须为 1：登录 cookie 只通过加密连接发送
COOKIE_SECURE = _env("COOKIE_SECURE", "0") == "1"
SESSION_DAYS = int(_env("SESSION_DAYS", "30"))

# ---- OAuth：只有填了对应的变量，该登录方式才会启用 ----
GOOGLE_CLIENT_ID = _env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")

APPLE_CLIENT_ID = _env("APPLE_CLIENT_ID")        # Services ID，例如 com.example.game.web
APPLE_TEAM_ID = _env("APPLE_TEAM_ID")
APPLE_KEY_ID = _env("APPLE_KEY_ID")
# .p8 私钥内容。环境变量里换行可以写成 \n
APPLE_PRIVATE_KEY = _env("APPLE_PRIVATE_KEY").replace("\\n", "\n")

WECHAT_APP_ID = _env("WECHAT_APP_ID")
WECHAT_APP_SECRET = _env("WECHAT_APP_SECRET")

# ---- 邮件（用于验证邮箱）。不配置时，验证链接会打印在服务器日志里 ----
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM") or SMTP_USER
