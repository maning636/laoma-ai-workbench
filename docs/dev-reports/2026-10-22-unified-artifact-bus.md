# 统一产物总线（Unified Artifact Bus）

> 日期：2026-10-22
> 分支：`main`　基线提交：`09e12c1`
> 定位：**自媒体矩阵发布 + AI 生图/生视频内容生产平台**
> 目标：让「功能」与「功能之间的产物」能串联、能通用、能串通

---

## 0. 一句话

项目原本有四套互不相通的 ID 空间，产出接不到下一步的调用；本次引入统一产物 ID `artifact_id`（`art_` + 12 位十六进制）与阶段机，把「AI 生图 / 素材上传 / 视频渲染 / 审核 / 发布」串成同一条流水线。

---

## 1. 问题：四套 ID 空间

| 域 | 原 ID 空间 | 存储位置 |
|---|---|---|
| AI 生图 | `image_generations.id`（整数） | `image_generations` 表 |
| 素材库 | `file_records.id`（整数） | `file_records` 表 |
| 审核队列 | `review_queue.review_id`（`rv_*`） | `review_queue` 表 |
| 发布任务 | `publish_tasks.task_id`（整数） | `publish_tasks` 表 |

后果：

- 生图产出的图片 URL **进不去**审核队列（审核项要 `task_id`，而生图没有 task_id）；
- 素材**进不去**发布任务（发布任务要 `material_id`，指向 file_records，无法表达「这是审核通过的版本」）；
- 「一稿多版」「派生」「回溯来源」无处安放。

### 1.1 顺带修掉的既有 P0：送审接口 500

写端到端探针时发现 `POST /api/v1/review/queue` **稳定 500**：

```
ReviewItem object has no attribute 'created_at'
```

根因：`prism_core/review_queue.py` 的 `enqueue_review()` 一直在写 `item.created_at`，但 `ReviewItem` 模型里根本没有这个字段 → 任何送审请求（`/review/queue`、`/review/auto-check`、批量入队）在入库前就抛 `AttributeError`。

**整条「送审」链路是断的**，而这正是本次要串联的那一环。修法：给 `ReviewItem` 补 `created_at: str = Field(default_factory=now_beijing_iso)`，并让 `_row_to_item()` 回填库里的真实值。

---

## 2. 方案

### 2.1 统一产物 ID 与主表

主库新增 `artifacts` 表（DDL 唯一真源：`prism_backend/fastapi_app/db/schema.py:ensure_artifacts_table`，由 `ensure_main_db_schema()` 在服务启动时调用）。

| 字段 | 含义 |
|---|---|
| `artifact_id` | 统一产物 ID（`art_` + 12 hex），主键 |
| `stage` | 阶段：`generated` / `uploaded` / `reviewing` / `approved` / `rejected` / `published` |
| `kind` | 产物类型：`image` / `video` / `audio` / `text` / `file` / `other` |
| `title` / `path` / `thumb` / `media_type` | 展示与产出本体（本地路径或远程 URL） |
| `source` | 来源域：`image_gen` / `upload` / `video_pipeline` / `manual` / `workshop` |
| `ref_type` + `ref_id` | 回指本域记录（`image_generation` / `file_record` / `review` / `publish_task`） |
| `parent_id` | 血缘：父产物 → 子产物（一稿多版） |
| `campaign_id` / `platform` | 所属活动与目标平台 |
| `review_id` / `publish_task_id` | 关联审核项 / 发布任务 |
| `dedupe_key` | **登记幂等键** = `sha1(ref_type\|ref_id\|path)` 前 32 位，唯一索引 |
| `meta` | 附加 JSON |

为什么幂等键要带 `path`：一次生图 `count>1` 会产生多张图共享同一个 `image_generations.id`，只按 `ref_id` 去重会把多张图压成一条。

`publish_tasks` 另加一列 `artifact_id`，让发布任务能指回它的来源产物。

### 2.2 阶段机

```
generated ─┐
uploaded  ─┴─→ reviewing ─→ approved ─→ published
                └──────→ rejected ─→(重新送审)─→ reviewing
```

非法流转被**显式拒绝**（HTTP 409），不改写阶段；`force=true` 仅供内部补偿。合法表在 `prism_core/artifacts.py:ALLOWED_TRANSITIONS`。

### 2.3 登记不阻断主业务

所有登记点都走 `safe_register_artifact()`：登记失败只记 warning，**不抛异常、不影响主流程**（生图照样返回图片、素材照样上传成功）。

### 2.4 data:base64 落盘

生图 provider 有的返回远程 URL、有的返回 `data:image/png;base64,...`（几 MB）。base64 **不能**进 `artifacts.path`（会撑爆 DB），因此落盘到 `VIDEO_FILES_DIR/generated/`，`path` 存相对路径（如 `generated/ab12.png`），`/getFile?filename=generated/ab12.png` 可直接取。

---

## 3. 落地清单

### 3.1 后端新增

| 文件 | 作用 |
|---|---|
| `prism_backend/prism_core/artifacts.py` | 统一产物服务：登记 / 查询 / 阶段机 / 血缘 / 统计（**只做 CRUD，不建表**） |
| `prism_backend/fastapi_app/api/v1/artifacts/router.py` | `/api/v1/artifacts` 路由（8 个端点） |
| `prism_backend/fastapi_app/api/v1/artifacts/__init__.py` | 包声明 |
| `prism_backend/tests/test_artifacts_bus.py` | 11 条 pytest 用例（临时库，不污染真实主库） |

### 3.2 后端 API

