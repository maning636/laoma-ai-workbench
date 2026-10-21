# Vendor 归属与来源

> Prism-Fusion（老马AI工作台）内置/参考的上游开源项目清单。
> 每一项都标注：来源仓库、归属方、许可证、抽取版本、本地改动范围、同步方式。
> 项目代码许可证（AGPL-3.0）见仓库根 [LICENSE](../LICENSE) 与 [NOTICE.txt](../NOTICE.txt)。

---

## 1. Easel —— 内容创作工作台参考源

| 项目 | 内容 |
| --- | --- |
| **上游仓库** | https://github.com/ZJU-REAL/Easel |
| **归属方** | 浙江大学 ZJU-REAL Lab（Zhejiang University, REAL Lab） |
| **上游许可证** | Apache License 2.0 |
| **本项目抽取路径** | `tools/easel-ref/app.py`（约 133 KB，54 条路由，含 SSE 流式与 skills/profile/persona/trends/ideas/schedule/outputs/drafts 等模块） |
| **抽取时间** | 2026-09-15 |
| **抽取版本** | Easel v0.2.1 附近（运行时挂载的 Easel 仓库 git tag 未硬编码确认；交接文档记 113 个 skills，与 v0.2.1 主干指纹一致） |

### 本地改动范围

- **未直接 vendor 完整 Easel**：Prism-Fusion 没有把 Easel 整包复制进仓库，也没有通过 git submodule 或 iframe 嵌入 Easel 前端。`tools/easel-ref/app.py` 只作为 **API 契约参考副本**，不参与运行。
- **已复刻的 API 层**（依据 `tools/easel-ref/app.py` 契约移植）：
  - `outputs`（内容库列表、预览、编辑、导出）
  - `drafts`（草稿箱、发布流程）
  - `skills`（技能库扫描与刷新）
  - `persona` / `profile`（多画像管理、profile 构建）
  - `schedule`（发布排程）
  - `ideas`（选题灵感）
  - `trends`（热点趋势抓取）
  - `profile`（用户画像与 baseline）
- **未移植的 API/模块（架构冲突，铁律 3 明令禁引 OpenClaw）**：
  - **对话直连 OpenClaw 网关提速**（v0.2.1）——依赖 OpenClaw 18789 端口与 question RPC；
  - **workspace 路径统一向 OpenClaw 问 `workspaceDir`**（v0.2.1）——依赖 OpenClaw 会话目录注册；
  - **`gateway_questions` 桥接**（SSE `question` 事件、`question.resolve` RPC）——依赖 OpenClaw 网关内建 pending-question 队列。

  Prism-Fusion 保留 Hermes 路线做对话与 agent，不做 OpenClaw 桥接。

### 同步方式

- 若需更新参考源，从 Easel 官方 releases 拉取对应版本的 `web/app.py`，覆盖 `tools/easel-ref/app.py`；同步时更新本文件与 `tools/easel-ref/README.md` 的"抽取版本 / 抽取时间"两行。
- 建议同步节奏：仅在移植新 API 前按需同步，不主动追 v0.3.x 等未对齐主干；避免每次同步触发无谓的移植面扩张。
- 若上游修改 MIT/Apache-2.0 归属或引入非 Apache-2.0 组件，先评估再同步；不接受未知许可证代码进入 `tools/easel-ref/`。

### 致谢

感谢浙江大学 ZJU-REAL Lab 团队开源 Easel，为本项目提供可参考的 API 契约与技能库设计；相关代码以 Apache License 2.0 分发，遵循其保留版权声明与许可证文本的要求。

---

## 其他上游（详见 [NOTICE.txt](../NOTICE.txt)）

| 项目 | 许可证 | 说明 |
| --- | --- | --- |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | MIT | CLI 自动发布基础 |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | Apache-2.0 | 抖音 / TikTok 解析与数据 |
| [HermesAgent](https://github.com/nousresearch/hermes-agent) | MIT | 本地 AI Agent 运行时 |
| [Persona Studio](https://github.com/TechQaiser/persona-studio) | MIT | 浏览器身份 / 指纹 / Profile 层 |
