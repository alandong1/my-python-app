"""平台的中英文切换：脚本能访问、首页有切换按钮、项目名有英文版。"""
import re
from pathlib import Path

from app.registry import Project

ROOT = Path(__file__).resolve().parent.parent


def dict_keys(path: Path):
    """读出 lang.js 里 i18n.add({...}) 的所有中文键。"""
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)*)":', path.read_text(encoding="utf-8"), re.M))


def test_i18n_scripts_served(client):
    for path in ("/static/i18n.js", "/static/lang.js"):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "window.i18n" in client.get("/static/i18n.js").text


def test_store_page_has_language_toggle(client):
    commit = client.get("/version").json()["commit"]
    html = client.get("/").text
    assert "data-lang-toggle" in html
    assert f'/static/i18n.js?v={commit}"' in html
    # 共用脚本必须在首页脚本之前加载
    assert html.index("/static/i18n.js") < html.index("/static/store.js")
    assert html.index("/static/lang.js") < html.index("/static/store.js")


def test_app_list_has_english_names(client):
    lordwar = next(a for a in client.get("/api/apps").json()["apps"] if a["slug"] == "lordwar")
    assert lordwar["nameEn"] == "Lord War"
    assert lordwar["descriptionEn"]


def test_english_name_is_optional():
    p = Project(slug="demo", name="演示", description="简介", icon="x", category="工具")
    assert p.card()["nameEn"] == "" and p.card()["descriptionEn"] == ""


def test_platform_translations_have_no_empty_values():
    text = (ROOT / "static" / "lang.js").read_text(encoding="utf-8")
    pairs = re.findall(r'^\s*"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)",', text, re.M)
    assert len(pairs) > 40
    assert all(en.strip() for _, en in pairs)
    # 键里不能有重复定义（同一个中文原文只能有一个译文）
    keys = [k for k, _ in pairs]
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]
