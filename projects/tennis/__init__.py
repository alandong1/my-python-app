"""网球：第一人称三维网球，多人联机（单打 / 双打）。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="tennis",
    name="网球",
    description="第一人称三维网球联机：摇杆跑位，右边选球种击球，有平击、上旋、下旋、侧旋，自动计分。注册用户可以建房，所有人都能加入。",
    name_en="Tennis",
    description_en="First-person 3D tennis, multiplayer singles or doubles. Use the joystick to move and pick your shot. Registered players can host rooms; everyone can join.",
    icon="🎾",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
    startup=server.startup,
    shutdown=server.shutdown,
    health=server.health,
)
