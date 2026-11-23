"""领主战争的中英文切换：页面有按钮和译文，脚本里用到的文字都有译文。"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def dict_keys():
    text = (HERE / "static" / "lang.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)*)":', text, re.M))


def test_page_has_language_toggle(client):
    r = client.get("/apps/lordwar/")
    assert r.status_code == 200
    assert "data-lang-toggle" in r.text
    assert "/static/i18n.js" in r.text


def test_script_strings_are_translated():
    """game.js 里 tr("...") 的每个中文参数，都要在 lang.js 里有译文。"""
    game = (HERE / "static" / "game.js").read_text(encoding="utf-8")
    literals = set(re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', game))
    missing = sorted(literals - dict_keys())
    assert not missing, missing


def test_static_text_is_translated():
    """index.html 里 data-i18n 标记的文字，都要有译文。"""
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    texts = re.findall(r'data-i18n(?:-ph|-title|-aria)?="([^"]+)"', html)
    texts += re.findall(r'data-i18n[^>]*>([^<\n]+)<', html)
    texts += re.findall(r'data-i18n-html>(.*?)</section>', html, re.S)
    # 只看含文字的部分（纯符号如 🏰、× 不需要翻译）
    words = {t.strip() for t in texts if re.search(r"[一-龥A-Za-z]", t)}
    missing = sorted(words - dict_keys())
    assert not missing, missing


def test_building_and_unit_names_are_translated():
    """config.py 里的名字和说明都要有译文（它们会显示在页面上）。"""
    from projects.lordwar import config as C

    names = [b["name"] for b in C.BUILDINGS.values()] + [b["desc"] for b in C.BUILDINGS.values()]
    names += [u["name"] for u in C.UNITS.values()] + list(C.TERRAIN_NAMES.values())
    names += [n["name"] for n in C.NPC_TYPES.values()] + [r["name"] for r in C.RESEARCH.values()]
    names += [r["desc"] for r in C.RESEARCH.values()]
    missing = sorted(set(names) - dict_keys())
    assert not missing, missing
