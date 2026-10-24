# 新项目启动检查单

> 从 `NEW-PROJECT-KIT/` 复制模板后，逐项勾选。**全部勾选后打第一个 tag `v0.1.0`。**

## 阶段 A · 仓库初始化（1–5）

- [ ] **1. 仓库初始化**：`git init`，LICENSE 文件（AGPL-3.0 / MIT / Apache-2.0）入库
- [ ] **2. 五件套齐备**：`README.md` / `CONTRIBUTING.md` / `SECURITY.md` / `NOTICE.txt` / `LICENSE`
- [ ] **3. `AGENT.md` 就位**：含 Repo Hygiene / Push Rules / Local-Only Data 三段
- [ ] **4. `.gitignore` 覆盖运行时目录**：`git status --short` 实测干净（无运行时数据入库）
- [ ] **5. 目录结构清晰**：`src/`（或 `backend/` / `frontend/`）、`tests/`、`docs/`、`scripts/`、`.github/` 就位

## 阶段 B · 依赖与工具链（6–10）

- [ ] **6. 依赖声明文件齐备**：`requirements.txt` + `requirements-dev.txt`（Python）；`package.json` + `package-lock.json`（Node）
- [ ] **7. 依赖声明闸门**：`scripts/tests/check_requirements_cover_imports.py` 就位
- [ ] **8. 依赖闸门反向自测**：`python scripts/tests/check_requirements_cover_imports.py --self-test` 通过
- [ ] **9. 前端工具链**：ESLint 配置 + `npm run lint:all` 脚本 + TypeScript `--noEmit`
- [ ] **10. Python 工具链**：ruff 配置 + `ruff check --select E9,F63,F7,F82` 通过

## 阶段 C · 测试体系（11–15）

- [ ] **11. 后端单测**：至少 1 个 pytest 用例，`pytest tests/ -q` 通过
- [ ] **12. 前端单测**：至少 1 个 vitest 用例，`npx vitest run` 通过
- [ ] **13. TDD 红→绿证据**：新增功能先写失败测试，再修复转绿
- [ ] **14. CI 全绿**：push 到远端后 GitHub Actions 全绿
- [ ] **15. `lint` 硬门**：CI 中 ruff + ESLint 全量检查通过

## 阶段 D · CI 硬门（16–20）

- [ ] **16. `test` 硬门**：CI 中 pytest 通过（不加 `-x`，一次全报）
- [ ] **17. `deps-gate` 硬门**：CI 中依赖闸门 + 反向自测通过
- [ ] **18. `security.yml` 硬门**：gitleaks + 依赖审计（safety / pip-audit / npm audit）通过
- [ ] **19. 软门就位**：E2E 打包烟测设 `continue-on-error: true`，仅在 `workflow_dispatch` 触发
- [ ] **20. 版本与发布守卫**：`release.yml` 含体积下限守卫 + 产物校验 + 已发布防覆盖

## 阶段 E · 版本与发布（21–23）

- [ ] **21. 版本号单一真源**：单一文件维护 version（如 `package.json` 或 `pyproject.toml`），tag 与资产名一致
- [ ] **22. `CHANGELOG.md` 首条**：`## [0.1.0] - <date>`，事实可溯源到 commit
- [ ] **23. `release.yml` 就位**：tag 触发 → 打包 → 校验 → GitHub Release

## 阶段 F · 知识管理（24–27）

- [ ] **24. 决策台账**：`docs/architecture/decisions/0001-*.md` 首条 ADR，含「为什么 + 否掉了什么 + 代价」
- [ ] **25. 坑清单**：`docs/handover/PROJECT-HANDOVER.md` §8 建骨架，每条含「现象 + 根因 + 修法」
- [ ] **26. dev-reports**：`docs/dev-reports/` 建首份开发报告
- [ ] **27. 验收表三件套**：`scripts/docs/` 下 build / read / roundtrip 三件套就位

## 阶段 G · 安全与合规（28–30）

- [ ] **28. Secret 扫描**：`.gitleaksignore` 白名单就位；CI gitleaks 通过
- [ ] **29. 凭据不进库**：`.env.example` 就位，真实 `.env` 在 `.gitignore` 内
- [ ] **30. 署名与许可证**：`LICENSE` / `NOTICE.txt` / `vendor/VENDOR.md` 齐备，第三方组件归属明确

---

## 打第一个 tag 前最后检查

- [ ] 全部 30 项已勾选
- [ ] 本地 `git status --short` 干净
- [ ] 本地 `git log --oneline -5` 无异常 commit
- [ ] CI 全绿（无硬门失败）
- [ ] 版本号单一真源确认一致
- [ ] `CHANGELOG.md` 已含 `0.1.0` 条目
- [ ] `release.yml` 本地 dry-run 通过

**通过后执行**：

```bash
git tag v0.1.0
git push origin main
git push origin v0.1.0
```
