# LaomaAI-Fusion 各 Phase 验证措施

> 配套 `PLAN_next_steps.md` 使用
> 验证分层：**单元** → **集成** → **E2E/冒烟** → **人工验收**
> 测试目录：`prism_backend/tests/`，命名 `test_{phase}_{module}.py`
> 前端测试：`prism_frontend/` 下使用 Vitest/Jest
> 现有测试基础：`prism_backend/tests/` 已有 20+ 测试文件，`fastapi_app/tests/` 有 conftest.py 夹具

---

## Phase 0：基础设施补齐

### 0.1 发布回执结构化

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | `PublishReceipt` schema 字段完整性：task_id/status/platform_post_id/published_at 必填；error_code/retryable/requires_human_action 条件必填 | 构造合法/非法数据，验证 422 |
| 单元 | `build_receipt()` 各状态组合（succeeded / failed_retryable / failed_final） | mock 输入，断言输出 JSON |
| 集成 | 发布成功 → 回执写入 DB（`publish_receipts` 表）含完整字段 | TestClient `POST /publish/single` → 轮询 `GET /receipts/{task_id}` |
| 集成 | 发布失败 → `error_code` + `retryable` 正确填充，工件路径非空 | 注入失败（无效 Cookie）断言回执 |
| 质量门禁 | 所有上传器返回 `PublishReceipt` 类型，禁止裸 dict 透传 | `uploader/base_video.py` CI job |

**验收标准**：`GET /api/v1/receipts/{task_id}` 返回 200 + 完整 JSON（0.1 定义全部字段）。
**验收结果**：✅ 2026-10-24 通过（20 项验收表组 B，docs/handover/SPRINT-ACCEPTANCE-R1R2.md）；实现盘点发现 receipts.py/task_state_machine.py 已有基础，实际为补缺而非新建。

---

### 0.2 幂等任务状态机

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 状态枚举完整性：9 个状态值全部可实例化 | 遍历 `TaskStatus` 枚举，断言值集合 |
| 单元 | 状态转换合法性矩阵：每条合法路径通过、非法路径拒绝 `InvalidTransition` | 穷举所有转换对 |
| 单元 | 幂等键格式：`campaign:{cmp}:variant:{v}:account:{acc}` 稳定 | 相同输入 → 相同 key |
| 单元 | `failed_retryable → running` 重入：task_id 不变、attempt 递增 | 构造重试任务 |
| 集成 | 端到端状态推进：创建 → 审批 → 排期 → 执行 → 完成 | 每步断言状态 |
| 集成 | 并发创建相同任务：返回同一 task_id，不重复创建 | 并发 `POST /tasks` 断言 id 相等 |
| 回归 | 旧状态名映射：`processing` 等旧名自动映射到新枚举 | 断言映射正确 |

**验收标准**：状态转换矩阵测试 100% 通过；幂等键相同两次请求不创建重复任务。
**验收结果**：✅ 2026-10-24 通过（20 项验收表组 B，docs/handover/SPRINT-ACCEPTANCE-R1R2.md）；实现盘点发现 receipts.py/task_state_machine.py 已有基础，实际为补缺而非新建。

---

### 0.3 任务监控与告警

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 告警触发条件：`failed_final` 且无重试 → 触发告警 | mock 任务状态断言 |
| 单元 | 告警 payload：task_id/platform/account/error_code/diagnostic_path/timestamp | 断言字段 |
| 集成 | Webhook 告警：配置企微/钉钉地址 → 失败 → 收到 POST | aiohttp mock 接收 |
| 集成 | 重试不告警：`failed_retryable` → 仅记录重试事件 | 断言重试计数递增 |
| E2E | 监控面板 `GET /api/v1/tasks/monitor` 返回实时状态 | 启动后端创建任务查询 |
| 回归 | 已有看板 API 返回格式不变 | 断言原有 API 兼容 |

**验收标准**：mock webhook 收到失败通知（含回执字段）；监控面板实时状态。

---

