# NEW-PROJECT-KIT · 新项目快速启动包

> 从 `Prism-Fusion` 工程手册抽象出的**可复制模板包**。复制后把 `{{项目名}}` 全部替换成你的项目名，就能得到一个「有工程护栏」的起点。

## 目录结构

```
NEW-PROJECT-KIT/
├── README.md                              ← 本文件（使用说明）
├── templates/
│   ├── ci-template.yml                    ← 精简版硬门 CI（复制为 .github/workflows/ci.yml）
│   ├── security-template.yml              ← 安全扫描骨架（复制为 .github/workflows/security.yml）
│   ├── AGENT-TEMPLATE.md                  ← AGENTS.md 骨架（复制为 AGENT.md）
│   ├── ADR-TEMPLATE.md                    ← 单条 ADR 模板（复制到 docs/architecture/decisions/）
│   └── PULL_REQUEST_TEMPLATE.md           ← PR 模板（复制为 .github/pull_request_template.md）
└── checklists/
    └── new-project-checklist.md           ← 30 项启动检查单
```

## 复制步骤（10 分钟内完成）

1. **复制模板到目标位置**：
   ```bash
   # 在新项目根目录执行
   cp docs/engineering/NEW-PROJECT-KIT/templates/ci-template.yml        .github/workflows/ci.yml
   cp docs/engineering/NEW-PROJECT-KIT/templates/security-template.yml  .github/workflows/security.yml
   cp docs/engineering/NEW-PROJECT-KIT/templates/AGENT-TEMPLATE.md      AGENT.md
   cp docs/engineering/NEW-PROJECT-KIT/templates/PULL_REQUEST_TEMPLATE.md .github/pull_request_template.md
   mkdir -p docs/architecture/decisions docs/handover docs/dev-reports scripts/docs
   cp docs/engineering/NEW-PROJECT-KIT/templates/ADR-TEMPLATE.md        docs/architecture/decisions/0001-template.md
   cp docs/engineering/NEW-PROJECT-KIT/checklists/new-project-checklist.md docs/handover/NEW-PROJECT-CHECKLIST.md
   ```

2. **替换占位符**：所有模板里的 `{{项目名}}` / `{{owner}}` / `{{技术栈}}` 全部替换成你的项目实际值。用 `grep -r "{{"` 检查是否遗漏。

3. **补齐依赖声明**：
   - `requirements.txt` / `requirements-dev.txt`（Python）
   - `package.json` / `package-lock.json`（Node）

4. **补齐最小测试**：
   - 1 个后端单测（如 `tests/test_health.py`）
   - 1 个前端单测（如 `src/__tests__/app.test.tsx`）

5. **补齐依赖声明闸门**：从 `scripts/tests/check_requirements_cover_imports.py` 复制一份，或者用等价工具。

6. **首个 CI 怎么点绿**（见 §下方）：
   - 本地先跑：`pytest tests/` + `npm run lint` + `npx tsc --noEmit` + 依赖闸门脚本
   - push 到远端 → 看 GitHub Actions
   - 若某个 gate 失败：先看是否是真缺陷；否则调整该 gate 的**范围**（如 ruff 最小规则集），**别删掉硬门**

7. **补 CHANGELOG**：`CHANGELOG.md` 里写首条 `## [0.1.0] - <date>`。

8. **补齐决策台账**：把 `ADR-TEMPLATE.md` 复制一份，填第一条真实决策（哪怕是「协议选 AGPL-3.0」）。

9. **首次发版**：本地全绿 → `git tag v0.1.0` → `git push origin v0.1.0` → 看 release.yml 是否跑通。

10. **勾选检查单**：`docs/handover/NEW-PROJECT-CHECKLIST.md` 逐项打勾，全部打勾即完成「工程护栏就位」。

## 首个 CI 点绿的 5 步

1. **本地跑 pytest 单测**（最快反馈）：
   ```bash
   pytest tests/ -q
   ```

2. **本地跑 lint**：
   ```bash
   ruff check . --select E9,F63,F7,F82
   npx eslint src/
   npx tsc --noEmit
   ```

3. **本地跑依赖闸门**：
   ```bash
   python scripts/tests/check_requirements_cover_imports.py
   python scripts/tests/check_requirements_cover_imports.py --self-test
   ```

4. **push 到远端**，看 GitHub Actions。

5. **看 CI 结果**：
   - 全绿 → 打 tag `v0.1.0`，跑 release.yml。
   - 有红 → 定位失败 gate，**别删 gate**，改代码或改 gate 范围。若某个 gate 是假警报（误报），先降规则集的严格度，**不要 skip 整个 job**。

## 与本工程手册的关系

- 本 KIT 只是「模板」；机制与决策的完整推理见 `docs/engineering/ENGINEERING-PLAYBOOK.md`。
- 遇到具体问题时先查手册（如「依赖闸门为什么必须反向自测」见手册 §2.2 与 §5.1）。
- 遇到本项目**具体**踩坑（如「Node 22 硬性下限」），见 `docs/handover/PROJECT-HANDOVER.md` §8。

## 版本

- v1.0（2026-10-24）：初版，与 Prism-Fusion HEAD `c24a11d` 对齐。
