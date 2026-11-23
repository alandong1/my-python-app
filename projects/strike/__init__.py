"""突击行动：CS 风格的第一人称 3D 多人射击游戏，电脑和手机网页都能玩。需要登录；注册用户可以建房，所有登录用户都能加入。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="strike",
    name="突击行动",
    description="CS 风格的第一人称多人射击：两队对战，电脑和手机都能玩。注册用户可以建房，房主能踢人、加电脑。",
    name_en="Strike Ops",
    description_en="CS-style first-person multiplayer shooter: two teams, desktop and mobile. Registered players can host rooms; hosts can kick players and add bots.",
    icon="🔫",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
    startup=server.startup,
    shutdown=server.shutdown,
    health=server.health,
)
