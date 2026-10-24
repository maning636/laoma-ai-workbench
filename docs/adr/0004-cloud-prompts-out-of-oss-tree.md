# ADR-0004: 云端 prompt 正文移出开源树

- **状态**：已接受（补录）
- **日期**：2026-10-22
- **决策者**：工作组（B2 拍板）
- **证据分级**：【已验证】

---

## 背景

2026-10-22 开源边界拍板前，云端 AI 的 prompt 模板正文（用于对话、生图、文案生成的多套 prompt）位于 `cloud_service/_pro_assets/` 与部分模块的 `prompts.py` 中。开源准备时发现：

1. **核心资产暴露**：prompt 正文是产品核心资产，直接进开源仓等于开源了运营能力。
2. **AGPL 义务**：AGPL-3.0 要求「提供对应源码」，但「prompt 正文」是否属于「源码」存在解释空间。稳妥口径是明确划界。
3. **打包链路差异**：Pro 版安装包需要 prompt 正文，Community 版不需要。

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §4「B2」行、§8.7 A7
- `git show --stat 7dd9237`：删 `_pro_assets/prompts.py` 正文，OSS 版 `CLOUD_PROMPTS = {}` 为空
- `.gitignore:317` 排除 `_pro_assets/`

## 决策

**云端 prompt 正文全部移出开源树**：公开仓留空 stub，Pro 版打包时注入正文。

**具体落地**：
- `7dd9237`：B2 云端 prompt 正文移出开源树，OSS 版 `CLOUD_PROMPTS = {}`
- `.gitignore:317`：`cloud_service/_pro_assets/` 全部排除
- Pro 版打包链路：`desktop-electron/scripts/` 内注入 `_pro_assets/`（本地私有目录，不入版本控制）
- OSS 版运行时：`CLOUD_PROMPTS` 为空 dict，`cloud_prompt` flag 判为 `false`

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| prompt 正文公开 | 核心资产泄露，AGPL 义务虽可解释为「不属源码」，但公开后无法撤回 |
| 把 prompts.py 完全移出（不留 stub） | OSS 用户运行时 `import` 会直接失败；至少留空 stub 保 API 兼容 |
| prompt 正文放私有仓 fork | 增加 fork 管理成本；AGPL 义务要求同一仓库提供源码 |
| prompt 正文走云端下发（运行时拉取） | 依赖网络，且云端下发同样暴露给用户 |
| 混淆 prompt 正文进包 | 混淆只提高逆向门槛，不解决开源义务；且 Pro 版安装包已用 PyArmor |

## 代价

**收益**：
- 核心资产（prompt 正文）不落入开源树
- AGPL 义务履行清晰：源码全部在公开仓，资产在私有 Pro 打包链路
- OSS 用户与 Pro 用户运行同一份 client 代码，判档靠 flag

**代价**：
- Pro 打包链路复杂：需在打包期注入 `_pro_assets/`
- prompt 正文与 client 代码版本可能漂移（正文改后需重新打包才能生效）
- OSS 用户无法享受云端 AI 完整能力

**已知副作用**：
- `CLOUD_PROMPTS = {}` 是**已修复的边界**（见 A7 说明）；接手方**不要**去「移出 prompts.py」——那是按错误的记忆去改一个已经正确的边界
- 若将来把云端 AI 也纳入 OSS 版，需先做 prompt 开源策略讨论

## 未来复审触发条件

- 引入云端 AI 的第三方合作供应商，需共享 prompt
- 云端订阅商业化上线，OSS 版也需最小可用云端 AI
- prompt 正文版本控制成为瓶颈（需专用版本管理）

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §4「B2」、§8.7 A7
- `docs/feature-inventory-and-oss-boundary.md` — 开源边界
- `.gitignore:317`
- Commit: `7dd9237`
