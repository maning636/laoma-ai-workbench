<!--
感谢提交 PR！请先阅读 [CONTRIBUTING.md](../CONTRIBUTING.md)。
提交前请自查：CI 全绿 + 本地测试通过 + 关联 Issue。
-->

## 改动描述

<!-- 用 1-3 句话说明这个 PR 做了什么、为什么做 -->

- 

## 改动类型（可多选）

- [ ] feat 新功能
- [ ] fix 缺陷修复
- [ ] docs 文档
- [ ] refactor 重构（不改变外部行为）
- [ ] test 测试
- [ ] chore 构建 / 依赖 / 脚本
- [ ] ci CI 流程
- [ ] perf 性能
- [ ] breaking 破坏性变更（请说明）

## 涉及模块

- [ ] M1 文生图
- [ ] M2 智能体
- [ ] M3 积分
- [ ] M4 工作流
- [ ] M5 图片编辑器
- [ ] 平台适配器
- [ ] Persona / 浏览器运行时
- [ ] 代理 / IP 池
- [ ] 开发者工具中心（/tools）
- [ ] 前端 UI
- [ ] 后端 API
- [ ] Electron 桌面端
- [ ] Cloud Service
- [ ] 部署 / 打包
- [ ] 其他（请说明）

## 测试结果

请粘贴本地实际执行结果（不是勾选框）：

```bash
# 前端类型检查
$ cd prism_frontend && npx tsc --noEmit
# ✅ 通过 / ❌ 失败（贴出错误）

# 前端单元测试
$ cd prism_frontend && npx vitest run
# ✅ 通过 (xxx tests) / ❌ 失败

# 前端 lint
$ cd prism_frontend && npm run lint:all
# ✅ 通过 / ❌ 失败

# 后端自运行测试（如相关模块改动）
$ cd prism_backend && python tests/test_m1_ai_design.py
$ cd prism_backend && python tests/test_m2_agents.py
$ cd prism_backend && python tests/test_c17_subscription_tier.py
# ✅ 通过 (ALL TESTS PASSED) / ❌ 失败

# 后端 lint
$ python -m ruff check prism_backend/ --select E9,F63,F7,F82
# ✅ 通过 / ❌ 失败
```

> 说明：后端测试为**自运行脚本模式**（每个 `test_*.py` 有 `if __name__ == "__main__"`），直接 `python tests/test_xxx.py` 运行即可，末尾会打印 `ALL TESTS PASSED`。

## 截图 / 录屏

<!-- 如果是 UI 改动，请在此粘贴截图或 GIF；无 UI 改动写 N/A -->

N/A

## 关联 Issue

Closes #<issue-id>

Related: #<other-issue>

## Checklist

- [ ] 我已经在本地跑通 §4 测试（tsc / vitest / M1-M2-M3 自运行 / ruff / eslint）
- [ ] 代码符合 [CONTRIBUTING.md · 代码规范](../CONTRIBUTING.md#3-代码规范)（TS strict / Python PEP8）
- [ ] Commit 遵循 Conventional Commits（`feat(scope): xxx` / `fix(scope): xxx` / ...）
- [ ] 已更新相关文档（README / docs/dev-reports / .env.example）
- [ ] UI 改动附了截图 / GIF
- [ ] 新增 / 修改逻辑配有对应测试
- [ ] 无硬编码 API key / token / 密码，无遗留调试代码（console.log / print / TODO 已清理）
- [ ] 未引入新的 secret 或泄露本地凭据
- [ ] 本 PR 未触及 Pro 云端实现（prompt / key / 数据服务），仅涉及 Community 层

---

### Reviewer 提示

- 涉及 M1 / M2 / M3 请重点关注后端自运行测试是否覆盖新分支
- 涉及 UI 请附上浏览器截图 + 深色 / 浅色主题确认
- 涉及配置请同步更新 `.env.example` 与 `prism_backend/config/llm_config.toml.example`
