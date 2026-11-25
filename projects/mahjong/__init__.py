"""湖北卡五星麻将：可以和朋友联机，也可以和电脑玩。"""
from app.registry import Project

from . import models, server  # models：让 init_db() 能建出积分和道具的表

PROJECT = Project(
    slug="mahjong",
    name="湖北卡五星",
    description="湖北卡五星麻将：建房间邀请好友联机，不够人就由电脑补位，也可以直接和电脑玩。",
    name_en="Hubei Ka Wu Xing Mahjong",
    description_en="Hubei Ka Wu Xing mahjong: create a room and play with friends online, with computer players filling empty seats, or play against the computer alone.",
    icon="🀄",
    category="游戏",
    status="测试中",
    requires_login=True,   # 游客也算登录：同一个浏览器就是同一个账号
    router=server.router,
    static_dir=server.STATIC,
)
