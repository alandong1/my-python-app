# Copilot instructions

本项目的开发流程和规范写在仓库根目录的 **`AGENTS.md`**，请先阅读并遵守它。

最重要的几条（完整内容见 `AGENTS.md`）：
- 用中文和负责人交流。
- 这是多项目平台 Dev Lab：平台核心在 `app/`，各项目在 `projects/<slug>/`，项目之间不要互相 import。
- 需求有变化时，先更新需求文档（平台：`docs/requirements.md`；项目：`projects/<slug>/REQUIREMENTS.md`），再改代码。
- 改动时对照 `AGENTS.md` 的「改动时同步更新的文件」，把相关文件一起更新。
- 改动后先运行 `.venv/bin/python scripts/changes.py run`（按改动选测试），全部通过才能提交。
- 一个 PR 只改一个项目（`projects/<slug>/`），或者只改平台；新建项目不用在任何共享文件里登记。
- 不要直接 push 到 `main`：在自己的分支上提交，开 PR 到 `main`（负责人本人的 PR 测试通过后自动合并，其他人的 PR 需负责人审核），然后运行 `scripts/wait_for_deploy.sh` 等待合并和部署上线。负责人已授权：测试通过后直接开 PR，不用询问。上线后在最后的回复里列出可以直接点开的链接（项目页面、PR）。同一个 PR 最多自己修 3 轮；PR 带 `needs-human` 标签时停止 push，等负责人处理。
- 新建项目时按 `AGENTS.md`「技术选型」根据需求选语言和架构；用默认技术栈以外的技术前先问负责人，并把理由写进项目的 `REQUIREMENTS.md`。
- 代码要兼容 Python 3.9；密钥只放 `.env` 或 Render 环境变量，绝不提交。
