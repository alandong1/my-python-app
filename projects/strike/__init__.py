"""突击行动：CS 风格的第一人称 3D 多人射击游戏，电脑和手机网页都能玩。不需要登录，输入昵称即可进入。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="strike",
    name="突击行动",
    description="CS 风格的第一人称多人射击：电脑用鼠标和键盘，手机用触屏，同一个竞技场里互相对战。",
    name_en="Strike Ops",
    description_en="CS-style first-person multiplayer shooter. Mouse and keyboard on desktop, touch on mobile, all in one arena.",
    icon="🔫",
    category="游戏",
    status="测试中",
    requires_login=False,
    router=server.router,
    static_dir=server.STATIC,
    startup=server.startup,
    shutdown=server.shutdown,
    health=server.health,
)
