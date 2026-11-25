"""积分、道具商城和排行榜的数据库操作。所有函数都是同步的，服务器里用 run_in_threadpool 调用。"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy import select

from app.db import User, get_db

from .models import MahjongItemStock, MahjongMeta, MahjongWallet

START_POINTS = 10000      # 每个玩家的起始积分（新玩家第一次进来就有）

# 技能：名字和价格（积分）。所有技能都是摸完牌之后使用，每局每个只能用一次。
ITEMS: Dict[str, dict] = {
    "swap": {"name": "偷天换日", "price": 20},
    "lucky_pong": {"name": "锦上添花", "price": 20},
    "miracle_hu": {"name": "妙手回春", "price": 50},
    "steal": {"name": "釜底抽薪", "price": 30},
}


def _wallet(db, uid: int) -> MahjongWallet:
    """拿到这个账号的钱包；没有就新建，给起始积分。"""
    w = db.get(MahjongWallet, uid)
    if w is None:
        w = MahjongWallet(user_id=uid, points=START_POINTS)
        db.add(w)
        db.flush()
    return w


def grant_once() -> None:
    """给所有已经存在的账号发一次起始积分（只发一次）。"""
    with get_db() as db:
        if db.get(MahjongMeta, "grant_start_points_v1"):
            return
        for uid in db.scalars(select(User.id)):
            w = db.get(MahjongWallet, uid)
            if w is None:
                db.add(MahjongWallet(user_id=uid, points=START_POINTS))
            else:
                w.points += START_POINTS
        db.add(MahjongMeta(key="grant_start_points_v1", value="1"))


def wallet(uid: int) -> dict:
    with get_db() as db:
        w = _wallet(db, uid)
        stock = {k: 0 for k in ITEMS}
        for row in db.scalars(select(MahjongItemStock).where(MahjongItemStock.user_id == uid)):
            if row.item in stock:
                stock[row.item] = row.count
        return {"points": w.points, "items": stock}


def add_points(uid: int, delta: int) -> None:
    with get_db() as db:
        w = _wallet(db, uid)
        w.points += delta
        db.commit()


def buy(uid: int, item: str) -> bool:
    """花积分买一个道具。积分不够返回 False。"""
    if item not in ITEMS:
        raise ValueError(item)
    price = ITEMS[item]["price"]
    with get_db() as db:
        w = _wallet(db, uid)
        if w.points < price:
            return False
        w.points -= price
        row = db.get(MahjongItemStock, (uid, item))
        if row is None:
            row = MahjongItemStock(user_id=uid, item=item, count=0)
            db.add(row)
        row.count += 1
        db.commit()
        return True


def consume(uid: int, item: str) -> bool:
    """用掉一个道具。没有库存返回 False。"""
    with get_db() as db:
        row = db.get(MahjongItemStock, (uid, item))
        if row is None or row.count <= 0:
            return False
        row.count -= 1
        db.commit()
        return True


def refund(uid: int, item: str) -> None:
    """操作不合规则时把道具退回去。"""
    with get_db() as db:
        row = db.get(MahjongItemStock, (uid, item))
        if row is None:
            row = MahjongItemStock(user_id=uid, item=item, count=0)
            db.add(row)
        row.count += 1
        db.commit()


def leaderboard(limit: int = 20) -> List[dict]:
    with get_db() as db:
        rows = db.execute(
            select(User.display_name, MahjongWallet.points)
            .join(MahjongWallet, MahjongWallet.user_id == User.id)
            .order_by(MahjongWallet.points.desc(), User.id)
            .limit(limit)
        ).all()
        return [{"name": name, "points": pts} for name, pts in rows]
