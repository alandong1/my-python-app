# AGENTS.md

给 AI 编程助手（Claude Code、Codex、Copilot、Cursor 等）和人类开发者的项目说明。
**这是开发流程和规范的唯一正式版本**，其他说明文件（`CLAUDE.md`、`.github/copilot-instructions.md`）都指向这里。

## 沟通

- 项目负责人用**中文**交流，回复、解释和文档都用中文。
- 负责人正在学习开发，做改动时简单说明**为什么**这样做，遇到新概念顺便解释。

## 项目概况

**Dev Lab**：负责人的个人项目平台。一个仓库、一个网站、一个数据库、一套开发流程，承载多个项目（游戏、工具、AI agent……）。
首页 `/` 是「应用商店」，列出所有项目；每个项目挂在 `/apps/<slug>/` 下。账号全平台通用。

技术栈：FastAPI 后端 + 原生 JS 前端；PostgreSQL（Neon）；部署在 Render。

| 路径 | 作用 |
|---|---|
| `app/` | **平台核心**：入口、账户、数据库、存档服务、首页 |
| `app/main.py` | FastAPI 入口：首页、`/api/apps`、`/health`、`/version`，挂载所有项目 |
| `app/registry.py` | `Project`：项目在平台上的登记信息（名字、图标、路由、启动/关闭钩子……） |
| `app/auth.py` / `app/oauth.py` | 账户：游客、注册登录、邮箱验证、Google/Apple/微信 OAuth、WebSocket 鉴权工具 |
| `app/db.py` / `app/settings.py` | 数据库表结构 / 环境变量配置 |
| `app/persistence.py` | 通用的快照存档服务（按项目 slug 区分），项目可直接使用 |
| `app/pages.py` | 返回 HTML 页面并给 js/css 加版本号 |
| `static/` | 平台首页（应用商店、登录、我的账号） |
| `projects/__init__.py` | **自动发现项目**：扫描 `projects/` 下的每个目录，新增项目不用改它 |
| `projects/<slug>/` | 各个项目：代码、`static/` 前端、`test_*.py` 测试、`REQUIREMENTS.md` 需求 |
| `projects/lordwar/` | 项目一：多人实时策略游戏「领主战争」 |
| `tests/` | 平台层的测试（账户、OAuth、首页、项目挂载） |
| `conftest.py` | 所有测试共用的配置（临时数据库、测试客户端） |
| `docs/requirements.md` | **平台**的需求与设计决定 |
| `scripts/changes.py` | 按改动的文件选测试（`run`）、检查 PR 改动范围（`scope`） |
| `scripts/wait_for_deploy.sh` | 等待 PR 合并进 `main`、Render 部署上线 |
| `.github/workflows/` | GitHub Actions：`ci.yml` 自动测试和改动范围检查，`pr-gate.yml` PR 审核规则，`ci-failure-limit.yml` CI 失败次数上限，`sync-prs.yml` 自动把 main 同步进落后的 PR |
| `deploy.conf` | 测试环境地址（非机密，正式来源；`README.md` 里有一份抄录） |

