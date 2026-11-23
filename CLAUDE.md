# CLAUDE.md

项目规范和开发流程统一写在 AGENTS.md（所有 AI 工具共用），这里直接导入：

@AGENTS.md

## Claude Code 专用

- push 到 `main` 之后，使用 `deploy` skill（`.claude/skills/deploy/SKILL.md`）确认部署上线，再通知负责人刷新。
- 修改流程或规范时，改 `AGENTS.md`，不要改这里，避免两处内容不一致。
