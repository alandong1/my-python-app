"""荒岛求生：三维多人生存游戏。玩家随机落在岛上，砍树、采集、打猎、钓鱼，保持饱食、健康、精神。"""
from app.registry import Project

from . import server

PROJECT = Project(
    slug="island-survival",
    name="荒岛求生",
    description="三维多人生存：随机落在荒岛上，砍树、采集、打猎、钓鱼、生火做饭，选厨师、医生或牧师一起求生。",
    name_en="Island Survival",
    description_en="3D multiplayer survival: land on a random spot of a wild island, chop, forage, hunt, fish and cook. Pick a chef, doctor or priest and survive together.",
    icon="🏝️",
    category="游戏",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
    startup=server.startup,
    shutdown=server.shutdown,
    health=server.health,
)
