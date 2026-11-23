"""世界存档测试：存档→读档结果一致；模拟服务器重启后王国还在。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from projects.lordwar import server
from projects.lordwar.game import Game, GameError
from app.persistence import KEEP_SNAPSHOTS, dump_world, load_latest, save_snapshot


def played_game() -> Game:
    """造一个有建筑、部队、训练队列、探索记录的世界。"""
    g = Game(7)
    a = g.join(101, "甲")
    g.join(102, "乙")
    a.res = {"gold": 5000.0, "wood": 5000.0}
    for c in list(a.tiles):
        for n in g.neighbors4(*c):
            try:
                g.expand(a, *n)
            except GameError:
                pass
    plains = [c for c in a.tiles if g.tile(*c).terrain == "plains" and not g.tile(*c).building]
    if plains:
        g.build(a, *plains[0], "barracks")
        g.train(a, "infantry", 10)
    for _ in range(30):
        g.tick()
    g.view_for(a)  # 计算视野，填充探索过的区域
    army = next(x for x in g.armies.values() if x.owner == a.id)
    target = next(c for c in a.explored if g.tile(*c).terrain not in ("water", "mountain")
                  and c != (army.x, army.y))
    g.move(a, army.id, *target)
    g.tick()
    g.view_for(a)
    return g


def roundtrip(g: Game) -> Game:
    return Game.from_dict(json.loads(dump_world(g.to_dict())))


def test_save_load_is_identical():
    g = played_game()
    g2 = roundtrip(g)
    assert g2.to_dict() == json.loads(dump_world(g.to_dict()))
    a1 = next(iter(g.players.values()))
    a2 = g2.players[a1.id]
    assert a2.tiles == a1.tiles and a2.explored == a1.explored and a2.hq == a1.hq
    assert g2.by_account == g.by_account
    assert {k: v.path for k, v in g2.armies.items()} == {k: v.path for k, v in g.armies.items()}


def test_loaded_world_keeps_running():
    g = roundtrip(played_game())
    p = next(iter(g.players.values()))
    gold = p.res["gold"]
    for _ in range(50):
        g.tick()
    assert p.res["gold"] > gold
    assert g.join(p.account_id, p.name) is p           # 同一账户回到同一个王国
    new = g.join(999, "新玩家")                          # 读档后新玩家照常加入
    assert new.alive and new.id in g.players


def test_incompatible_save_rejected():
    d = played_game().to_dict()
    with pytest.raises(ValueError):
        Game.from_dict({**d, "version": 999})
    with pytest.raises(ValueError):
        Game.from_dict({**d, "w": 10})


def test_snapshot_db_keeps_latest_only():
    g = played_game()
    for i in range(KEEP_SNAPSHOTS + 3):
        g.tick()
        save_snapshot("test-app", Game.SAVE_VERSION, g.tick_no, dump_world(g.to_dict()))
    latest = load_latest("test-app")
    assert latest["tick"] == g.tick_no
    from sqlalchemy import func, select
    from app.db import WorldSnapshot, get_db
    with get_db() as db:
        n = db.scalar(select(func.count()).select_from(WorldSnapshot).where(WorldSnapshot.app == "test-app"))
    assert n == KEEP_SNAPSHOTS
    assert load_latest("no-such-app") is None


def join(c):
    with c.websocket_connect("/apps/lordwar/ws") as ws:
        ws.send_json({"type": "join"})
        return ws.receive_json()


def test_kingdom_survives_restart():
    # 第一次启动：注册、进入游戏、拓展领地
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "restart_user", "password": "secret123"})
        first = join(c)
        p = server.game.players[first["id"]]
        p.res["gold"] = 9999.0
        before_tiles = set(p.tiles)
        before_game = server.game
    # 退出 with 时服务器关闭并存档。第二次启动：读档
    with TestClient(app) as c:
        assert server.game is not before_game                 # 确实是从存档重建的
        c.post("/api/auth/login", json={"username": "restart_user", "password": "secret123"})
        second = join(c)
        p2 = server.game.players[second["id"]]
        assert second["id"] == first["id"]
        assert p2.tiles == before_tiles
        assert p2.res["gold"] >= 9999.0
