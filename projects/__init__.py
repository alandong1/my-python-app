"""Dev Lab 上的所有项目。新增项目：在 projects/ 下建目录，然后加进下面的列表。

列表顺序就是首页「应用商店」里卡片的顺序。
"""
from typing import List

from app.registry import Project

from .lordwar import PROJECT as LORDWAR

PROJECTS: List[Project] = [
    LORDWAR,
]

_slugs = [p.slug for p in PROJECTS]
assert len(_slugs) == len(set(_slugs)), f"项目 slug 重复：{_slugs}"
