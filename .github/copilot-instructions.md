# Copilot instructions

本项目的开发流程和规范写在仓库根目录的 **`AGENTS.md`**，请先阅读并遵守它。

最重要的几条（完整内容见 `AGENTS.md`）：
- 用中文和负责人交流。
- 改动后先运行 `.venv/bin/python -m pytest -q`，全部通过才能提交。
- 直接 push 到 `main`，然后运行 `scripts/wait_for_deploy.sh` 等待 Render 部署上线。
- 代码要兼容 Python 3.9；密钥只放 `.env` 或 Render 环境变量，绝不提交。
