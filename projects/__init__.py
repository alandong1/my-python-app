"""Dev Lab 上的所有项目：自动发现，新增项目**不用改这个文件**。

规则：projects/ 下每个子目录（Python 包）就是一个项目，它的 __init__.py 里必须定义
PROJECT = Project(...)，并且 slug 和目录名一致（目录名里的 _ 对应 slug 里的 -）。

为什么自动发现：多个项目同时开发时，如果都要往同一个列表里加一行，就会互相冲突。

商店里卡片的顺序：Project.order 小的在前，相同时按 slug 字母顺序。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import List

from app.registry import Project


def discover() -> List[Project]:
    found = []
    for info in pkgutil.iter_modules(__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        project = getattr(module, "PROJECT", None)
        if not isinstance(project, Project):
            raise RuntimeError(f"projects/{info.name}/__init__.py 里没有定义 PROJECT = Project(...)")
        if project.slug != info.name.replace("_", "-"):
            raise RuntimeError(
                f"projects/{info.name}/ 的 slug 是 {project.slug!r}，必须和目录名一致"
                f"（目录名里的 _ 对应 slug 里的 -）")
        found.append(project)
    return sorted(found, key=lambda p: (p.order, p.slug))


PROJECTS: List[Project] = discover()
