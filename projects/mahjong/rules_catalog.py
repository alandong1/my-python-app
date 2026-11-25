"""麻将玩法目录：首页下拉菜单里显示的玩法。

只有 available=True 的玩法能开房间。其他玩法的规则还在确认中，先显示出来但不能玩，
等规则文本确认后再开放（见 REQUIREMENTS.md 第 14 节）。
"""
from __future__ import annotations

from typing import Dict, List

RULES: List[Dict] = [
    {"id": "hubei", "name": "湖北卡五星", "available": True, "note": "三人，两门数牌加中发白，已实现"},
    {"id": "hongzhong", "name": "红中赖子杠", "available": False, "note": "规则确认中"},
    {"id": "sichuan", "name": "四川血战到底", "available": False, "note": "规则确认中"},
    {"id": "xueliu", "name": "血流成河", "available": False, "note": "规则确认中"},
    {"id": "shanghai", "name": "上海麻将", "available": False, "note": "规则确认中"},
]

BY_ID: Dict[str, Dict] = {r["id"]: r for r in RULES}


def label(rule_id: str) -> str:
    r = BY_ID.get(rule_id)
    return r["name"] if r else rule_id


def is_available(rule_id: str) -> bool:
    r = BY_ID.get(rule_id)
    return bool(r and r["available"])