### 0.4 账号健康监控

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 健康状态枚举：`valid/warning/invalid/unknown` | 遍历断言 |
| 单元 | Cookie 过期预警：`last_checked` 超阈值 → 降级 `warning` | mock 时间断言 |
| 集成 | `POST /accounts/{id}/check` → 返回 `valid/invalid` | 每平台一个用例 |
| 集成 | 检查后写入 `account_health_snapshots` 表 | 查询 DB 断言 |
| 集成 | `POST /accounts/check-all` 返回所有账号状态 | 断言数组含 health_status |
| E2E | 前端账号页状态图标（绿/黄/红） | Playwright 快照 |

**验收标准**：`check-all` 返回全部账号状态；前端正确渲染。

---

## Phase 1：平台字段补全

### 1.1 抖音商品挂载修复

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | 修复后通过「标记万物」路径成功挂载（真实浏览器） | 真实账号，断言页面出现商品名 |
| 单元 | `PLATFORM_SETTINGS_KEY_BY_CODE` 映射：抖音 → `"douyin"` | 断言字典 |
| 集成 | `handle_single_publish` 解包 `platform_settings.douyin` → 上传器 | mock 上传器断言参数 |
| 冒烟 | preview_only=True 全流程，日志含「标记万物」 | 运行 `douyin_preview` |

**验收标准**：preview_only 中商品挂载日志显示「标记万物」流程成功。

---

### 1.2-1.5 快手/小红书/B站/视频号字段补全

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 各平台 `upload()` 新参数有默认值 | 不传新参数不报 TypeError |
| 单元 | `platform_settings` 解包：5 平台 code → 对应 key 正确 | `test_platform_settings_unpack.py` |
| 集成 | `handle_single_publish` 字段透传：5 平台各断言收到正确字段 | mock 各上传器 |
| 冒烟 | 各平台 preview_only=True 冒烟 | 每平台各运行一次 |
| 集成 | 空 platform_settings 不阻断：默认值执行 | 不传 platform_settings 断言正常 |

**验收标准**：5 平台 preview_only 冒烟通过；空 platform_settings 不崩溃。

---

### 1.6 各平台登录态检查

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | `POST /accounts/check-all` 覆盖 5 平台 | 返回数组含 platform/health_status |
| 单元 | Cookie 过期检测：解析过期时间字段 | 构造过期 cookie 断言 `invalid` |
| 集成 | 检查后写入 `account_health_snapshots` | 查询 DB 断言 |
| E2E | 前端账号页状态刷新 | Playwright 断言图标变化 |

**验收标准**：5 平台检查后前端显示正确状态；DB 有快照记录。

---

## Phase 2：诊断与修复体系

### 2.1 选择器版本化配置

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | JSON schema 校验：`config/selectors/douyin_upload.v1.json` | 解析断言必填字段 |
| 单元 | `load_selectors(platform, version)` 返回正确字典 | 读取 JSON 断言结构 |
| 单元 | 灰度策略：按 account_id 返回不同版本 | 断言 A→v1 B→v2 |
| 集成 | 上传器引用版本化选择器 | 运行（mock 浏览器）断言来自 JSON |
| 回归 | 回滚：v2→v1 后选择器恢复 | 修改版本断言值恢复 |
| 集成 | 文件缺失降级：回退硬编码默认值 | 删除文件断言不崩 |

**验收标准**：JSON 格式校验通过；加载/回滚/降级测试全部通过。

---

### 2.2 诊断工件采集

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 工件结构：screenshot/dom/url/stack/timestamp | 构造断言字段 |
| 单元 | 脱敏：Cookie/Token/密码 → `***` | 构造含敏感信息 DOM 断言脱敏 |
| 集成 | 失败自动采集：`failed_final` → `artifacts/{task_id}/` 有文件 | 注入失败断言文件存在 |
| 集成 | 工件路径关联回执：`artifact_paths` 指向实际文件 | `os.path.exists` |
| 集成 | 清理策略：超 N 天自动清理 | mock 时间构造旧工件 |
| 冒烟 | 截图非空：PNG >1KB | 断言文件大小 |

