"""scripts/changes.py：按改动选测试、检查 PR 范围。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("changes", ROOT / "scripts" / "changes.py")
changes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changes)


def test_scope_of():
    assert changes.scope_of("projects/snake/static/game.js") == "projects/snake"
    assert changes.scope_of("projects/lordwar/game.py") == "projects/lordwar"
    # projects/ 目录本身的文件、以及其他所有文件都属于平台
    assert changes.scope_of("projects/__init__.py") == changes.PLATFORM
    assert changes.scope_of("app/main.py") == changes.PLATFORM
    assert changes.scope_of("README.md") == changes.PLATFORM
    # 不合法的目录名不当作项目，也就不会被拼进测试命令
    assert changes.scope_of("projects/$(rm -rf x)/a.py") == changes.PLATFORM


def test_select_tests_for_one_project(tmp_path):
    (tmp_path / "projects" / "snake").mkdir(parents=True)
    files = ["projects/snake/static/game.js", "projects/snake/REQUIREMENTS.md"]
    assert changes.select_tests(files, root=tmp_path) == ["tests", "projects/snake"]


def test_select_tests_platform_code_runs_everything(tmp_path):
    assert changes.select_tests(["app/main.py"], root=tmp_path) == ["."]
    assert changes.select_tests(["requirements.txt", "projects/snake/x.js"], root=tmp_path) == ["."]


def test_select_tests_docs_only(tmp_path):
    assert changes.select_tests(["AGENTS.md", "docs/requirements.md"], root=tmp_path) == ["tests"]
    assert changes.select_tests([], root=tmp_path) == ["tests"]


def test_select_tests_skips_deleted_project(tmp_path):
    # 删除整个项目时目录已经不存在，只跑平台测试
    assert changes.select_tests(["projects/old/game.py"], root=tmp_path) == ["tests"]


def test_check_scope():
    assert changes.check_scope(["projects/snake/a.js", "projects/snake/b.css"]) is None
    assert changes.check_scope(["app/main.py", "AGENTS.md"]) is None
    assert changes.check_scope([]) is None
    problem = changes.check_scope(["projects/snake/a.js", "projects/lordwar/b.py"])
    assert problem and "projects/snake" in problem and "projects/lordwar" in problem
    assert changes.check_scope(["projects/snake/a.js", "app/main.py"])


def test_projects_are_discovered_and_sorted():
    from projects import PROJECTS
    slugs = [p.slug for p in PROJECTS]
    assert {"lordwar", "snake"} <= set(slugs)
    assert [(p.order, p.slug) for p in PROJECTS] == sorted((p.order, p.slug) for p in PROJECTS)
