# Dev Lab

个人项目平台：一个网站、一个数据库、一套开发流程，承载多个项目（游戏、工具、AI agent……）。
首页是「应用商店」，每个项目挂在 `/apps/<slug>/` 下，账号全平台通用。

## 项目

| 项目 | 网址 | 说明 |
|---|---|---|
| ⚔️ 领主战争 | `/apps/lordwar/` | 多人实时策略游戏：随机地图、领地拓展、建筑与兵种、野怪、战争迷雾、攻城。需求见 [projects/lordwar/REQUIREMENTS.md](projects/lordwar/REQUIREMENTS.md) |

## 账户

- **游客**：浏览器里生成随机凭证作为身份，同一浏览器再来还是同一个人
- **用户名 + 密码**注册登录，可选绑定邮箱（需点验证链接）
- **第三方登录**：Google / Apple / 微信，配置了对应密钥才会显示

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
.venv/bin/python -m pytest -q          # 运行全部测试
scripts/wait_for_deploy.sh             # push 到 main 后等待 Render 部署上线
```

## 技术栈

- 后端：Python（FastAPI），WebSocket 实时通信
- 前端：原生 JavaScript
- 数据库：PostgreSQL（Neon），保存账户、登录会话和项目存档
- 部署：Render，push 到 `main` 自动部署