**验收标准**：失败任务自动产出工件；回执 artifact_paths 指向实际文件；脱敏不含敏感信息。

---

### 2.3 Computer Use Repair Lab

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | 沙箱启动 `POST /diagnostics/repair-sandbox` → session_id | 断言 200 + id |
| 集成 | 修复候选生成：提交失败任务 → 返回候选列表 | mock CU API 断言候选结构 |
| 集成 | 审核流程：候选 → 审核队列 | 断言队列有记录 |
| 集成 | 回归验证：审核通过 → 回归测试 → 选择器更新 | 模拟回归断言结果 |
| 集成 | 选择器配置更新：`config/selectors/` 下出现新 JSON | 断言文件存在 |
| 单元 | `RepairProposal` schema：selector/rationale/evidence/approver/version | 断言字段 |
| 回归 | 禁止行为：CU 不操作生产账号 | 断言用测试账号/沙箱 |
| 冒烟 | 端到端：失败→诊断→候选→审核→回归→版本化 | 完整脚本 |

**验收标准**：端到端修复流程至少 1 次通过；禁止行为测试全部通过。

---

## Phase 3：AI 内容编排

### 3.1 内容版本管理

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | `ContentVariant` schema：id/platform/title/body/tags/cover/metadata/version | 断言字段 |
| 单元 | 版本递增：同素材多版本 → version 递增 | 构造 3 版本断言 1/2/3 |
| 单元 | 平台适配：5 平台各符合规则（标题长度/标签数/格式） | 断言各平台合规 |
| 集成 | `POST /content-variants/` → `GET /{id}/versions` | 断言 200 + 列表 |
| 集成 | 版本激活：`POST /{id}/activate/{version}` | 断言 GET 返回该版本 |
| 集成 | Easel 产物 → ContentVariant 自动转换 | 断言解析正确 |
| 冒烟 | 前端版本页面：多版本列表可切换 | Playwright 断言 |

**验收标准**：5 平台各生成 1 版本；版本切换 API 正确；平台规则约束通过。

---

### 3.2 品牌与合规管理

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 品牌配置 schema：voice/prohibited_words/rules/guidelines | 断言字段 |
| 单元 | 禁用词检测：含禁用词 → `violated=true` + 命中词 | 构造内容断言 |
| 单元 | 重复度检测：与历史比对 → 分数 | 构造高重复断言 >阈值 |
| 集成 | `content_moderator` + 品牌配置 → 合规检查结果 | 断言 pass/fail/warning |
| 集成 | 不同平台规则不同 → 检查结果因平台而异 | 同内容 2 平台断言差异 |
| 回归 | Fusion AI `content_moderator` 已有功能不回归 | 断言原有 API 兼容 |
| 单元 | 禁用词 CRUD：添加后检测生效 | 添加断言违规 |

**验收标准**：禁用词被标记；不同平台检查结果因规则而异。

---

### 3.3 内容审核队列

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 审核状态枚举：pending/approved/rejected/needs_revision | 遍历断言 |
| 单元 | 审核记录 schema：review_id/version_id/decision/reviewer/comment/timestamp | 断言字段 |
| 集成 | `POST /review-requests/` → 创建待审核 | 断言 201 + id |
| 集成 | 审批/退回：`POST /{id}/approve` / `/{id}/reject` + 意见 | 断言状态 + 意见 |
| 集成 | 版本追踪：`GET /{id}/history` 返回多版本 | 断言列表 |
| 集成 | 与 0.2 衔接：审核通过 → 自动创建 `approved` 任务 | 查询任务断言 |
| E2E | Easel inbox：提交→审批→退回→再提交→通过 | Playwright 全流程 |
| 集成 | 不可篡改：修改审核记录 → 403 | 断言拒绝 |

**验收标准**：全流程（提交→审批/退回→修改→再审）通过；审核通过自动创建发布任务；不可篡改。

---

