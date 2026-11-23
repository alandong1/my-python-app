#!/usr/bin/env python3
"""根据改动了哪些文件，决定跑哪些测试、检查 PR 的改动范围。本地和 CI 共用。

用法：
  .venv/bin/python scripts/changes.py run      # 跑这次改动相关的测试（本地开发用这个）
  python3 scripts/changes.py tests             # 只打印要跑的测试路径
  python3 scripts/changes.py scope             # 检查改动是否只属于一个范围
  可选参数：--base <提交>  和谁比较（默认 origin/main）
            --files a b c  直接指定改动的文件（测试用）

「范围」：projects/<目录>/ 下的文件属于那个项目，其余所有文件都属于平台。
一个 PR 只能改一个范围（见 AGENTS.md「项目之间的边界」）。

选测试的规则：
  - 改了平台的代码或配置（不只是 .md 文档）→ 全部测试：平台会影响所有项目
  - 否则 → 平台测试 tests/ + 每个被改动的项目自己的测试
    平台测试总是要跑：所有项目在同一个进程里，一个项目坏了可能让整个网站起不来，
    tests/ 里有「所有项目都能挂载」的检查
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
PLATFORM = "平台"
# 项目目录名必须是合法的 Python 包名；也防止奇怪的目录名被拼进命令行
_PROJECT_DIR = re.compile(r"[a-z][a-z0-9_]*")


def scope_of(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "projects" and _PROJECT_DIR.fullmatch(parts[1]):
        return f"projects/{parts[1]}"
    return PLATFORM


def scopes(files: Iterable[str]) -> dict:
    result: dict = {}
    for f in files:
        result.setdefault(scope_of(f), []).append(f)
    return result


def select_tests(files: List[str], root: Path = ROOT) -> List[str]:
    """返回要传给 pytest 的路径。["."] 表示全部测试。"""
    platform_code = [f for f in files if scope_of(f) == PLATFORM and not f.endswith(".md")]
    if platform_code:
        return ["."]
    targets = ["tests"]
    for scope in sorted(scopes(files)):
        if scope != PLATFORM and (root / scope).is_dir():
            targets.append(scope)
    return targets


def check_scope(files: List[str]) -> Optional[str]:
    """改动只属于一个范围时返回 None，否则返回说明。"""
    groups = scopes(files)
    if len(groups) <= 1:
        return None
    lines = ["这个 PR 同时改动了多个范围，一个 PR 只能改一个项目，或者只改平台："]
    for scope in sorted(groups):
        shown = groups[scope][:5]
        more = f" 等 {len(groups[scope])} 个文件" if len(groups[scope]) > 5 else ""
        lines.append(f"  - {scope}：{', '.join(shown)}{more}")
    lines += [
        "请拆成多个 PR，每个 PR 只改一个范围。",
        "实在拆不开（例如平台接口变了，所有项目都要跟着改）：停下来告诉负责人，",
        "由负责人审核后用管理员权限合并。",
    ]
    return "\n".join(lines)


def _git(*args: str) -> List[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]


def changed_files(base: str) -> List[str]:
    """和 base 相比改动过的文件：已提交的 + 还没提交的 + 新建还没 add 的。"""
    files = set(_git("diff", "--name-only", f"{base}...HEAD"))
    files |= set(_git("diff", "--name-only", "HEAD"))
    files |= set(_git("ls-files", "--others", "--exclude-standard"))
    return sorted(files)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["tests", "scope", "run"])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*")
    args, extra = parser.parse_known_args(argv)

    files = args.files if args.files is not None else changed_files(args.base)

    if args.command == "scope":
        problem = check_scope(files)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        names = ", ".join(sorted(scopes(files))) or "没有改动"
        print(f"✅ 改动范围：{names}")
        return 0

    targets = select_tests(files)
    if args.command == "tests":
        print(" ".join(targets))
        return 0

    print(f"改动的文件：{len(files)} 个 → 跑测试：{' '.join(targets)}")
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *targets, *extra], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
