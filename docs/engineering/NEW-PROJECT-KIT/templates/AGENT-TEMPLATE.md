# AGENT.md

> {{项目名}} 的 AI Agent 上下文契约。所有 AI（Claude Code / Codex / Kimi / Hermes 等）与人共用。**本文件是唯一权威**，派生位置由脚本同步、不入版本库。

## Repo Hygiene

- GitHub only carries source code, docs, sanitized examples, and build scripts.
- Never commit or push real account data, cookies, browser profiles, fingerprints, proxy/IP pool data, logs, local databases, or other runtime artifacts.
- Do not include raw account identifiers, cookie values, proxy IPs, or local-only paths in commit messages, PR descriptions, screenshots, or copied debug output.

## Push Rules

- Before commit or push, run `git status --short`.
- If a runtime or sensitive file appears in Git tracking, remove it from the index with `git rm --cached <path>` and add or fix the ignore rule.
- If an example file is required for documentation or onboarding, create a sanitized template such as `*.example.*` instead of pushing real data.

**禁用命令**（一律不允许）：
- `git add -A` / `git add .`
- `git stash`
- `git reset --hard`
- `git checkout ./`
- `git clean`
- `git push --force` / `git push -f`
- `git commit --no-verify`

## Local-Only Data

以下必须在 `.gitignore` 内，严禁进版本库：

- `.env` / `*.env.local`
- `*.db` / `*.sqlite*` / `dump.rdb`
- `logs/` / `tmp/` / `tmp-runtime-data/`
- `_caches/` / `.cache/`
- `_appdata_*/` / `.local-share/`
- `dist/` / `dist-out/` / `build/`
- `node_modules/`
- `.venv/` / `venv/` / `env/`

**项目专属本地数据（按需增补）**：
- `{{本地数据目录 1}}/`
- `{{本地数据目录 2}}/`
- `{{本地数据目录 3}}/`

## Interface Border Rule（如适用）

- 视觉/接口约定：颜色、边框、间距必须有主题 token，不许硬编码。
- 新增约定按项目实际补充。

## AI Agent 上下文（可选）

如果项目使用特定 AI Agent（Hermes / Claude Code / 自定义 agent），在此声明预加载技能：

- 预加载技能路径：`{{技能路径}}`
- 派生位置由脚本同步、不入版本库：`{{派生路径 1}}` / `{{派生路径 2}}`

## Git Trailer（AI 参与记录）

AI 参与的 commit 必须带 `AI-Model:` trailer：

```
feat(scope): 简短描述

Fixes: #{{issue-number}}

AI-Model: {{model-name}}
```

## 变更记录

- v1.0（{{日期}}）：初版