### 3.4 LangGraph Intelligence

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | Context Pack 构建：目标+账号+素材+品牌+历史 → 结构化 | 断言含全部要素 |
| 单元 | 权限分级：Read 不写、Draft 不发布、Execute 需审批 | 断言越权被拒 |
| 单元 | Agent 输出 schema：Strategist→策略 / Composer→版本 / Reviewer→风险 / Analyst→复盘 | 各断言 |
| 集成 | Strategist：输入目标 → 输出策略草案（受众/策略/渠道/预算） | 断言结构 |
| 集成 | Composer：素材+品牌 → 多平台 ContentVariant | 断言 ≥1 版本 |
| 集成 | Reviewer：内容版本 → 风险报告 | 断言风险等级 |
| 集成 | Analyst：回执+指标 → 复盘报告 | 断言报告结构 |
| 集成 | Checkpoint 恢复：中断后从断点继续 | 模拟中断断言 |
| 回归 | LangGraph 不直接发布：Agent 工具不含 publish | 断言无副作用 |
| 回归 | Fusion AI 已有编排不回归 | 断言原有 API |

**验收标准**：4 Agent 各产出合规 schema 输出；越权被拒；Checkpoint 恢复通过。

---

### 3.5 Campaign 工作台

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | Campaign schema：goal/audience/strategy/policy/status | 断言字段 |
| 单元 | 状态流转：draft→active→reviewing→scheduled→completed | 断言转换 |
| 集成 | `POST /campaigns/` → 201 | 断言 id |
| 集成 | 全链路：创建→策略→内容→审核→排期→执行 | 每步断言 |
| 集成 | 关联内容版本/发布计划 | 断言 `GET /{id}/variants` + `/plans` |
| E2E | 前端 Campaign 页面全流程 | Playwright |
| 回归 | 已有 `campaign_service.py` 不回归 | 断言原有 API |

**验收标准**：全链路 E2E 通过；前端全流程可操作。

---

### 3.6 智能排期

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 推荐算法：历史数据 → 最优时段 | 构造数据断言 |
| 单元 | 各平台最优窗口 | 断言符合预期 |
| 集成 | Campaign 激活 → 自动填充 PublishPlan 时间 | 断言 schedule 非空 |
| 集成 | 冲突检测：同账号 2h 内不排 2 任务 | 断言 warning |
| 回归 | 手动排期优先级：手动 > 推荐 | 手动后不被覆盖 |

**验收标准**：Campaign 激活自动填充排期；手动排期不被覆盖。

---

## Phase 4：数据闭环

### 4.1 素材增强

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | Transcript 生成：音视频 → 文本 | mock ASR 断言 |
| 单元 | 视觉摘要：视频 → 关键帧描述 | mock 视觉模型 |
| 单元 | AI metadata schema：copyright/ai_generated/source/usage_rights | 断言字段 |
| 集成 | 上传自动增强：上传视频 → 触发转录+摘要+metadata | 查询详情断言 |
| 集成 | `GET /assets/{id}/transcript` 返回文本 | 断言 |
| 回归 | 视频流水线不回归 | 断言原有 API |

**验收标准**：上传后自动生成 transcript+metadata；视频流水线回归通过。

---

### 4.2 数据回收与 Insight

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 指标 schema：views/likes/comments/shares/watch_time/conversion | 断言字段 |
| 单元 | 异常检测：突降 >50% → 告警 | 构造突降断言 |
| 集成 | 定时回收指标 → `metric_snapshots` 表 | 断言 DB 记录 |
| 集成 | Insight 生成：指标 → 分析（趋势/异常/建议） | 断言报告 |
| 集成 | 下一轮建议：Insight → 建议列表 | 断言 |
| 回归 | TikHub 已有采集不回归 | 断言 API 可用 |
| 冒烟 | 采集→入库→看板展示 | 断言看板 API |

**验收标准**：指标自动入库可查；Insight 报告可生成；异常触发告警。

---

