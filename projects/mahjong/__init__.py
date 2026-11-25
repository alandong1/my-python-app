"""湖北卡五星麻将：可以和朋友联机，也可以和电脑玩。"""
from app.registry import Project

from . import models, server  # models：让 init_db() 能建出积分和道具的表

PROJECT = Project(
    slug="mahjong",
    name="麻将小游戏",
    description="多种麻将玩法：湖北卡五星（已开放），红中赖子杠、四川血战到底、血流成河、上海麻将（规则确认中）。可以联机，也可以和电脑玩。",
    name_en="Mahjong Games",
    description_en="Several mahjong variants. Hubei Ka Wu Xing is available now; others are being finalised. Play online with friends or against the computer.",
    icon="🀄",
    category="游戏",
    status="测试中",
    requires_login=True,   # 游客也算登录：同一个浏览器就是同一个账号
    router=server.router,
    startup=server.startup,
    static_dir=server.STATIC,
)
