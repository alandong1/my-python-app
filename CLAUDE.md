# CLAUDE.md

项目规范和开发流程统一写在 AGENTS.md（所有 AI 工具共用），这里直接导入：

@AGENTS.md

## Claude Code 专用

- 负责人已明确授权：改动完成并测试通过后，**直接开 PR，不要询问**（详见 `AGENTS.md` 开发流程第 3 步）。开 PR 后订阅这个 PR 的动态（`subscribe_pr_activity`），不用问负责人要不要盯。
- 开 PR 之后，使用 `deploy` skill（`.claude/skills/deploy/SKILL.md`）等待合并、确认部署上线，再通知负责人刷新。
- 修改流程或规范时，改 `AGENTS.md`，不要改这里，避免两处内容不一致。