### 4.3 内容去重/查重

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 文本相似度：0-1 分数 | 相同/相似/不同各一组 |
| 单元 | 素材指纹：相同→相同指纹；不同→不同 | 断言 |
| 集成 | 跨平台查重：同素材多平台 → 标记重复 | 断言标记 |
| 集成 | `GET /dedup/reports` 返回重复列表 | 断言 |
| 单元 | 阈值配置：不同阈值不同结果 | 构造 0.8/0.9 |

**验收标准**：同素材多平台被标记；查重报告正确。

---

### 4.4 多账号矩阵调度

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 并发控制：并发 ≤ 配置上限 | 构造 10 任务断言 |
| 单元 | 冲突检测：同素材→同账号 → 拒绝 409 | 断言 |
| 单元 | 限流退避：平台限流 → 退避重试 | mock 限流断言 |
| 集成 | 账号池 `GET /accounts/pool` | 断言返回 |
| 集成 | 矩阵 E2E：10 任务→5 账号→全部成功 | 断言 succeeded |
| 回归 | 已有 `matrix_scheduler.py` 不回归 | 断言原有 API |
| 冒烟 | 50 任务并发入队 → 无丢失无崩溃 | 断言 |

**验收标准**：50 任务无丢失；冲突正确拒绝；限流退避生效。

---

## Phase 5：系统增强

### 5.1 CLI 统一

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 命令注册完整性：account/publish/campaign/task/diagnose | 遍历断言 |
| 单元 | `--json` 输出可解析 | 各命令断言 |
| 单元 | 所有命令返回 request_id | 断言含 id |
| 集成 | CLI 全流程：login→publish→task status→diagnose | 端到端脚本 |
| 集成 | CLI 走 Domain Service 而非上传脚本 | mock Domain Service |
| 回归 | 已有 `prism_cli.py` 25KB 不回归 | 断言原有命令 |
| 冒烟 | CLI 全流程冒烟 | 每步断言 |

**验收标准**：`--json` 全部可解析；CLI 走 Domain Service；全流程冒烟通过。

---

### 5.3 RBAC

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 角色枚举：admin/editor/reviewer/viewer | 遍历断言 |
| 单元 | 权限矩阵：各角色权限集正确 | 断言矩阵 |
| 单元 | 中间件：未认证→401；权限不足→403 | mock 用户 |
| 集成 | viewer 无法发布→403；admin→200 | 断言状态码 |
| 集成 | 操作写入 `audit_events` 表 | 查询断言 |
| 集成 | 审计不可篡改 | 完整性校验 |
| 集成 | 所有 API 端点有权限检查 | 遍历路由表 |
| E2E | 前端菜单按角色显示 | Playwright |
| 回归 | 已有 API 在新角色下正常 | 断言原有 API |

**验收标准**：权限矩阵通过；viewer 无法发布（403）；审计日志完整；前端菜单按角色显示。

---

### 5.2 Persona Studio 加固

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | Persona→RBAC 角色映射正确 | 断言映射 |
| 集成 | 登录后权限上下文注入 | 断言用户上下文含角色 |
| 回归 | Persona 已有功能不回归 | 断言原有 API |
| 集成 | 多用户权限隔离 | 构造多用户断言 |

**验收标准**：Persona 登录自动获得 RBAC 角色；多用户隔离正确。

---

### 5.4 Webhook/API 集成

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 签名验证：通过/失败 | 断言校验 |
| 单元 | 幂等去重：相同事件 ID → 只处理一次 | 断言 |
| 集成 | 外部触发发布 → 创建任务 | 断言 task_id |
| 集成 | 回执回调：任务完成 → POST 回调 URL | mock 断言 |
| 集成 | 回调幂等：相同 task_id 只触发一次 | 断言 |
| 冒烟 | 全流程：外部触发→执行→回调 | 端到端 |

**验收标准**：Webhook 触发成功；回执回调正确；幂等生效。

---

## Phase 6：安全合规与质量保障

### 6.1 安全加固

