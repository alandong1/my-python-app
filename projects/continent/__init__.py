"""大陆争霸：所有人在同一张大地图上，从步兵一路造到航母，靠侦察机探视野，还能搬迁基地。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="continent",
    name="大陆争霸",
    description="二战背景的多人大地图：造兵、升级、侦察、抢矿，还能搬迁基地（《疯狂大陆》式玩法，试做版）。",
    name_en="Continent War",
    description_en="A WWII-style multiplayer map game: build units from infantry to carriers, scout the fog, upgrade, and relocate your base. Prototype.",
    icon="🌍",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
)
