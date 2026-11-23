"""Dev Lab 平台入口：首页应用商店 + 账户系统 + 挂载 projects/ 下的各个项目。

运行：uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from projects import PROJECTS

from . import settings
from .auth import router as auth_router
from .db import describe_db, init_db
from .pages import html_page

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("devlab")
STATIC = Path(__file__).resolve().parent.parent / "static"
PLATFORM_NAME = "Dev Lab"
BOOT_TIME = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("版本：%s，数据库：%s", settings.GIT_COMMIT, describe_db())
    if settings.IS_RENDER and settings.DATABASE_URL.startswith("sqlite"):
        # 线上用 SQLite 的话，数据会在每次重启时丢失。宁可启动失败，也不要悄悄丢数据
        log.error("线上环境没有配置 DATABASE_URL！请在 Render 的 Environment 里添加 Neon 连接字符串。")
        raise RuntimeError("DATABASE_URL is required on Render")
    await run_in_threadpool(init_db)
    for p in PROJECTS:
        if p.startup:
            await p.startup()
            log.info("项目已启动：%s", p.slug)
    yield
    # 关闭时倒序关闭各项目（例如游戏会在这里存档）。一个项目出错不影响其他项目
    for p in reversed(PROJECTS):
        if p.shutdown:
            try:
                await p.shutdown()
            except Exception:
                log.exception("项目关闭出错：%s", p.slug)


app = FastAPI(title=PLATFORM_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(auth_router)

for _p in PROJECTS:
    if _p.external_url:
        continue
    if _p.static_dir:
        app.mount(f"/apps/{_p.slug}/static", StaticFiles(directory=_p.static_dir),
                  name=f"{_p.slug}-static")
    if _p.router:
        app.include_router(_p.router, prefix=f"/apps/{_p.slug}")


@app.get("/")
async def store():
    """首页：应用商店。"""
    return html_page(STATIC / "index.html")


@app.get("/api/apps")
async def list_apps():
    return {"platform": PLATFORM_NAME, "apps": [p.card() for p in PROJECTS]}


_LOCAL_SLUGS = {p.slug for p in PROJECTS if not p.external_url}


@app.get("/apps/{slug}")
async def project_without_slash(slug: str):
    """/apps/lordwar → /apps/lordwar/，这样项目页面里的相对路径才能正确解析。"""
    if slug not in _LOCAL_SLUGS:
        # 只对已登记的项目跳转，否则 /apps/x/ 和 /apps/x 会来回无限跳转
        raise HTTPException(404, "没有这个项目")
    return RedirectResponse(f"/apps/{slug}/", status_code=307)


@app.get("/health")
async def health():
    return {"ok": True, "projects": {p.slug: p.health() for p in PROJECTS if p.health}}


@app.get("/version")
async def version():
    """当前运行的是哪个 git 提交，用来确认新版本是否已经部署上线。"""
    return {
        "commit": settings.GIT_COMMIT,
        "started": BOOT_TIME.isoformat(timespec="seconds"),
        "db": "postgresql" if settings.DATABASE_URL.startswith("postgresql") else "sqlite",
    }
