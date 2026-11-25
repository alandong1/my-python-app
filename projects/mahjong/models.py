"""麻将的数据库表：积分和道具库存。表名以 mahjong_ 开头（见 AGENTS.md「项目之间的边界」）。

在 __init__.py 里 import 本模块，保证 init_db() 建表时能看到这些表。
"""
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MahjongWallet(Base):
    """每个账号的积分余额（排行榜和商城都用它）。"""

    __tablename__ = "mahjong_wallets"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=0)


class MahjongItemStock(Base):
    """每个账号拥有的道具数量。"""

    __tablename__ = "mahjong_item_stock"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class MahjongMeta(Base):
    """一次性的记录（比如「给所有玩家发过一万积分」已经做过了）。"""

    __tablename__ = "mahjong_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64), default="")