## 常用命令

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # 首次安装
.venv/bin/uvicorn app.main:app --reload                                  # 本地运行 http://localhost:8000
.venv/bin/python scripts/changes.py run                                 # 跑这次改动相关的测试（平时用这个）
.venv/bin/python -m pytest -q                                            # 运行全部测试（平台 + 所有项目）
.venv/bin/python -m pytest -q tests projects/lordwar                     # 平台测试 + 某个项目
scripts/wait_for_deploy.sh                                               # 开 PR 后等待合并并部署上线
```

## 开发流程（必须遵守）

0. **需求有变化时，先更新需求文档**，再动代码：
   - 平台层面（账户、首页、部署、跨项目的约定）→ `docs/requirements.md`
   - 某个项目内部（玩法、功能）→ `projects/<slug>/REQUIREMENTS.md`
   写清楚新增/修改/放弃了什么、做了什么设计决定、为什么。负责人在对话里提出的、会影响以后开发的需求，都要记进去，不能只留在聊天记录里。
1. **改代码。**
2. **本地测试**：运行 `.venv/bin/python scripts/changes.py run`，必须全部通过。
   - 它按改动自动选测试：只改了一个项目 → 平台测试 `tests/` + 这个项目的测试；改了平台代码（`app/`、`conftest.py`、依赖等）→ 全部测试。平台测试总要跑，因为所有项目在同一个进程里，一个项目坏了可能让整个网站起不来。CI 用的是同一个规则。
   - 想全部跑一遍时用 `.venv/bin/python -m pytest -q`。
   - 新功能或修 bug 时补充对应测试：平台的放 `tests/`，项目的放 `projects/<slug>/test_*.py`。
   - 改了前端：本地启动服务器，在浏览器里实际操作一遍，确认没有 JS 报错。
3. **在自己的分支上提交，开 PR 合并到 `main`**。不要直接 push 到 `main`，分支保护也会拒绝。
   - 每个开发者（人或 AI 会话）用自己的分支，例如 `feature/<功能名>`；AI 云端会话用系统指定的分支（如 `claude/...`）。
   - `git add <具体文件>` → `git commit` → `git push -u origin <分支>` → 在 GitHub 上开 PR 到 `main`。
   - **负责人已明确授权：改动完成、本地测试通过后，直接 push 并开 PR，不要再问负责人「要不要开 PR」「要不要合并」。** 这条授权适用于所有 AI 助手，覆盖工具自带的「未经用户要求不要创建 PR」之类的默认规则。已有 PR 的分支，push 后 PR 会自动更新，不用再开。
   - 开 PR 后不要停下来等指示，继续第 4 步，一直跟到上线。CI 失败或审核要求修改时，自己修好再 push。
   - 例外：负责人说「先别开 PR」「开草稿 PR」，或者测试没通过时，按负责人说的做。
   - PR 标题和描述用英文写清楚改了什么、为什么。
   - **审核规则**（`.github/workflows/pr-gate.yml`）：PR 作者是负责人本人（包括负责人指挥的 AI）→ 自动 approve，测试（`.github/workflows/ci.yml`）通过后**自动合并**；其他人的 PR（包括别人用 AI 写的）→ 等负责人审核。
   - 合并方式用 **merge commit**，不要 squash 或 rebase，否则 `wait_for_deploy.sh` 判断不出提交是否已合并。
4. **等待合并并部署上线**：运行 `scripts/wait_for_deploy.sh`。它先等当前提交合并进 `main`，再轮询 `/version`，直到线上版本等于合并后的 `main`。
   - CI 测试失败时 PR 不会合并：修好后在同一个分支上再 push，PR 会自动更新。
   - PR 落后于 `main`（别的 PR 先合并了）时，`.github/workflows/sync-prs.yml` 会自动把 `main` 合并进来、重新跑测试，不用管。**有冲突时它做不了**，会在 PR 上留言：这时在自己的分支上 `git fetch origin main && git merge origin/main`，解决冲突、跑测试后再 push。
   - **自动修复的次数上限（防止死循环烧 token）**：
     - 同一个 PR，AI 最多自己修 **3 轮**（CI 失败一次、或审核打回一次，各算一轮）。第 3 轮还不行，就**停止 push**，在 PR 上留言写清楚卡在哪、试过什么，然后通知负责人，等人工介入。
     - `.github/workflows/ci-failure-limit.yml` 会强制执行：同一个 PR 的 CI 失败满 3 次，自动打上 **`needs-human`** 标签、关闭自动合并、留言通知负责人。
     - PR 带 `needs-human` 标签时，**AI 不要再 push、不要去掉这个标签**，只能等负责人处理。负责人去掉标签后，计数从零开始，自动 approve 和自动合并也会恢复。
     - 不要为了让 CI 重新跑而推空提交，也不要跳过或删掉测试。同一份代码的 CI 最多手动重跑一次。
5. **通知负责人刷新页面**，并说明改了什么、去哪个页面看。
   - 有存档的项目（如领主战争）会在部署前自动存档、部署后恢复；如果这次改了存档格式，要提醒负责人「这次会开新世界」。
   - 如果这次改动需要负责人在**外部网站**上操作（见「改动时同步更新的文件」里的 🖐️ 项），必须逐条列出。

测试没通过就不要开 PR。部署超时就去看 Render 的 Events/Logs，不要假装已上线。

## 新建项目

1. 和负责人确认：项目名、`slug`（网址里的英文名，小写字母开头，只能有小写字母、数字、连字符）、图标、分类、是否需要登录，以及**技术选型**（见下一节「技术选型」）。
2. 建目录 `projects/<slug>/`，至少包含：
   - `__init__.py`：定义 `PROJECT = Project(...)`（参考 `projects/lordwar/__init__.py`）
   - `server.py`：`router = APIRouter()`，至少有 `@router.get("/")` 返回 `html_page(STATIC / "index.html")`
   - `static/index.html`：页面里的资源用**相对路径**（`static/xxx.js`），不要写 `/static/...`，那是平台首页的目录
   - `REQUIREMENTS.md`：这个项目的需求与设计决定
   - `test_*.py`：至少测试页面能打开、主要接口能用
3. **不用在任何共享文件里登记**：`projects/__init__.py` 会自动发现新目录，目录名必须和 slug 一致（目录名里的 `_` 对应 slug 里的 `-`）。商店里的排序用 `Project(order=...)` 调整，默认 100，小的在前。
4. 按开发流程测试、提交、部署。新建项目的 PR 只包含 `projects/<slug>/` 里的文件。

项目可以使用平台提供的：
- **账户**：HTTP 接口里用 `app.auth.require_user`；WebSocket 里先 `ws_same_origin(ws)`，再用 `lookup_session_user(ws.cookies.get(SESSION_COOKIE))`。页面里没登录时跳转到 `/?login=1&next=<当前路径>`。
- **存档**：`app.persistence` 的 `save_snapshot` / `load_latest`，用自己的 slug 区分。
- **启动/关闭钩子**：`Project.startup` / `shutdown`，比如启动后台循环、关闭前存档。

## 技术选型

新建项目（或者项目的需求发生大的变化）时，AI 要**根据这个项目的需求选择语言和架构**，不要不假思索地照搬上一个项目。

**「最合适」不等于「运行最快」**，综合看四点，按重要程度排列：
1. **能满足需求**：性能够用、能在目标设备上运行（浏览器 / 手机 / 电脑）。
2. **开发效率**：同样的功能，代码少、调试容易、有成熟的库。
3. **部署和维护成本**：能不能放进现有平台（同一个网站、同一个 Render 服务、同一个数据库）。每多一种语言或一个服务，就多一份部署、监控和费用。
4. **负责人能看懂**：负责人在学习开发，优先选主流、资料多的技术。

**默认技术栈**（没有特殊需求就用这个，可以直接放进平台）：
- 前端：原生 JavaScript（HTML + CSS），运行在浏览器里，电脑和手机都能用。
- 后端：Python + FastAPI，作为平台里的一个项目（`projects/<slug>/`）。
- 数据库：平台的 PostgreSQL，表名加 `<slug>_` 前缀。

**按需求选择**：

| 项目需求 | 推荐 | 放在哪里 |
|---|---|---|
| 简单的网页游戏 / 小工具，逻辑都在浏览器里 | 纯前端 JavaScript，服务器只负责发网页 | 平台内（例如 `snake`） |
| 多人实时互动、需要服务器保存状态 | 前端 JavaScript + 后端 Python（WebSocket） | 平台内（例如 `lordwar`） |
| 复杂的 2D 网页游戏（大量动画、物理效果） | JavaScript/TypeScript + 游戏引擎（如 Phaser） | 平台内，引擎文件放项目的 `static/` |
| 前端代码很多、多人维护 | 考虑 TypeScript，需要加构建步骤，先和负责人商量 | 平台内 |
| AI / 数据处理 | Python（生态最好）；耗时的计算放线程池，不要卡住事件循环 | 平台内；需要大量内存或 GPU 时单独部署 |
| 服务器要同时承载成千上万人、每秒大量计算 | Go / Rust / Java / C# 等编译型语言 | **单独部署**，商店用 `external_url` 登记 |
| 3D 游戏、要上架 Steam 或主机 | Unity（C#）/ Godot / Unreal（C++） | 单独的仓库或服务；能导出网页版的，可以挂到商店 |
| 必须上架 App Store / Google Play 的手机 App | Flutter 或 React Native（一套代码两个平台）；需要深度用到手机功能时用 Swift / Kotlin | 单独的仓库；需要服务器时可以复用平台的接口 |

**规则**：
- 选默认技术栈时，直接开始。
- **要用默认以外的语言、框架、构建工具，或者要单独部署时，先告诉负责人**：选了什么、为什么默认的不够用、会多出哪些部署和费用，等负责人同意再开始。
- 不管选了什么，都把**选型和理由**写进项目的 `REQUIREMENTS.md`（「技术选型」一节），以后的 agent 才知道为什么这么选、什么情况下该换。
- 不要为了「更快」过早优化：先用简单的方案做出来，真的遇到性能问题（有数据证明），再针对瓶颈优化或换技术。

## 项目之间的边界

- **网址**：项目的所有页面和接口都在 `/apps/<slug>/` 下。平台保留 `/`、`/static/`、`/api/`、`/health`、`/version`。
- **数据库**：项目自己的表名必须以 `<slug>_` 开头（例如 `lordwar_xxx`）；不要修改平台的表（`users`、`sessions` 等），需要用户信息时通过 `app.auth` 获取。
- **一个 PR 只改一个范围**：要么只改一个项目（`projects/<slug>/` 里的文件），要么只改平台（其他所有文件）。CI 的 `scope` 检查会拦住混在一起的 PR。
  - 原因：多个 agent 并行开发时，各改各的目录就不会冲突；PR 也更容易审核和回退。
  - 项目需要平台提供新功能时：先开一个平台 PR，合并后再开项目 PR。
  - 实在拆不开（例如平台接口变了，所有项目都要跟着改）：停下来告诉负责人，由负责人审核后用管理员权限合并。
- **代码**：项目只能 import `app.*` 的公开工具和自己目录里的代码，**不要 import 其他项目的代码**。多个项目都需要的功能，提到 `app/` 里。
- **稳定性**：所有项目在同一个进程里运行。一个项目的启动失败或死循环会影响整个网站，所以后台任务要捕获异常、不要阻塞事件循环；耗时的计算放进线程池。
- **太重的项目**（例如需要大量内存或 GPU 的 AI 服务）可以单独部署成另一个服务，在 `PROJECTS` 里用 `external_url` 登记，商店卡片会直接跳过去。

## 环境

| | 本地开发 | 远程测试环境 |
|---|---|---|
| 地址 | http://localhost:8000 | 见 `deploy.conf` 的 `DEPLOY_URL`（正式来源；`README.md` 里抄了一份供人查看，改网址时两处一起改） |
| 数据库 | 未设置 `DATABASE_URL` 时用 SQLite `dev.db` | Neon PostgreSQL（us-east-2） |
| 部署 | — | PR 合并进 `main` 后 Render 自动部署（约 1–5 分钟） |

- 远程环境目前是**测试环境**，还没有真实用户。以后有正式环境时会分出 `production` 分支、第二个 Render 服务和 Neon 分支。
- `/version` 返回线上的提交号和数据库类型；`/health` 返回各项目的状态。
- 在 Render 上没有 `DATABASE_URL` 时服务会拒绝启动（防止悄悄用临时 SQLite 丢数据）。

## 改动时同步更新的文件

每次改动后对照这张表，把相关文件一起改掉，放在**同一个提交**里。
🖐️ = 在 repo 之外、AI 无法操作的设置，必须明确告诉负责人去哪里改、改成什么。

| 改动类型 | repo 里要同步更新的 | 🖐️ 需要负责人在外部操作的 |
|---|---|---|
| 平台需求（账户、首页、部署、跨项目约定） | `docs/requirements.md` | — |
| 某个项目的需求 / 玩法 | `projects/<slug>/REQUIREMENTS.md` | — |
| 项目的技术选型 | 项目 `REQUIREMENTS.md` 的「技术选型」一节；改默认技术栈时改 `AGENTS.md`「技术选型」 | 单独部署的项目：新服务的部署和费用 |
| 新增 / 删除项目 | 只有 `projects/<slug>/` 目录本身（自动发现，不用登记） | — |
| 项目名称 / 图标 / 分类 / 状态 | `projects/<slug>/__init__.py` 的 `PROJECT` | — |
| 开发流程 | `AGENTS.md`「开发流程」；涉及部署时 `.claude/skills/deploy/SKILL.md`；`.github/copilot-instructions.md` 里的摘要；`docs/requirements.md`「环境与部署」 | — |
| CI 测试 / PR 审核规则 | `.github/workflows/ci.yml`、`.github/workflows/pr-gate.yml`、`.github/workflows/ci-failure-limit.yml`、`.github/workflows/sync-prs.yml`（它重复了 `pr-gate.yml` 的自动 approve 条件，两处要一致）、`AGENTS.md`「开发流程」、`docs/requirements.md` | 改了 CI 的 job 名或 Python 版本时，GitHub 分支保护里「必须通过的检查」（现在是 `scope`、`test (3.9)`、`test (3.12)`）也要跟着改 |
| 编码规范 | `AGENTS.md`「规范」；重要的同步到 `.github/copilot-instructions.md` | — |
| 测试环境网址 | `deploy.conf`、`README.md`「环境与网址」 | Render 环境变量 `PUBLIC_BASE_URL`；已启用的 OAuth 在 Google/Apple/微信后台的回调地址 |
| 换部署平台 / 服务器 | `deploy.conf`、`render.yaml`、`app/settings.py`（`IS_RENDER`、`GIT_COMMIT` 的来源）、`app/main.py` 里的 Render 判断、`AGENTS.md`「环境」、`README.md` | 新平台的环境变量；OAuth 回调地址 |
| 换数据库 | `AGENTS.md`「环境」、`.env.example` | 新平台上的 `DATABASE_URL`；负责人本地 `.env` |
| 新增 / 删除环境变量 | `app/settings.py`、`.env.example`；线上也需要的加进 `render.yaml` | Render 上填写实际值 |
| 数据库表结构 | `app/db.py`（平台）或项目自己的模块；见「规范 → 数据库」 | 已有表需要在 Neon 上执行迁移 |
| 领主战争存档里的数据（`Game.to_dict` / `from_dict`） | 两个方法一起改；不兼容旧存档时把 `Game.SAVE_VERSION` +1，并在 `projects/lordwar/test_persistence.py` 补测试 | 部署后会开新世界，事先告诉负责人 |
| 新增依赖 | `requirements.txt`（或 `requirements-dev.txt`），固定版本号 | — |
| 新增 API / 前端操作 | 对应的测试；用户可见的操作写进项目的 `REQUIREMENTS.md`（平台的写进 `README.md`） | — |

## 规范

**安全**
- 密钥只放在 `.env`（已被 git 忽略）或 Render 的 Environment 里。不要提交、不要写进代码、不要在聊天里贴出。`.env.example` 只放空模板。
- 不要用 `git add -A` 一把梭，逐个确认要提交的文件。
- 测试永远用临时 SQLite（见根目录 `conftest.py`），不要连 `.env` 里的真实数据库。
- 登录后跳转的地址必须经过 `app.auth.safe_next`（只允许本站相对路径），防止被利用跳到钓鱼网站。

**代码**
- 本地 Python 是 **3.9**，Render 是 3.12。代码必须兼容 3.9：文件开头加 `from __future__ import annotations`，不用 `match`、不用 `X | Y` 运行时类型。
- 新增依赖要写进 `requirements.txt` 并**固定版本号**；只用于开发的写进 `requirements-dev.txt`。
- 前端渲染用户输入的文字要转义（`esc()` 或 `textContent`）。
- 领主战争：游戏数值放 `projects/lordwar/config.py`；玩家可见的数据由服务器按战争迷雾裁剪（`Game.view_for`），不要把看不见的信息发给客户端。

**数据库**
- 表由 `init_db()` 里的 `create_all` 创建。它**只会新建不存在的表，不会修改已有的表**。
  给已有的表加/改字段时，必须同时处理 Neon 上的旧表（手动 `ALTER TABLE`，或引入 Alembic 做迁移），并告诉负责人。
- 项目的表定义如果放在项目目录里，要确保在 `init_db()` 之前被 import（在项目的 `__init__.py` 里 import 即可），否则不会被创建。
- 给领主战争的世界加了新的状态（新字段、新对象）时，**必须同时加进 `Game.to_dict` 和 `from_dict`**，否则重启后这部分数据会丢失。

**提交**
- 提交信息用英文，第一行简短说明做了什么，正文列出要点。
