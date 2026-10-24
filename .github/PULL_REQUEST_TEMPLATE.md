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

## 坑清单 / 已知问题

<!-- 
  这个 PR 引入了哪些"能跑但要注意"的东西？没有请写 N/A。
  常见类型：
    - 竞态 / 时序问题（例：先启动 worker 再启动 FastAPI，否则 X）
    - 环境差异（Windows / macOS / Linux 任一独有）
    - 临时 workaround（例：等待 upstream 修复 CVE-XXX，届时应移除）
    - 兼容性折衷（例：为兼容 A 场景放弃了 B 场景，理由：...）
  每一项请给一行"缓解措施"或"移除条件"，便于日后回收。
-->

- N/A

## 是否涉及已拍板决策（ADR 引用）

<!-- 
  如果本 PR 触及以下已拍板的设计决定，请在对应条上打勾并说明"如何遵守"。
  未拍板但需要拍板的决策请在下方新增条目并链接到讨论 Issue。
  当前已拍板清单（持续追加）：
    - ADR-001 抖音登录生产禁用 HTTP 逆向模式（见 prism_backend/AGENTS.md）
    - ADR-002 subprocess.run 走 subprocess_safe wrapper（除 allowlist）
    - ADR-003 requirements*.txt 与顶层 import 双向对齐（CI: deps-gate）
    - ADR-004 CI 硬门 / 软门分层（ci.yml 头部注释）
    - ADR-005 Security Scan 基线期全部软门（security.yml 头部注释）
-->

- [ ] ADR-001 抖音登录生产禁用 HTTP 逆向模式
- [ ] ADR-002 subprocess.run 走 subprocess_safe wrapper
- [ ] ADR-003 requirements*.txt 与顶层 import 双向对齐
- [ ] ADR-004 CI 硬门 / 软门分层
- [ ] ADR-005 Security Scan 基线期全部软门
- [ ] 其他 / 新拍板（在此新增）：

## 关联 Issue

Closes #<issue-id>

Related: #<other-issue>

## 文档更新

<!-- 涉及行为变更、配置变更、用户可见接口变更必须同步文档 -->

- [ ] README / CONTRIBUTING / SECURITY 已同步（如适用）
- [ ] `docs/dev-reports/` 或 `docs/architecture/` 已补一篇决策/复盘（如涉及架构或大改动）
- [ ] `.env.example` / `config/*.example` 已同步（如涉及配置字段新增）
- [ ] 本 PR 无需文档更新（说明理由：______）

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
