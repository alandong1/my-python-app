"""项目登记：Dev Lab 平台上的每个项目都用一个 Project 描述自己。

平台根据这些信息：在首页「应用商店」显示卡片、把项目的路由挂到 /apps/<slug>/、
启动和关闭服务器时调用项目的 startup / shutdown。
新项目怎么接入，见 AGENTS.md 的「新建项目」。项目由 projects/__init__.py 自动发现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter

SLUG_RE = re.compile(r"[a-z][a-z0-9-]{1,30}")


@dataclass
class Project:
    slug: str                    # 网址里的名字：/apps/<slug>/；也是存档、数据表前缀的名字
    name: str                    # 商店里显示的名字
    description: str             # 一两句话介绍
    icon: str                    # 一个 emoji
    category: str                # 游戏 / 工具 / AI 等
    status: str = "测试中"        # 开发中 / 测试中 / 已上线
    name_en: str = ""            # 英文名（切换到英文时显示；留空则显示中文名）
    description_en: str = ""     # 英文简介（同上）
    requires_login: bool = True  # 进入项目是否需要登录（平台账号，含游客）
    router: Optional[APIRouter] = None
    static_dir: Optional[Path] = None             # 挂到 /apps/<slug>/static/
    startup: Optional[Callable[[], Awaitable[None]]] = None
    shutdown: Optional[Callable[[], Awaitable[None]]] = None
    health: Optional[Callable[[], dict]] = None   # 给 /health 汇总用
    external_url: Optional[str] = None            # 单独部署的项目：卡片直接跳到这个网址
    order: int = 100                              # 商店里的排序：小的在前，相同按 slug

    def __post_init__(self):
        if not SLUG_RE.fullmatch(self.slug):
            raise ValueError(f"项目 slug 不合法：{self.slug!r}（小写字母开头，只能有小写字母、数字、连字符）")

    @property
    def url(self) -> str:
        return self.external_url or f"/apps/{self.slug}/"

    def card(self) -> dict:
        return {"slug": self.slug, "name": self.name, "description": self.description,
                "nameEn": self.name_en, "descriptionEn": self.description_en,
                "icon": self.icon, "category": self.category, "status": self.status,
                "requiresLogin": self.requires_login, "url": self.url}
