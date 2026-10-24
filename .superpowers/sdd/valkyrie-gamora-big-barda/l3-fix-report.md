# L3 评审修复报告

评审来源：`.superpowers/sdd/valkyrie-gamora-big-barda/l3-review.md`
评审结论：**Needs fixes** — 1 Critical + 2 Important + 4 Minor。

本修复轮处理 C1 + I1 + I2 三条（评审第 3 条实为测试盲区，非功能缺陷，已通过新增测试覆盖）。Minor 按评审建议留技术债不做。

## 逐条处理

### C1（Critical）— `hermes-provider-card.tsx:273` apply-to body 契约错配

**问题**：`doImport()` 发 `body: "{}"` 到 `POST /api/v1/ai/providers/{id}/apply-to/chat`，
后端 `providers_router.py:477` 的 `ApplyToRequest.model_name` 是必填（空则 `HTTPException(400)`），
用户点「导入配置」按钮 100% 失败。

**修法**（1 行改 3 行）：

```ts
body: JSON.stringify({ model_name: selectedModel })
```

`doImport` 的 deps `[selectedProviderId, selectedModel, toast, hydrate]` 已含 `selectedModel`，
无需改 deps 数组。

### I1（Important）— `router.py:from-performance` 用 HTTP 200 掩盖 DB 故障

**问题**：`sqlite3.connect()` 失败分支返回 `{"status":"error","result":{...}}` HTTP 200。
前端 ideas 区块在 `loadPerformance` 里按 `res.ok` 判定成功，`data.status === "error"`
未被检查——真实的后端故障（DB 不可用/损坏）会被当成「无数据」提示展示，掩盖故障。

**修法**（后端改 4 行）：

```python
except sqlite3.Error as e:
    logger.error(f"from-performance: 数据库连接失败 {e}")
    raise HTTPException(status_code=503, detail="选题数据暂不可用")
```

**前端无需改**：`loadPerformance` 已有 `if (!res.ok) throw new Error(...)` 分支，
会走 toast 分支，dedupeKey 覆盖此场景。

### I2（评审列第 3 条，实为测试盲区）— hermes-provider-card 无前端测试

**修法**：新增 `hermes-provider-card.dom.test.tsx`（2 用例），
断言 apply-to 请求 body 含 `model_name` 字段并等于选中的模型。

## 测试

| 用例 | 文件 | 覆盖 |
|---|---|---|
| `test_ideas_from_performance_db_unavailable_raises_503` | `test_l3_island_links.py` | monkeypatch `sqlite3.connect` 抛 `OperationalError` → 断言 `HTTPException.status_code == 503` + `detail` 含「选题数据」 |
| `点导入配置按钮时 apply-to 请求体携带 model_name=selectedModel` | `hermes-provider-card.dom.test.tsx` | 完整流程（展开卡片 → 打开导入弹窗 → 选供应商 → 选模型 → 点导入）→ 断言 `JSON.parse(body) === { model_name: "gpt-4o" }` + 反向断言 `body !== "{}"` |
| `URL 命中 /ai/providers/{id}/apply-to/chat` | 同上 | 断言 URL 含 `/ai/providers/7/apply-to/chat` |

## 全量验证

| 命令 | 结果 |
|---|---|
| 后端 `pytest tests/test_l3_island_links.py -q` | **12 passed**（原 11 + 新增 1） |
| 前端 `vitest run` | 28 files / **460 passed**（原 458 + 新增 2） |
| 前端 `tsc --noEmit` | 0 error |
| 前端 eslint（2 改动文件） | 0 error（2 warnings 预存 `any`） |
| 后端 ruff `--select E9,F63,F7,F82,F841`（2 改动文件） | All checks passed |
| U+FFFD（4 改动文件） | 全部 0 |

## 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `prism_frontend/src/components/settings/hermes-provider-card.tsx` | 修改 | body `"{}"` → `JSON.stringify({ model_name: selectedModel })` + 注释 |
| `prism_frontend/src/components/settings/__tests__/hermes-provider-card.dom.test.tsx` | 新增 | 2 用例，断言 apply-to 请求契约 |
| `prism_backend/fastapi_app/api/v1/content_library/router.py` | 修改 | `sqlite3.Error` 分支改 `raise HTTPException(503, ...)` |
| `prism_backend/tests/test_l3_island_links.py` | 修改 | 新增 1 用例 `test_ideas_from_performance_db_unavailable_raises_503` |

## 未处理（Minor，留技术债）

评审 4 条 Minor 按建议留后续：
- `share_count` 未参与加权（SELECT 里存在但 `_score` 与 `note` 未用）
- `max_score = max(...) or 1` 后 `if max_score` 冗余兜底
- `campaigns/router.py:limit=1000` cap 未测
- `campaigns/[id]/page.tsx` publishTasks 空态未显示区块（评审已确认设计取舍可接受）
