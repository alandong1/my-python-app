"""世界存档：把游戏世界的快照写进数据库，启动时读回来。

序列化（Game.to_dict）必须在游戏主循环所在的线程里做，保证拿到的是同一时刻的完整状态；
写数据库比较慢，放到线程池里做，不阻塞游戏。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import delete, select

from .db import WorldSnapshot, get_db

log = logging.getLogger("persistence")
KEEP_SNAPSHOTS = 5


def dump_world(data: dict) -> str:
    """转成 JSON 字符串。必须在游戏线程里调用（见文件开头说明）。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def save_snapshot(app: str, version: int, tick: int, payload: str) -> int:
    """保存一份快照（可以在线程池里调用），返回字节数。会顺带删掉多余的旧快照。"""
    with get_db() as db:
        db.add(WorldSnapshot(app=app, version=version, tick=tick, data=payload))
        db.flush()
        keep = db.scalars(select(WorldSnapshot.id).where(WorldSnapshot.app == app)
                          .order_by(WorldSnapshot.id.desc()).limit(KEEP_SNAPSHOTS)).all()
        db.execute(delete(WorldSnapshot).where(WorldSnapshot.app == app,
                                               WorldSnapshot.id.not_in(keep)))
    return len(payload.encode())


def load_latest(app: str) -> Optional[dict]:
    with get_db() as db:
        row = db.scalar(select(WorldSnapshot).where(WorldSnapshot.app == app)
                        .order_by(WorldSnapshot.id.desc()).limit(1))
        if not row:
            return None
        return json.loads(row.data)
