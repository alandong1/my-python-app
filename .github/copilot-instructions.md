# Copilot instructions

本项目的开发流程和规范写在仓库根目录的 **`AGENTS.md`**，请先阅读并遵守它。

最重要的几条（完整内容见 `AGENTS.md`）：
- 用中文和负责人交流。
- 这是多项目平台 Dev Lab：平台核心在 `app/`，各项目在 `projects/<slug>/`，项目之间不要互相 import。
- 需求有变化时，先更新需求文档（平台：`docs/requirements.md`；项目：`projects/<slug>/REQUIREMENTS.md`），再改代码。
- 改动时对照 `AGENTS.md` 的「改动时同步更新的文件」，把相关文件一起更新。
- 改动后先运行 `.venv/bin/python -m pytest -q`，全部通过才能提交。
- 直接 push 到 `main`，然后运行 `scripts/wait_for_deploy.sh` 等待 Render 部署上线。
- 代码要兼容 Python 3.9；密钥只放 `.env` 或 Render 环境变量，绝不提交。