| 层级 | 验证项 | 方法 |
|---|---|---|
| 单元 | 敏感配置加密：API Key 存 DB 为加密格式 | grep DB 断言无明文 |
| 单元 | 日志脱敏：Key/Token → `***` | grep 日志断言 |
| 单元 | 输入校验：SQL 注入/XSS/路径穿越 → 拦截 | 构造恶意输入断言 400/403 |
| 单元 | 速率限制：短时间大量请求 → 429 | 构造 N 请求 |
| 集成 | CORS 收紧：非白名单 → 拒绝 | mock Origin 断言 |
| 集成 | OWASP Top 10 扫描 | 扫描脚本断言无高危 |
| 冒烟 | 密钥泄露扫描：`grep -rE '(sk-|ghp_|api_key|password)' .` | 断言 0 命中 |

**验收标准**：DB 无明文 Key；SQL 注入/XSS 被拦截；安全扫描无高危。

---

### 6.2 操作审计日志

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | 所有操作写入 `audit_events` | 执行后查询 |
| 集成 | 字段完整：操作者/时间/类型/目标/结果 | 断言字段 |
| 集成 | 不可篡改：修改 DB → 校验失败 | 完整性校验 |
| 集成 | 查询：按角色/时间/类型检索导出 | 断言返回 |
| 冒烟 | 操作后审计即时可查 | 执行后立即查 |

**验收标准**：所有操作写入审计；条件查询正确；不可篡改。

---

### 6.3 数据安全与备份

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | 定时备份 → 文件生成 | 触发断言文件存在 |
| 集成 | 备份恢复 → 数据完整 | 恢复后断言一致 |
| 集成 | 任务数据导出 CSV/JSON | 断言格式 |
| 集成 | Cookie 加密落盘 | 断言非明文 |
| 单元 | 删除合规：账号删除→关联清理 | 断言清理 |
| 冒烟 | 备份→删除→恢复→一致 | 端到端 |

**验收标准**：备份可生成可恢复（一致）；Cookie 加密；任务可导出。

---

### 6.4 测试与验收

| 层级 | 验证项 | 方法 |
|---|---|---|
| 质量门禁 | 单元覆盖率 ≥80%（核心 ≥90%） | `pytest --cov` |
| 质量门禁 | 集成覆盖率 ≥70% | 断言 |
| 质量门禁 | 各平台冒烟用例集 ≥3 条 | 断言用例数 |
| 质量门禁 | 回归测试基线：全部通过 | 断言 0 失败 |
| 性能压测 | 10 并发 × 5 平台 = 50 任务全部完成 | 断言 succeeded |
| 性能压测 | 持续 1 小时不崩溃 | 断言无崩溃 |
| 冒烟 | 全平台 preview_only 回归 | 5 平台全通过 |
| 验收清单 | 各 Phase 验收标准逐项检查 | 自动化清单脚本 |

**验收标准**：覆盖率达标；5 平台冒烟通过；50 任务压测成功；回归 0 失败。

---

### 6.5 私有化部署方案

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | Docker Compose → 全部服务启动 | 断言容器 healthy |
| 集成 | 一键部署脚本 → 依赖安装→启动→配置 | 干净环境运行 |
| 集成 | 离线安装包 → 无网络安装 | 断言无缺失依赖 |
| 冒烟 | 运维面板：健康检查+日志+指标 | 断言可访问 |
| 冒烟 | 从 0 到首次发布全流程 | 端到端 |

**验收标准**：一键部署完成；Docker Compose healthy；从 0 到发布通过。

---

## Phase 7：Rust Core 与桌面端

### 7.1 Rust Core

| 层级 | 验证项 | 方法 |
|---|---|---|
| 集成 | daemon 启动：端口监听+健康检查 | `curl /health` → 200 |
| 集成 | CLI 通过 prism-core 路由 | 断言输出含 Rust 版本 |
| 集成 | 生命周期：启动/停止/重启 | 断言状态切换 |
| 集成 | 端口管理：占用检测+分配 | 断言检测正确 |
| 回归 | Electron 原有功能不回归 | 断言可用 |
| 冒烟 | 端到端：启动→CLI→任务执行 | 断言全流程 |

**验收标准**：daemon 健康检查通过；CLI 通过 core；生命周期测试通过。

