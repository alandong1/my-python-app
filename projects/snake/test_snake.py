"""贪吃蛇：页面能打开、不需要登录、静态文件能访问、中英文译文齐全。"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def dict_keys():
    text = (HERE / "static" / "lang.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)*)":', text, re.M))


def test_page_opens_without_login(client):
    r = client.get("/apps/snake/")
    assert r.status_code == 200
    assert 'id="board"' in r.text
    assert "data-lang-toggle" in r.text
    assert "/static/i18n.js" in r.text
    assert "static/game.js" in r.text


def test_static_files_are_served(client):
    for path in ("static/game.js", "static/style.css", "static/lang.js"):
        assert client.get(f"/apps/snake/{path}").status_code == 200, path


def test_store_lists_snake_without_login(client):
    data = client.get("/api/apps").json()
    snake = next(a for a in data["apps"] if a["slug"] == "snake")
    assert snake["url"] == "/apps/snake/"
    assert snake["requiresLogin"] is False


def test_script_strings_are_translated():
    """game.js 里 tr("...") 的每个中文参数，都要在 lang.js 里有译文。"""
    game = (HERE / "static" / "game.js").read_text(encoding="utf-8")
    literals = set(re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', game))
    assert literals, "没有找到 tr(...) 调用，检查测试或代码"
    missing = sorted(literals - dict_keys())
    assert not missing, missing


def test_static_text_is_translated():
    """index.html 里 data-i18n* 标记的文字，都要有译文。"""
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    texts = re.findall(r'data-i18n(?:-title|-aria)?="([^"]+)"', html)
    texts += re.findall(r'data-i18n(?:-html)?>([^<]+)<', html)
    texts += re.findall(r'<title data-i18n>([^<]+)<', html)
    missing = sorted({t.strip() for t in texts} - dict_keys())
    assert not missing, missing
