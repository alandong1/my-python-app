# my-python-app · 领主战争

一个浏览器里的多人实时策略游戏（原型）。Python FastAPI 服务器 + WebSocket 实时同步 + Canvas 前端。

## 玩法

- 每个玩家在随机生成的 48×48 地图上获得一块 3×3 的初始领地和主城
- 花金币**一格一格拓展**领地（只能拓展相邻格子）
- 在领地上**建造建筑**：金矿场（金矿脉）、伐木场（森林）、集市、兵营、铁匠铺、箭塔，最高 5 级
- 兵营训练**步兵 / 弓箭手 / 骑兵 / 投石车**（兵营等级解锁），铁匠铺研究**武器 / 护甲**
- 野外有**狼群、土匪、兽人部落**，地图中央有**远古巨龙**，击败可得资源
- **战争迷雾**：只能看到领地、主城、箭塔和部队附近的格子；探索过的区域会显示旧情报
- 部队走进敌方领地会占领地块，攻破敌方**主城**即可让对方出局
- 战斗用兰彻斯特平方律结算；丘陵、森林有防守加成；投石车攻城 ×3

## 账户系统

- **游客试玩**：浏览器 localStorage 里生成一串随机凭证作为身份，同一浏览器再来还是同一个人
- **用户名 + 密码**注册登录（密码用 bcrypt 哈希存储），可选绑定邮箱（需点验证链接）
- **第三方登录**：Google / Apple / 微信，配置了对应密钥才会显示；已登录用户可在「我的账号」里绑定
- 登录状态保存在 HttpOnly cookie 中，数据库只存会话 token 的哈希

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # 按需填写，全部留空也能运行
.venv/bin/uvicorn app.main:app --reload
```

打开 http://localhost:8000 ，多开几个浏览器窗口（或无痕窗口）就能模拟多个玩家。

`.env` 里没有 `DATABASE_URL` 时使用本地 SQLite 文件 `dev.db`；填上 Neon 的连接字符串就用 Neon。
没配置 SMTP 时，邮箱验证链接会打印在服务器日志里。

## 开发

开发流程和规范见 [AGENTS.md](AGENTS.md)（AI 编程助手和人都按它来），需求与设计决定见 [docs/requirements.md](docs/requirements.md)。

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # 运行测试
scripts/wait_for_deploy.sh             # push 到 main 后等待 Render 部署上线
```

## 操作

- 拖动地图平移，滚轮缩放，WASD / 方向键移动视角，H 回到主城
- 点击格子查看详情、建造、升级、拓展
- 选中己方部队后**右键**目标进军，**Shift+右键**派出一半；也可以用面板里的按钮

## 代码结构

- `app/config.py`：所有数值（建筑、兵种、野怪、视野……），调平衡改这里
- `app/game.py`：游戏逻辑（地图生成、战斗、迷雾、主循环）
- `app/main.py`：FastAPI 服务器、WebSocket、每 0.5 秒一次的 tick 循环
- `app/auth.py`：账户接口（游客、注册登录、邮箱、第三方登录回调）
- `app/oauth.py`：Google / Apple / 微信 OAuth
- `app/db.py`：数据库表结构；`app/settings.py`：环境变量配置
- `static/`：前端页面

## 技术栈

- 后端：Python（FastAPI）
- 数据库：PostgreSQL（Neon），保存账户、登录会话和游戏世界存档（每 30 秒及关闭前自动存档，重启后恢复）
- 部署：Render，从 GitHub 自动部署（启动命令 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`）
