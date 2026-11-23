# Dev Lab

个人项目平台：一个网站、一个数据库、一套开发流程，承载多个项目（游戏、工具、AI agent……）。
首页是「应用商店」，每个项目挂在 `/apps/<slug>/` 下，账号全平台通用。

## 项目

每个项目是 [`projects/`](projects/) 下的一个目录，网址是 `/apps/<目录名>/`，需求文档是目录里的 `REQUIREMENTS.md`。
平台启动时自动发现所有项目，打开网站首页的应用商店就能看到完整列表。

## 账户

- **游客**：浏览器里生成随机凭证作为身份，同一浏览器再来还是同一个人
- **用户名 + 密码**注册登录，可选绑定邮箱（需点验证链接）
- **第三方登录**：Google / Apple / 微信，配置了对应密钥才会显示

## 环境与网址（参考）

| | 网址 | 说明 |
|---|---|---|
| 🌐 测试环境网站 | https://my-python-app-m3qj.onrender.com | 正式来源是 [`deploy.conf`](deploy.conf) 的 `DEPLOY_URL`，两处要保持一致 |
| 🚀 Render 控制台（部署） | https://dashboard.render.com | 登录后选服务 `my-python-app`：**Events** 看部署记录，**Logs** 看运行日志，**Environment** 填环境变量和密钥 |
| 🗄️ Neon 控制台（数据库） | https://console.neon.tech | 登录后选项目（区域 us-east-2）：**Tables** 看数据，**SQL Editor** 执行 SQL（如迁移），**Connect** 获取连接字符串 |

- 数据库连接字符串里有密码，**不写进仓库**：本地放 `.env` 的 `DATABASE_URL`，线上放 Render 的 Environment。
- 两个控制台都要用负责人自己的账号登录，AI 助手无法操作。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env        # 按需填写，全部留空也能运行
.venv/bin/uvicorn app.main:app --reload
```

打开 http://localhost:8000 。`.env` 里没有 `DATABASE_URL` 时使用本地 SQLite 文件 `dev.db`。

## 开发

开发流程、目录结构、新建项目的步骤和规范见 **[AGENTS.md](AGENTS.md)**（AI 编程助手和人都按它来）。
平台需求与设计决定见 [docs/requirements.md](docs/requirements.md)。

```bash
.venv/bin/python scripts/changes.py run   # 跑这次改动相关的测试
.venv/bin/python -m pytest -q          # 运行全部测试
scripts/wait_for_deploy.sh             # 开 PR 后等待合并进 main、Render 部署上线
```

## 技术栈

- 后端：Python（FastAPI），WebSocket 实时通信
- 前端：原生 JavaScript
- 数据库：PostgreSQL（Neon），保存账户、登录会话和项目存档
- 部署：Render，PR 合并进 `main` 后自动部署
- CI：GitHub Actions，每个 PR 自动跑测试；负责人本人的 PR 自动 approve 并合并，其他人的 PR 需负责人审核
