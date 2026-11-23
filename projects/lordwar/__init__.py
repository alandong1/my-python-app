"""领主战争：Dev Lab 的第一个项目。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="lordwar",
    name="领主战争",
    description="多人实时策略：建立王国、一格一格拓展领土，在战争迷雾中征服野怪和其他领主。",
    icon="⚔️",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
    startup=server.startup,
    shutdown=server.shutdown,
    health=server.health,
)
