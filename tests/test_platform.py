"""Dev Lab 平台测试：首页商店、项目挂载、版本号、登录后跳转。"""
import re

from app.auth import safe_next
from app.registry import Project


def test_store_page_and_app_list(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    commit = client.get("/version").json()["commit"]
    assert f'/static/store.js?v={commit}"' in r.text and f'/static/store.css?v={commit}"' in r.text
    data = client.get("/api/apps").json()
    assert data["platform"] == "Dev Lab"
    lordwar = next(a for a in data["apps"] if a["slug"] == "lordwar")
    assert lordwar["url"] == "/apps/lordwar/" and lordwar["requiresLogin"] is True


def test_project_mounted(client):
    r = client.get("/apps/lordwar", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/apps/lordwar/"
    r = client.get("/apps/lordwar/")
    commit = client.get("/version").json()["commit"]
    assert r.status_code == 200 and f'static/game.js?v={commit}"' in r.text
    # 页面引用的每个静态文件都能访问到
    for path in re.findall(r'(?:src|href)="(static/[^"?]+)', r.text):
        assert client.get(f"/apps/lordwar/{path}").status_code == 200, path
    assert client.get("/apps/nope/").status_code == 404


def test_health_reports_projects(client):
    h = client.get("/health").json()
    assert h["ok"] and "lordwar" in h["projects"] and "players" in h["projects"]["lordwar"]


def test_safe_next_blocks_other_sites():
    assert safe_next("/apps/lordwar/") == "/apps/lordwar/"
    for bad in ("https://evil.com", "//evil.com", "/\\\\evil.com", None, "", "javascript:alert(1)"):
        assert safe_next(bad) == "/"


def test_invalid_project_slug_rejected():
    import pytest
    for bad in ("Lordwar", "a", "has space", "../x", "1abc"):
        with pytest.raises(ValueError):
            Project(slug=bad, name="x", description="x", icon="x", category="x")
