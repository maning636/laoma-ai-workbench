# AI 参与记录机制

> 本文档定义本项目 AI 参与代码提交的可审计规范。适用范围：`Prism-Fusion` 主仓库及所有子目录（`prism_backend/` / `prism_frontend/` / `cloud_service/` / `desktop-electron/` / `docs/` 等）。

---

## 1 背景

`Prism-Fusion` 自 2026-10-13 项目启动起，AI Agent（Kimi Code / HermesAgent / Claude Code / Codex）参与了**每一批次**的核心开发工作——从底座搭建、五模块复刻、SaaS 化、注册码体系、CI 全链路、开源发布到收官冲刺。**没有一条提交是「纯人类独立完成」的**，多数提交由 AI 主导实施、人类审阅拍板。

传统 Git 提交记录无法区分「人写的」「AI 写的」「人机协作的」，接手方无从判断：

- 某个模块的质量基线由谁维护
- 代码风格偏向人类还是 AI
- Bug 复现时是否要提示 AI 参与
- 合规审计时如何界定 AI 参与比例

本文档定义**向前兼容的 Git 原生规范**，让「AI 参与」这一属性可被 `git interpret-trailers` 审计。

## 2 Git Trailer 规范

### 2.1 格式

**AI 参与的提交，message 末行（或末段）追加 trailer**：

```
AI-Model: <模型名>
```

示例（完整 commit message）：

```
feat(providers): 模型供应商注册表——CRUD/测试连接/拉模型/应用到通道（后端）

- 新增 providers 表
- 前端设置页 OpenRouter 风格
- 通道软关联不迁移旧配置

AI-Model: Kimi-K2
```

或人机协作：

```
fix(ci): 修后端 pytest 陈旧断言/陈旧接口，软门转硬门

AI-Model: Claude-Sonnet-4
Human-Review: maning636
```

### 2.2 模型名取值

使用**官方模型短名**，不要写内部代号：

| 场景 | 建议写法 |
|---|---|
| Kimi Code 主导 | `AI-Model: Kimi-K2` |
| Claude Code 主导 | `AI-Model: Claude-Sonnet-4` |
| Codex 主导 | `AI-Model: GPT-4o` 或 `AI-Model: GPT-5` |
| HermesAgent 主导 | `AI-Model: HermesAgent` |
| 多模型协作 | 每行一个 trailer，或末行写 `AI-Model: Kimi-K2, Claude-Sonnet-4` |

### 2.3 什么时候必须写 trailer

- **AI 主导实施**（AI 写主体代码 / 文档）
- **AI 大幅修改**（>30% 代码由 AI 生成或改写）
- **AI 主导决策记录**（ADR、SOP、报告等文档）

### 2.4 什么时候不需要

- 人类手写 <30% 代码的琐碎修改（如 typo、格式化）
- 纯依赖版本升级（`package.json` / `requirements.txt` 版本数字变更）
- AI 仅做审阅、写文档字符串，无代码产出

## 3 审计方式

Git 原生支持 trailer 审计（`git interpret-trailers`）：

```bash
# 列出所有 AI 参与的提交
git log --grep="AI-Model:" --oneline

# 统计各模型参与次数
git log --grep="AI-Model:" --pretty=format:"%b" | grep "^AI-Model:" | sort | uniq -c | sort -rn

# 按日期统计 AI 参与提交量
git log --grep="AI-Model:" --pretty=format:"%ad" --date=format:"%Y-%m-%d" | sort | uniq -c
```

## 4 本项目 AI 参与里程碑表

> 数据基于 `git log --since="2026-10-13" --until="2026-10-25" --pretty=format:"%ad %h"` 统计，2026-10-13 至 2026-10-24 共 **150 个提交**。

| 阶段 | 日期 | 提交量 | 关键产出 | 主导角色 |
|:---:|:---:|:---:|---|:---:|
| 阶段 A · 底座与商业化骨架 | 10-13 ~ 10-16 | 34 commits | 品牌切换（PRISM_→LAOMA_）、cloud_service 云端服务、客户端双通道、CORS、支付对接（后删）、部署产物 | AI 主导 + 人类拍板 |
| 阶段 B · 五模块复刻与开源准备 | 10-18 ~ 10-20 | 5 commits | 5 模块复刻（M1 AI 生图 / M2 智能体训练 / M3 积分账本 / M4 场景向导 / M5 图片编辑器）、GitHub 开源准备、Community 打包 | AI 主导 |
| 阶段 C · 产品化收尾 + SaaS 化 | 10-21 ~ 10-22 | 42 commits | 打通 10 条断链、注册码模块（B1）、云端 prompt 移出开源树（B2）、砍平台支付、D4 只读守卫、1.1.1–1.1.3 三版 | AI 主导 + 人类拍板 |
| 阶段 D · 单一客户端 + 开源发布 | 10-23 | 30 commits | 合并单一客户端（1.1.4）、1.1.5 客户端三处真缺陷修复、CI 从软门全改硬门、开源发布、P7 三态、D1-D5 追认、备份 round18 | AI 主导 + 人类拍板 |
| 收官冲刺 | 10-24 | 39 commits | L1-1/L1-2 数据层收编、L2-1/L2-2/L2-3 数据回收链路、L3-1/L3-2 孤岛收编、供应商注册表、包体瘦身、CI 全链路发版、超时封装、工程手册 + 新项目快速启动包 | AI 主导 |

**总计**：150 个提交，AI 参与率 **100%**（每一提交均有 AI 参与；具体 trailer 待历史回填）。

### 4.1 关键量化指标

- **代码量**：约 1439 个跟踪文件（`git ls-files | wc -l`）
- **PRISM 后端 Python**：562 个 py 文件
- **前端 TS/TSX**：302 个 ts/tsx 文件
- **云端 Python**：38 个 py 文件
- **桌面 Electron**：约 1958 个 py 文件（PyInstaller 编译产物计入）
- **文档**：`docs/dev-reports/` 43 份 + `docs/` 70 份 md
- **CI 硬门**：8 硬门全绿
- **发布版本**：1.1.1 → 1.1.5（5 个正式版本）+ 计划 1.1.6
- **开源状态**：AGPL-3.0，`maning636/laoma-ai-workbench`，Release `v1.1.5`
- **安装包体积**：639,437,816 B（约 610 MiB）

### 4.2 历史 trailer 回填计划

- **过去 150 个提交**：**不回填**（Git 原生规范应向前兼容，历史保持原状）
- **本项目新提交**：从 2026-10-24 起执行 trailer 规范
- **补录 ADR**：本次 `docs(adr): 12 项关键决策补录 ADR` commit 需带 `AI-Model: Kimi-K2` trailer

## 5 与 AGENT.md 的关系

- 根目录 `AGENT.md` 末尾的「AI 参与记录」小节指向本文档
- `prism_backend/AGENTS.md` 的抖音 HTTP 禁令不冲突：AI 参与记录是元数据，不改变代码禁令

## 6 参考

- Git 官方文档：`git interpret-trailers`、`git notes`
- `AGENT.md` — 项目 AI Agent 上下文与规范
- `docs/engineering/ENGINEERING-PLAYBOOK.md` — 工程体系总纲
- 原始数据：`git log --since="2026-10-13" --until="2026-10-25"`
