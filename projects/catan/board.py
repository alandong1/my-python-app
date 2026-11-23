"""卡坦岛的棋盘：六边形地块、顶点（放村庄的角）、边（放道路的线）。

几何方式：地块是「尖顶」六边形（上下有尖），半径为 1。
每个角、每条边都用坐标唯一标识（四舍五入后的位置），相邻的地块自动共用角和边。
服务器用整数编号（id）描述棋盘，前端直接用同一套编号画图、点击。
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from . import config as C

RADIUS = 2   # 19 个地块的标准棋盘


def _cells(radius: int) -> List[Tuple[int, int]]:
    """轴坐标 (q, r) 表示的六边形区域，按顺序排好，保证编号稳定。"""
    cells = []
    for q in range(-radius, radius + 1):
        for r in range(max(-radius, -q - radius), min(radius, -q + radius) + 1):
            cells.append((q, r))
    return cells


def _center(q: int, r: int) -> Tuple[float, float]:
    return math.sqrt(3) * (q + r / 2), 1.5 * r


class Board:
    """棋盘数据。编号都是列表下标。

    hexes[i]:    {"id", "cx", "cy", "terrain", "number", "corners": [6 个顶点 id], "edges": [6 个边 id]}
    vertices[i]: {"id", "x", "y", "adj": [相邻顶点], "edges": [相连的边], "hexes": [相邻地块]}
    edges[i]:    {"id", "a", "b", "hexes": [1 或 2 个地块]}
    harbors:     [{"edge": 边 id, "type": "any" 或资源名}]
    """

    def __init__(self):
        self.hexes: List[dict] = []
        self.vertices: List[dict] = []
        self.edges: List[dict] = []
        self.harbors: List[dict] = []

    def desert(self) -> int:
        return next(h["id"] for h in self.hexes if h["terrain"] == "desert")

    def hex_neighbors_by_edge(self, hid: int) -> List[int]:
        out = []
        for eid in self.hexes[hid]["edges"]:
            for other in self.edges[eid]["hexes"]:
                if other != hid:
                    out.append(other)
        return out

    def public(self) -> dict:
        """发给前端的棋盘（不含内部关系，只含画图需要的信息）。"""
        return {
            "hexes": [{"id": h["id"], "cx": h["cx"], "cy": h["cy"], "terrain": h["terrain"],
                       "number": h["number"], "corners": h["corners"]} for h in self.hexes],
            "vertices": [{"id": v["id"], "x": v["x"], "y": v["y"]} for v in self.vertices],
            "edges": [{"id": e["id"], "a": e["a"], "b": e["b"]} for e in self.edges],
            "harbors": self.harbors,
        }


def generate(rng: random.Random) -> Board:
    board = Board()
    vertex_ids: Dict[Tuple[float, float], int] = {}

    # 1. 地块和顶点
    for hid, (q, r) in enumerate(_cells(RADIUS)):
        cx, cy = _center(q, r)
        corners = []
        for k in range(6):
            ang = math.radians(60 * k + 30)          # 尖顶六边形的 6 个角
            x, y = cx + math.cos(ang), cy + math.sin(ang)
            key = (round(x, 3), round(y, 3))
            if key not in vertex_ids:
                vertex_ids[key] = len(board.vertices)
                board.vertices.append({"id": vertex_ids[key], "x": round(x, 4), "y": round(y, 4),
                                       "adj": [], "edges": [], "hexes": []})
            vid = vertex_ids[key]
            corners.append(vid)
            board.vertices[vid]["hexes"].append(hid)
        board.hexes.append({"id": hid, "cx": round(cx, 4), "cy": round(cy, 4), "terrain": None,
                            "number": None, "corners": corners, "edges": []})

    # 2. 边：相邻的两个角连成一条边
    edge_ids: Dict[Tuple[int, int], int] = {}
    for h in board.hexes:
        for k in range(6):
            a, b = h["corners"][k], h["corners"][(k + 1) % 6]
            key = (min(a, b), max(a, b))
            if key not in edge_ids:
                edge_ids[key] = len(board.edges)
                board.edges.append({"id": edge_ids[key], "a": key[0], "b": key[1], "hexes": []})
                board.vertices[key[0]]["adj"].append(key[1])
                board.vertices[key[1]]["adj"].append(key[0])
                board.vertices[key[0]]["edges"].append(edge_ids[key])
                board.vertices[key[1]]["edges"].append(edge_ids[key])
            eid = edge_ids[key]
            board.edges[eid]["hexes"].append(h["id"])
            h["edges"].append(eid)

    # 3. 地形：随机打乱
    terrains = list(C.TERRAIN_DECK)
    rng.shuffle(terrains)
    for h, t in zip(board.hexes, terrains):
        h["terrain"] = t

    # 4. 数字圆片：随机排列，尽量让 6 和 8 不相邻（红数字不挨着，平衡性更好）
    land = [h for h in board.hexes if h["terrain"] != "desert"]
    tokens = list(C.NUMBER_TOKENS)
    for _ in range(1000):
        rng.shuffle(tokens)
        for h, n in zip(land, tokens):
            h["number"] = n
        if not _red_numbers_touch(board):
            break

    # 5. 港口：沿海岸线均匀分布 9 个
    coast = [e for e in board.edges if len(e["hexes"]) == 1]
    coast.sort(key=lambda e: _edge_angle(board, e))
    m = len(coast)
    offset = rng.random() * m / len(C.HARBOR_TYPES)
    types = list(C.HARBOR_TYPES)
    rng.shuffle(types)
    for i, t in enumerate(types):
        idx = int(offset + i * m / len(types)) % m
        board.harbors.append({"edge": coast[idx]["id"], "type": t})
    return board


def _edge_angle(board: Board, e: dict) -> float:
    a, b = board.vertices[e["a"]], board.vertices[e["b"]]
    return math.atan2((a["y"] + b["y"]) / 2, (a["x"] + b["x"]) / 2)


def _red_numbers_touch(board: Board) -> bool:
    for e in board.edges:
        if len(e["hexes"]) == 2:
            n1 = board.hexes[e["hexes"][0]]["number"]
            n2 = board.hexes[e["hexes"][1]]["number"]
            if n1 in (6, 8) and n2 in (6, 8):
                return True
    return False
