"""返回 HTML 页面的公共工具。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.responses import HTMLResponse

from . import settings

_ASSET = re.compile(r'((?:src|href)="[^"]+\.(?:js|css))"')


def html_page(path: Path) -> HTMLResponse:
    """读取 HTML 文件，给其中 js/css 的地址加上版本号。

    每次部署后版本号会变，浏览器就会加载新文件，而不是用缓存里的旧版本。
    """
    html = path.read_text(encoding="utf-8")
    html = _ASSET.sub(lambda m: f'{m.group(1)}?v={settings.GIT_COMMIT}"', html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
