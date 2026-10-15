# 计划编号口径说明（D 类 review）

> 目的：仓库里散落在 `_plan_productization_saas.md`、`docs/dev-reports/2026-10-13-project-handover.md`、`docs/dev-reports/2026-10-15-remaining-dev-worklist.md`、`_review_productization_v1.md` 等多份文档里的 **P0-P7 / A 类 / B 类 / C 类 / D 类** 编号容易混用。本文只做说明，**不改**任何历史文档编号（会丢信息）。

---

## 1. 三套编号的由来

| 编号族 | 出处 | 含义 | 生命周期 |
|---|---|---|---|
| **P0 – P7** | `_review_productization_v1.md`（初版产品化 review） | 首次系统性梳理出的 8 个优先级主题（路径 / preflight / Easel 快照 / Easel 自动更新 / 打包收口 / subprocess 改造 / E2E / CI 集成）。是**横向主题**，跨阶段。 | 2026-10-11 定型；不再新增。 |
| **A / B / C / D 类** | `_plan_productization_saas.md` §11、`2026-10-13-project-handover.md` | 按**时间 / 状态**切片的执行批：A 立即收尾（≤1 人日）、B 本地收尾（~8-10 人日）、C SaaS 化（~20-26 人日）、D 长期 review 杂项（~2-3 人日）。是**纵向批次**。 | 持续演化；A/B 完成后编号会自然消解，C 类会继续增长。 |
| **C1 – C21 / A1 – A3 / B1 – B8** | `_plan_productization_saas.md` §5-§11、`2026-10-13-project-handover.md` §2.2 | 每类下面的**具体任务编号**（C19 支付 / C20 云基础设施 / B7 反逆向 等）。 | 与父类生命周期一致。 |

**核心区分**：P* 是"问题清单"，A/B/C/D 类是"执行批次"，C*/B*/A* 是"批次下的工单"。同一件事可能在 P* 里出现一次，然后在 A/B/C 里再出现一次，编号不同但指向同一件事。

---

## 2. 对应关系（历史追溯）

| P* 主题 | 归属批次 | 说明 |
|---|---|---|
| **P0** 路径收口 | 已完（P0-P5 收官） | `paths.py` + `paths.json` + `/preflight` 已落地 |
| **P1** 配置层 | 已完 | `core/paths.py` fallback 链 |
| **P2** Easel 快照 | 已完 | `easel_update._backup_data_dir`（本次 D 类 review 升级为目录级） |
| **P3** Easel 自动更新 | 已完 | `easel_update.apply_update / rollback_update` 三层回滚 |
| **P4** 打包收口 | 已完 | `scripts/packaging/build-package.bat` / `supervisor.spec` / `.gitignore` / `PACKAGING.md` |
| **P5** subprocess 改造 | A 类（A1/A3） | `subprocess_safe.py` + 已迁 33/62，剩余 ~29 处由 A3 收口 |
| **P6** E2E 打包回归 | B 类（B5） | `scripts/tests/e2e_packaged_test.ps1` + `integration_test.py` |
| **P7** CI 集成 / 部署 | C 类（C21） | `deploy/` 尚未成型，本次未做 |

（来源：`_plan_productization_saas.md` 尾注 + `2026-10-13-project-handover.md` §2.2 表格）

---

## 3. D 类 · 长期 review 小项（本文档触发）

D 类共 8 项，来源 `docs/dev-reports/2026-10-15-remaining-dev-worklist.md` §5 与 `_plan_productization_saas.md` §11.4。**D 类不参与优先级排序**，属于"零散穿插、风险可控"的清单：

1. 6 模块前缀兼容层 `/api/v1/api/v1/` 观察期后移除（**只报告不移除**，风险高）
2. Easel `openclaw.json` 目录备份 → 已改为目录级
3. `openclaw@latest` pin 版本 → 阻塞在真实版本号未查得（见 handover §7）
4. `paths.json` 加入 `.gitignore` → 已加（`/data/paths.json`、`/paths.json`、`*.paths.json.tmp`）
5. health-check fast/full 分档 → 现有 `/system/health-check` 未分档，改动面大（`system/router.py` 1200+ 行），本次只报告方案
6. **本文档**：跨会话计划编号口径统一
7. `automation_worker` 日志统一到 `data/logs` → 已改（`worker.py` `_LOGS_DIR` 走 `core.paths.get_data_dir()`）
8. hermes `get_update_status` 回滚字段 → 已复核（`hermes_update.py:402-421`，字段齐全）

---

## 4. 使用约定（给后续 agent / 会话）

1. **新增任务先归到 P*（如果适用）**；再根据当前进度归入 A/B/C/D 类；最后编号为 `{类}{序号}`。
2. **不要跨文档改编号**。历史编号（C19、P5、A3 等）在旧文档里保持原样；引用时以本文档为准。
3. **P* 只增不改**；C 类可以继续增长到 C22、C23…；A/B 类完成后自然消失。
4. 交接文档里若同时出现 P* 和 C*，视为**同一任务**，优先以 C* 定位当前状态，P* 定位历史脉络。

---

*生成于 2026-10-16，D 类 review 交付物之一。不修改任何既有编号。*