---

### 7.2 Tauri 桌面端

| 层级 | 验证项 | 方法 |
|---|---|---|
| 冒烟 | Tauri 应用启动：窗口正常显示 | 启动截图 |
| 集成 | 所有前端页面可访问 | 遍历路由断言 200 |
| 集成 | Tauri↔prism-core IPC | 断言通信 |
| 集成 | 桌面端服务管理：启动/停止后端/前端 | 断言状态变更 |
| 回归 | 与 Electron 功能一致 | 逐页对比 |
| 冒烟 | 安装包体积 < Electron 1/3 | 对比大小 |

**验收标准**：Tauri 页面全可访问；服务管理可用；体积显著小于 Electron。

---

## Phase 8：交付文档与开源

### 8.1 交付文档包

| 层级 | 验证项 | 方法 |
|---|---|---|
| 验收 | 部署手册：从零部署完整步骤 | 人工审核 |
| 验收 | 运维手册：监控/备份/故障排除 | 人工审核 |
| 验收 | 用户手册：各功能操作指南 | 人工审核 |
| 验收 | API 文档：所有端点有 OpenAPI/Swagger | 断言 Swagger UI |
| 验收 | 架构说明：架构图+模块说明 | 人工审核 |
| 验收 | 测试报告：单元+集成+E2E+性能 | 断言报告存在 |
| 验收 | 验收清单：各 Phase 标准逐项列出 | 断言完整 |
| 冒烟 | 文档可查性：目录清晰、可搜索 | 断言 README 入口 |

**验收标准**：所有文档齐全可访问；Swagger 完整；验收清单覆盖全部 Phase。

---

### 8.2 全平台打包

| 层级 | 验证项 | 方法 |
|---|---|---|
| 冒烟 | Windows .exe/.msi 安装后启动 | 断言成功 |
| 冒烟 | Mac .dmg 安装后启动 | 断言成功 |
| 冒烟 | Linux .deb/.rpm 安装后启动 | 断言成功 |
| 集成 | 首次启动自动配置环境 | 断言配置完成 |
| 集成 | 代码签名验证 | 断言签名有效 |

**验收标准**：三平台安装包各安装启动成功；签名验证通过。

---

### 8.3 开源整理

| 层级 | 验证项 | 方法 |
|---|---|---|
| 验收 | Easel 署名：README/NOTICE 含浙大 ZJU-REAL，Apache 2.0 | 断言含署名 |
| 验收 | 第三方许可审计报告 | 断言报告存在 |
| 验收 | LICENSE 文件 | 断言存在 |
| 验收 | NOTICE 文件 | 断言存在 |
| 冒烟 | 合规扫描：依赖许可证与项目兼容 | `license-checker` |

**验收标准**：Easel 署名正确；许可审计通过；LICENSE+NOTICE 完整。

---

## 质量门禁总表

> 每次 PR / CI 自动检查，**不通过不合并**。

| # | 门禁项 | 命令 | 通过标准 |
|---|---|---|---|
| G1 | Python 语法检查 | `python -c "import ast; ast.parse(open(f).read())"` | 0 错误 |
| G2 | 单元测试+覆盖率 | `pytest tests/ --cov --cov-fail-under=80` | ≥80%，核心≥90% |
| G3 | 集成测试 | `pytest tests/ -m integration` | 0 失败 |
| G4 | 冒烟测试 | `pytest tests/ -m smoke` | 5 平台全通过 |
| G5 | 前端 lint | `npx eslint src/` | 0 error |
| G6 | 前端 typecheck | `npx tsc --noEmit` | 0 error |
| G7 | 依赖安全扫描 | `safety check` / `npm audit` | 0 高危 |
| G8 | 敏感信息扫描 | `grep -rE '(sk-|ghp_\|api_key\|password).*=[^*]' .` | 0 命中 |
| G9 | 回归测试 | `pytest tests/ -m regression` | 0 失败 |
| G10 | API 文档覆盖 | 新增 API 均有 OpenAPI schema | 100% 覆盖 |

---

