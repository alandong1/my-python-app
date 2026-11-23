# AGENTS.md

给 AI 编程助手（Claude Code、Codex、Copilot、Cursor 等）和人类开发者的项目说明。
**这是开发流程和规范的唯一正式版本**，其他说明文件（`CLAUDE.md`、`.github/copilot-instructions.md`）都指向这里。

## 沟通

- 项目负责人用**中文**交流，回复、解释和文档都用中文。
- 负责人正在学习开发，做改动时简单说明**为什么**这样做，遇到新概念顺便解释。

## 项目概况

浏览器多人实时策略游戏「领主战争」。FastAPI 后端 + WebSocket 实时同步 + 原生 JS Canvas 前端。

| 路径 | 作用 |
|---|---|
| `app/config.py` | 游戏数值（建筑、兵种、野怪、视野），调平衡改这里 |
| `app/game.py` | 游戏逻辑：地图生成、战斗、战争迷雾、tick 循环 |
| `app/main.py` | FastAPI 入口、WebSocket、`/health`、`/version` |
| `app/auth.py` / `app/oauth.py` | 账户：游客、注册登录、邮箱验证、Google/Apple/微信 OAuth |
| `app/db.py` / `app/settings.py` | 数据库表结构 / 环境变量配置 |
| `static/` | 前端（`index.html`、`game.js`、`style.css`） |
| `tests/` | pytest 测试 |
| `scripts/wait_for_deploy.sh` | push 后等待 Render 部署上线 |
| `deploy.conf` | 测试环境地址（非机密，唯一来源） |
| `docs/requirements.md` | **需求与设计决定**：做什么、为什么这样做、待办 |

## 常用命令

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # 首次安装
.venv/bin/uvicorn app.main:app --reload                                  # 本地运行 http://localhost:8000
.venv/bin/python -m pytest -q                                            # 运行全部测试
scripts/wait_for_deploy.sh                                               # push 后等待部署上线
```

## 开发流程（必须遵守）

0. **需求有变化时，先更新 `docs/requirements.md`**（新增/修改/放弃的需求、做出的设计决定及原因），再动代码。
   负责人在对话里提出的需求，如果会影响以后的开发，都要记进去，不能只留在聊天记录里。
1. **改代码。**
2. **本地测试**：运行 `.venv/bin/python -m pytest -q`，必须全部通过。
   - 新功能或修 bug 时，在 `tests/` 里补充对应测试。
   - 改了前端：本地启动服务器，在浏览器里实际操作一遍，确认没有 JS 报错。
3. **提交并直接 push 到 `main`**（目前是个人项目，不走 PR）：
   `git add <具体文件>` → `git commit` → `git push origin main`
4. **等待部署上线**：运行 `scripts/wait_for_deploy.sh`。它会轮询 `/version`，直到线上版本等于刚推送的提交。
5. **通知负责人刷新页面**，并说明改了什么。提醒：每次部署都会**重置游戏世界**（账号不受影响）。
   如果这次改动需要负责人在**外部网站**上操作（见下面「改动时同步更新的文件」里的 🖐️ 项），必须逐条列出。

测试没通过就不要 push。部署超时就去看 Render 的 Events/Logs，不要假装已上线。

## 环境

| | 本地开发 | 远程测试环境 |
|---|---|---|
| 地址 | http://localhost:8000 | 见 `deploy.conf` 的 `DEPLOY_URL`（唯一来源） |
| 数据库 | 未设置 `DATABASE_URL` 时用 SQLite `dev.db` | Neon PostgreSQL（us-east-2） |
| 部署 | — | push 到 `main` 后 Render 自动部署（约 1–5 分钟） |

- 远程环境目前是**测试环境**，还没有真实玩家。以后有正式环境时会分出 `production` 分支、第二个 Render 服务和 Neon 分支。
- `/version` 返回线上的提交号和数据库类型；`/health` 返回在线人数。
- 游戏世界在**内存**里，重启/部署即清空；账户和登录会话在数据库里，会保留。
- 在 Render 上没有 `DATABASE_URL` 时服务会拒绝启动（防止悄悄用临时 SQLite 丢数据）。

## 改动时同步更新的文件

每次改动后对照这张表，把相关文件一起改掉，放在**同一个提交**里。
🖐️ = 在 repo 之外、AI 无法操作的设置，必须明确告诉负责人去哪里改、改成什么。

| 改动类型 | repo 里要同步更新的 | 🖐️ 需要负责人在外部操作的 |
|---|---|---|
| 功能需求 / 玩法规则 | `docs/requirements.md`；玩法变化较大时同步 `README.md` 的「玩法」 | — |
| 开发流程 | `AGENTS.md`「开发流程」；涉及部署时 `.claude/skills/deploy/SKILL.md`；`.github/copilot-instructions.md` 里的摘要 | — |
| 编码规范 | `AGENTS.md`「规范」；重要的同步到 `.github/copilot-instructions.md` | — |
| 测试环境网址 | `deploy.conf` | Render 环境变量 `PUBLIC_BASE_URL`；已启用的 OAuth 在 Google/Apple/微信后台的回调地址 |
| 换部署平台 / 服务器 | `deploy.conf`、`render.yaml`、`app/settings.py`（`IS_RENDER`、`GIT_COMMIT` 的来源）、`app/main.py` 里的 Render 判断、`AGENTS.md`「环境」、`README.md` | 新平台的环境变量；OAuth 回调地址 |
| 换数据库 | `AGENTS.md`「环境」、`.env.example` | 新平台上的 `DATABASE_URL`；负责人本地 `.env` |
| 新增 / 删除环境变量 | `app/settings.py`、`.env.example`；线上也需要的加进 `render.yaml` | Render 上填写实际值 |
| 数据库表结构 | `app/db.py`；见「规范 → 数据库」 | 已有表需要在 Neon 上执行迁移 |
| 新增依赖 | `requirements.txt`（或 `requirements-dev.txt`），固定版本号 | — |
| 新增 API / 前端操作 | 对应的 `tests/`；用户可见的操作写进 `README.md`「操作」 | — |

## 规范

**安全**
- 密钥只放在 `.env`（已被 git 忽略）或 Render 的 Environment 里。不要提交、不要写进代码、不要在聊天里贴出。`.env.example` 只放空模板。
- 不要用 `git add -A` 一把梭，逐个确认要提交的文件。
- 测试永远用临时 SQLite（见 `tests/conftest.py`），不要连 `.env` 里的真实数据库。

**代码**
- 本地 Python 是 **3.9**，Render 是 3.12。代码必须兼容 3.9：文件开头加 `from __future__ import annotations`，不用 `match`、不用 `X | Y` 运行时类型。
- 新增依赖要写进 `requirements.txt` 并**固定版本号**；只用于开发的写进 `requirements-dev.txt`。
- 游戏数值放 `app/config.py`，不要散落在逻辑里。
- 玩家可见的数据由服务器按战争迷雾裁剪（`Game.view_for`），不要把看不见的信息发给客户端。
- 前端渲染用户输入的文字要转义（`esc()` 或 `textContent`）。

**数据库**
- 表由 `init_db()` 里的 `create_all` 创建。它**只会新建不存在的表，不会修改已有的表**。
  给已有的表加/改字段时，必须同时处理 Neon 上的旧表（手动 `ALTER TABLE`，或引入 Alembic 做迁移），并告诉负责人。

**提交**
- 提交信息用英文，第一行简短说明做了什么，正文列出要点。
