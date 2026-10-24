# ADR-0008: 数据层软关联归因列，不做强制迁移

- **状态**：已接受（补录）
- **日期**：2026-10-22
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-22 收官时，数据层四表（`materials` / `publish_tasks` / `video_analytics` / `review_receipts`）之间的关联关系是**硬外键**——某表外键指向另一表主键，删除被引用方会导致级联问题。同时 `video_analytics` 表存在悬空 FK（引用已被删除的 `publish_tasks` 记录）。

断链审计发现 10 条断链（`docs/handover/PROJECT-HANDOVER.md` §3 阶段 C）：素材→发布→审核→回收 链路上多处引用缺失。硬外键 + 严格约束导致：

1. 用户删素材后，关联的发布任务、审核回执无法清理
2. `video_analytics` 悬空 FK 触发 SQLAlchemy 启动期报错
3. 数据回收任务无法关联到已删除的原始素材

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 C「打通 10 条断链」
- `git show --stat e263a9d`：L1-2 四表软关联归因列 + 修 video_analytics 悬空 FK + 漂移收敛

## 决策

**四表改用软关联归因列**：新增 `source_material_id` / `source_task_id` / `source_receipt_id` 等字符串归因列（不建外键约束），硬 FK 改为软引用；对已存在的悬空 FK 做**一次性漂移收敛**（不迁移整表，只清理已知的悬空行）。

**具体落地**：
- `e263a9d`：L1-2 四表软关联归因列 + 修 `video_analytics` 悬空 FK + 漂移收敛
- 新增列：`source_material_id`（materials 侧）、`source_task_id`（publish_tasks 侧）、`source_receipt_id`（review_receipts 侧）
- 悬空 FK 清理：一次性 `DELETE FROM video_analytics WHERE publish_task_id NOT IN (SELECT id FROM publish_tasks)`
- 保留原有硬 FK 列，只是**新增软归因列**不替换，兼容旧数据

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 全量迁移到纯软关联（删所有硬 FK） | 破坏向后兼容，需迁移全部历史数据，风险高 |
| 保留硬 FK + 加级联删除 | 用户删素材后连带删掉发布任务、审核回执，数据丢失 |
| 保留硬 FK + 加级联更新 | 语义混乱，更新操作会跨表扩散 |
| 用 trigger 维护软归因列 | 复杂度高，且 SQLAlchemy 不支持 trigger 语法 |
| 全量重刷视频数据 | 数据回收成本高，且历史数据可能被用户依赖 |

## 代价

**收益**：
- 用户删除素材后，关联的发布任务、审核回执、数据回收数据保留
- `video_analytics` 悬空 FK 不再触发启动期报错
- 10 条断链一次性打通，数据回收链路完整

**代价**：
- 应用层必须自己处理「软关联对象不存在」的情况（不能用 ORM 外键加载）
- 数据库不再保证引用完整性，需在业务代码里维护
- 迁移成本：新增列不迁移旧数据（旧行的归因列为 NULL）

**已知副作用**：
- 部分旧数据（迁移前产生的）无归因列值，需按业务逻辑回查
- 数据审计时需按软归因列追溯，而非依赖硬 FK

## 未来复审触发条件

- 用户反馈数据丢失或关联断裂
- 数据量增长到需要跨表 JOIN 的性能优化时
- 引入新版本数据库（PG / ClickHouse）需重新评估 FK 策略

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 C
- Commit: `e263a9d` `5c8b71e`（L1-1 表 DDL 收编与启动 bootstrap）
