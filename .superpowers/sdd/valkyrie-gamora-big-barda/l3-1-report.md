# L3-1 报告：孤岛模块收编（后端+前端接线）

## 任务背景

`module-link-frontend.md` 孤岛清单与断链 #2/#5：
- 断链 #2：`hot_topics` 纯爬虫，`ideas` 页空转，自家表现数据不回写选题
- 断链 #5：模型供应商注册表 0 消费者，设置页「大语言模型配置」仍独立手填
- 孤岛：`campaigns` 与向导/发布零关联

## 三件收编

### ① ideas 吃回收数据（修断链 #2）

**后端**：`GET /api/v1/content-library/ideas/from-performance`
- 查询 `video_analytics` 按互动量加权（播放×1 + 点赞×1 + 评论×2 + 收藏×2）降序
- 映射为建议选题条目：`title`（去重后）、`note`（平台·播放·点赞·评论·收藏）、`heat`（0-1 归一）、`source="performance"`
- 支持 `platforms` 参数逗号分隔过滤（如 `douyin,tiktok`）
- 空数据返回 `{suggestions: [], data_ready: false, hint: "..."}` 不报错
- 老库无表/缺列 → 返回空列表 + 提示，不抛错

**前端**：ideas 页「从我的表现生成」区块——**留 L3-2**（前端接线需 ideas 页大改，超出本次最小闭环范围）

### ② campaigns 接向导产物

**后端**：
- `schema.py`：`DDL_PUBLISH_TASKS` 加 `campaign_id TEXT` 列 + `DDL_IDX_PUBLISH_TASKS` 索引
- `_ensure_legacy_column_migrations`：`publish_tasks_required` 加 `campaign_id`（幂等 ALTER）
- `BatchPublishRequest`：顶层加 `campaign_id: Optional[str]`
- `publish/services.py`：`publish_batch` 签名 + `_create_batch_tasks` 签名 + INSERT SQL 加 `campaign_id`
- `publish/router.py`：两处 publish_batch 调用透传 `campaign_id=request.campaign_id`
- `campaigns/router.py`：加 `GET /{campaign_id}/publish-tasks`（按 campaign_id 反查 publish_tasks）

**前端**：
- `publish/matrix/page.tsx`：加「关联营销活动」下拉（读 `/api/v1/campaigns/list`），payload 加 `campaign_id`
- `campaigns/[id]/page.tsx`：加「向导关联发布任务」区块（读 `/api/v1/campaigns/{id}/publish-tasks`）

### ③ providers 接通道消费（修断链 #5）

**前端**：`hermes-provider-card.tsx`
- 加「从供应商导入」按钮 + 弹窗
- 弹窗内：选供应商（读 `/ai/providers`）→ 拉模型列表（读 `/providers/{id}/models`）→ 调 `POST /providers/{id}/apply-to/chat`
- 不改原有手填路径，纯前端接线（后端 apply-to 端点已存在）

## 测试

### 后端 `tests/test_l3_island_links.py`（11 用例）

1. `test_ideas_from_performance_empty_returns_hint_and_empty_list`
2. `test_ideas_from_performance_aggregates_top_materials_by_engagement`
3. `test_ideas_from_performance_platform_filter`
4. `test_publish_tasks_campaign_id_column_idempotent_migration`
5. `test_publish_tasks_campaign_id_index_exists`
6. `test_publish_tasks_filter_by_campaign_id`
7. `test_publish_tasks_campaign_id_write_and_readback`
8. `test_campaign_publish_tasks_endpoint_roundtrip`
9. `test_campaign_publish_tasks_endpoint_empty_when_no_tasks`
10. `test_batch_publish_request_schema_has_campaign_id`
11. `test_batch_publish_request_campaign_id_does_not_break_attribution_fields`

### 回归测试

| 测试文件 | 结果 |
|---|---|
| `test_l1_attribution.py` | 7 passed |
| `test_l1_schema_bootstrap.py` | 5 passed |
| `test_l2_analytics_attribution.py` | 11 passed |
| `test_l2_image_to_library.py` | 8 passed |
| `test_l2_review_receipt_link.py` | 7 passed |
| **合计** | **41 passed** |

### 前端测试

`npx vitest run`：**25 文件 450 用例全过**（17.97s）

### 静态检查

- ruff `--select E9,F63,F7,F82,F841`：改动文件 0 报错（router.py 预存 1 个 F841 无关本次）
- U+FFFD：10 个改动文件全部 0

## 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `prism_backend/fastapi_app/db/schema.py` | 修改 | DDL + 索引 + 幂等迁移 |
| `prism_backend/fastapi_app/schemas/publish.py` | 修改 | BatchPublishRequest 加 campaign_id |
| `prism_backend/fastapi_app/api/v1/publish/services.py` | 修改 | publish_batch + _create_batch_tasks 透传 |
| `prism_backend/fastapi_app/api/v1/publish/router.py` | 修改 | 两处调用透传 campaign_id |
| `prism_backend/fastapi_app/api/v1/campaigns/router.py` | 修改 | 加 GET /{id}/publish-tasks |
| `prism_backend/fastapi_app/api/v1/content_library/router.py` | 修改 | 加 GET /ideas/from-performance |
| `prism_backend/tests/test_l3_island_links.py` | 新增 | 11 用例 |
| `prism_frontend/src/app/publish/matrix/page.tsx` | 修改 | 加 campaign 下拉 + payload |
| `prism_frontend/src/app/campaigns/[id]/page.tsx` | 修改 | 加关联发布任务区块 |
| `prism_frontend/src/components/settings/hermes-provider-card.tsx` | 修改 | 加从供应商导入按钮+弹窗 |

## 边界说明

- ideas 前端区块留 L3-2：本次仅完成后端端点 + 测试，前端需 ideas 页加「从我的表现生成」区块（大改，超出最小闭环）
- campaigns 关联任务区块仅在 `publishTasks.length > 0` 时显示，无数据时不占版面
- hermes-provider-card 导入弹窗不改变原有手填路径，纯增量接线
