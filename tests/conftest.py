"""测试公共配置：用临时 SQLite 数据库，绝不连接 .env 里的真实数据库。"""
import os
import tempfile

# 必须在导入 app 之前设置，因为 app.settings 在导入时读取环境变量
_tmpdir = tempfile.mkdtemp(prefix="game-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ.pop("RENDER", None)
for _k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "APPLE_CLIENT_ID", "APPLE_TEAM_ID",
           "APPLE_KEY_ID", "APPLE_PRIVATE_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET", "SMTP_HOST"):
    os.environ[_k] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def _app_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_app_client):
    """每个测试开始时：退出登录、清空限流计数。"""
    _app_client.cookies.clear()
    for limiter in (auth.login_limiter, auth.register_limiter, auth.guest_limiter, auth.email_limiter):
        limiter.hits.clear()
    return _app_client


@pytest.fixture
def sent_emails(monkeypatch):
    """拦截发出的邮件，返回 [(收件人, 正文)]。"""
    sent = []
    monkeypatch.setattr(auth, "send_email", lambda to, subject, body: sent.append((to, body)))
    return sent
