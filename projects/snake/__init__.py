"""贪吃蛇：一个纯前端的小游戏，电脑和手机都能玩。不需要登录，成绩只保存在本机。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="snake",
    name="贪吃蛇",
    description="经典贪吃蛇：方向键、WASD 或滑动屏幕控制，电脑和手机都能玩。",
    name_en="Snake",
    description_en="Classic snake: steer with arrow keys, WASD, or swipes. Plays on desktop and mobile.",
    icon="🐍",
    category="游戏",
    status="测试中",
    requires_login=False,
    router=server.router,
    static_dir=server.STATIC,
)