| 端点 | 说明 |
|---|---|
| `GET /api/v1/artifacts` | 列表（阶段 / 来源 / 类型 / 关键字过滤 + 分页） |
| `GET /api/v1/artifacts/stats` | 统计：按阶段 / 来源 / 类型分组 |
| `GET /api/v1/artifacts/{id}` | 详情（含血缘） |
| `GET /api/v1/artifacts/{id}/lineage` | 血缘：父链 + 子链 |
| `GET /api/v1/artifacts/by-ref/{ref_type}/{ref_id}` | 按本域记录反查产物 |
| `POST /api/v1/artifacts` | 手动登记产物 |
| `POST /api/v1/artifacts/{id}/promote` | 推进阶段（非法流转 409） |
| `POST /api/v1/artifacts/{id}/submit-review` | 送审（自动入审核队列 + 阶段转 reviewing） |

### 3.3 集成点（产物从哪来、往哪去）

| 集成点 | 改动 |
|---|---|
| **AI 生图** `fusion_ai/ai_design.py` | 生成成功后逐图登记（`source=image_gen`），响应新增 `artifact_ids` |
| **素材上传** `fastapi_app/api/v1/files/router.py` | 上传后登记（`source=upload`），响应新增 `artifact_id` |
| **视频渲染** `fastapi_app/api/v1/video_pipeline/router.py` | 渲染产物登记（`source=video_pipeline`），响应新增 `artifact_ids` |
| **送审** `fastapi_app/api/v1/artifacts/router.py` + `review/router.py` | 审核项 `task_id` 存 `artifact_id`；`/review/queue` 收到 `art_*` 时自动关联产物 |
| **审核决策** `prism_core/review_queue.py` | 通过 → `approved`；拒绝 / 需修改 / 自动预检否决 → `rejected`（**阶段回写**） |
| **发布** `publish_tasks.artifact_id` | 列已加（消费逻辑放下一阶段） |

### 3.4 前端新增 / 改动

| 文件 | 改动 |
|---|---|
| `prism_frontend/src/app/artifacts/page.tsx` | **新增** 产物中心：阶段统计条 + 过滤器 + 产物表 + 详情/血缘弹窗 + 一键送审 |
| `prism_frontend/src/components/layout/sidebar-new.tsx` | 新增「产物」分组 → 产物中心（位于「生成」与「分发」之间） |
| `prism_frontend/src/app/fusion/image-studio/page.tsx` | 每张生成图下方显示 `artifact_id`，并提供「送审」按钮 |
| `prism_frontend/src/app/review/page.tsx` | 审核队列新增「来源产物」列；审核后 toast 显示产物阶段回写结果 |
| `prism_frontend/src/lib/image-studio.ts` | `AiDesignGenerateResponse` 增加 `artifact_ids?: string[]` |

---

## 4. 验证

| 项目 | 结果 |
|---|---|
| `pytest prism_backend/tests` | **147 passed / 1 skipped**（原 136 passed + 新增 11 条） |
| `tsc --noEmit`（前端） | **0 错** |
| `vitest run`（前端） | **336 / 336 passed** |
| API 级端到端（打真实 :7000） | **26 / 26 通过** |
| 探针脚本（直接打主库） | **18 / 18 通过** |
| 页面 SSR | `/artifacts`、`/review`、`/fusion/image-studio` 均 200；侧边栏含「产物中心」 |
| 前端代理 | `/api/v1/artifacts` 经 Next rewrite 打到后端 200 |
| 数据洁净 | 演示/探针数据已清零：`artifacts=0` / `file_records=0` / `review_queue=0` |

### 4.1 API 级端到端覆盖的链路

```
素材上传 → 响应带 artifact_id
       → GET /artifacts 列表可见（stage=uploaded, source=upload, ref=file_record#id）
       → POST /artifacts/{id}/submit-review  (201)
       → GET /review/queue 审核项 task_id == artifact_id
       → 产物 stage=reviewing、review_id 已回填
       → POST /review/items/{rid}/approve
       → 响应 artifact_stage=approved
       → GET /artifacts/{id} stage=approved
       → 非法流转 published→reviewing 返回 409
```

### 4.2 回归

`POST /api/v1/review/queue` 修复前 **500**，修复后 **201**（`test_05_review_item_has_created_at` 专门防护）。

---

## 5. 已知边界 / 下一阶段

1. **发布侧消费尚未接线**：`publish_tasks.artifact_id` 列已就位，但「审核通过的产物 → 一键发布」还没做（`approved → published` 的自动流转与发布任务创建）。
2. **血缘只有一层写入入口**：手工登记时可指定 `parent_id`；「用产物 A 生成产物 B」这种自动派生还没接（生图 API 暂未接收 `parent_artifact_id`）。
3. **老数据未回填**：历史 `image_generations` / `file_records` 不会自动变成产物，只有新产生的才有 `artifact_id`。需要时可用 `POST /api/v1/artifacts` 批量回填。
4. **`data:` URL 落盘目录**固定为 `VIDEO_FILES_DIR/generated/`，未做保留策略（会一直堆积）。
5. **内置 Browser 在本机持续超时**，未能做实机截图验证；页面已用 SSR 200 + 代理数据路径 + tsc/vitest 三重覆盖。

---

## 6. 相关文件

- 服务：`prism_backend/prism_core/artifacts.py`
- 路由：`prism_backend/fastapi_app/api/v1/artifacts/router.py`
- DDL 真源：`prism_backend/fastapi_app/db/schema.py`（`ensure_artifacts_table`）
- 阶段回写：`prism_backend/prism_core/review_queue.py`
- 前端页面：`prism_frontend/src/app/artifacts/page.tsx`
- 测试：`prism_backend/tests/test_artifacts_bus.py`
