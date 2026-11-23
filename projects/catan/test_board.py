"""棋盘生成：数量、距离、红数字规则、港口。"""
import random

from projects.catan.board import generate


def test_standard_board_size():
    b = generate(random.Random(7))
    assert len(b.hexes) == 19
    assert len(b.vertices) == 54          # 标准卡坦岛：54 个村庄位置
    assert len(b.edges) == 72             # 72 条路的位置
    assert sum(1 for e in b.edges if len(e["hexes"]) == 1) == 30   # 海岸线 30 条边


def test_each_vertex_touches_at_most_three_hexes_and_edges_are_consistent():
    b = generate(random.Random(8))
    for v in b.vertices:
        assert 1 <= len(v["hexes"]) <= 3
        assert len(v["adj"]) == len(v["edges"]) in (2, 3)


def test_terrain_and_numbers():
    b = generate(random.Random(9))
    deserts = [h for h in b.hexes if h["terrain"] == "desert"]
    assert len(deserts) == 1 and deserts[0]["number"] is None
    numbers = sorted(h["number"] for h in b.hexes if h["number"] is not None)
    assert numbers == sorted([2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12])


def test_red_numbers_not_adjacent_for_many_seeds():
    for seed in range(30):
        b = generate(random.Random(seed))
        for e in b.edges:
            if len(e["hexes"]) == 2:
                n = [b.hexes[h]["number"] for h in e["hexes"]]
                assert not (n[0] in (6, 8) and n[1] in (6, 8)), seed


def test_nine_harbors_on_coast_with_standard_types():
    b = generate(random.Random(10))
    assert len(b.harbors) == 9
    assert sorted(h["type"] for h in b.harbors) == sorted(
        ["any"] * 4 + ["brick", "lumber", "wool", "grain", "ore"])
    coast = {e["id"] for e in b.edges if len(e["hexes"]) == 1}
    assert all(h["edge"] in coast for h in b.harbors)
    assert len({h["edge"] for h in b.harbors}) == 9