## CI 流水线配置建议

```yaml
# .github/workflows/ci.yml（参考）
on: [pull_request, push]
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements-dev.txt
      - run: pytest prism_backend/tests/ --cov --cov-fail-under=80 -m "not e2e"
      - run: pytest prism_backend/tests/ -m integration
      - run: pytest prism_backend/tests/ -m smoke
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd prism_frontend && npm ci
      - run: cd prism_frontend && npx eslint src/
      - run: cd prism_frontend && npx tsc --noEmit
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Secret scan
        run: grep -rE '(sk-|ghp_|api_key|password).*=[^*]' . && exit 1 || exit 0
      - name: Dependency audit
        run: |
          pip install safety
          safety check -r prism_backend/requirements.txt
```

---

## 里程碑验收清单

### M1：可用版（Week 1-4）验收

- [ ] 0.1 发布回执结构化 API 可查（`GET /receipts/{task_id}` 返回完整 JSON）
- [ ] 0.2 状态转换矩阵单元测试 100% 通过 + 幂等键测试通过
- [ ] 0.4 账号健康检查 API 返回全部账号状态
- [ ] 1.1 抖音商品挂载 preview_only 日志含「标记万物」
- [ ] 1.2-1.5 5 平台 preview_only 冒烟全通过
- [ ] 1.6 前端账号页显示正确健康状态
- [ ] 3.1 内容版本 API 可生成+查询+切换
- [ ] 3.2 禁用词检测生效 + 不同平台合规检查差异化

### M2：AI 编排 + 诊断（Week 5-9）验收

- [ ] 2.1 选择器 JSON 校验 + 加载 + 回滚测试通过
- [ ] 2.2 失败任务自动产出工件（截图+DOM+日志）+ 脱敏通过
- [ ] 2.3 端到端修复流程至少 1 次通过
- [ ] 0.3 Webhook 告警 mock 收到通知
- [ ] 3.3 内容审核全流程（提交→审批/退回→再审）+ 衔接 0.2
- [ ] 3.4 4 Agent 各产出合规输出 + 越权被拒 + checkpoint 恢复
- [ ] 3.5 Campaign 全链路 E2E 通过
- [ ] 3.6 Campaign 激活自动填充排期 + 手动排期不被覆盖
- [ ] 4.1 素材上传自动生成 transcript+metadata

### M3：数据闭环 + 系统增强（Week 10-13）验收

- [ ] 4.2 指标自动入库 + Insight 报告可生成 + 异常告警
- [ ] 4.3 跨平台查重标记正确 + 查重报告 API 正确
- [ ] 4.4 50 任务并发无丢失 + 冲突拒绝 + 限流退避
- [ ] 5.1 CLI `--json` 全部可解析 + 走 Domain Service + 全流程冒烟
- [ ] 5.3 RBAC 权限矩阵 + 审计日志 + 前端菜单按角色
- [ ] 5.2 Persona→RBAC 映射 + 多用户隔离
- [ ] 5.4 Webhook 触发+回执回调+幂等
- [ ] 6.1 DB 无明文 Key + 注入/XSS 被拦截 + 安全扫描无高危
- [ ] 6.2 操作审计日志完整+不可篡改
- [ ] 6.3 备份可恢复+Cookie 加密+数据可导出

### M4：验收与交付（Week 14-18）验收

- [ ] 6.4 覆盖率达标（≥80%）+ 5 平台冒烟 + 50 任务压测 + 回归 0 失败
- [ ] 6.5 Docker Compose healthy + 一键部署 + 从 0 到发布
- [ ] 7.1 prism-core 健康检查+CLI 路由+生命周期（可选）
- [ ] 7.2 Tauri 页面全可访问+服务管理+体积 < Electron 1/3（可选）
- [ ] 8.1 所有文档齐全可访问 + Swagger 完整 + 验收清单完整
- [ ] 8.2 三平台安装包启动成功 + 代码签名（可选）
- [ ] 8.3 Easel 署名+许可审计+LICENSE+NOTICE+合规扫描
