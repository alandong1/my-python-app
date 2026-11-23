"""卡坦岛：多人联机的资源经营桌游（规则同卡坦岛基础版，3–4 人）。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="catan",
    name="卡坦岛",
    description="经典资源经营桌游：抢占土地、交易资源、修路建城，先拿到 10 分者获胜。3–4 人联机。",
    name_en="Catan-style Board Game",
    description_en="Classic resource-trading board game: settle, trade and build roads and cities. First to 10 points wins. 3–4 players online.",
    icon="🏝️",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
    health=server.health,
)
