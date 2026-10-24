<!-- 由 scripts/docs/build_sprint_acceptance.py 生成；状态列由验收执行人更新，
     其余列的改动请改数据源后重跑 build。统计以 read_sprint_acceptance.py 输出为准。 -->

# 冲刺验收表 · R1 收尾 + R2 产品地基

> 冲刺窗口：2026-10-17 ～ 2026-10-24（R1 收尾 + R2 Phase 0.1/0.2）· 基线提交 c24a11d 起计
> 构建：2026-10-24 · 共 20 项（A 10 / B 6 / C 4）
>
> 列口径：验证方式 auto=命令可复跑 / manual=人工核对 / external=外部系统；
> 证据分级 verified=自动命令证据 / confirmed=人工确认 / speculated=未验证（初始态）；
> 状态 pending / partial / passed，passed 需附日期与执行人，如 `passed 2026-10-24 by controller`；
> 项通过后证据分级同步升级：auto → verified，manual/external → confirmed。

## 组 A · R1 收尾验收

| 编号 | 验收项 | 可复跑命令 | 期望输出 | 验证方式 | 证据分级 | 状态 |
|---|---|---|---|---|---|---|
| A1 | 向导平台对齐 | grep -n -A 9 "PUBLISH_PLATFORMS" prism_frontend/src/components/wizard/scenarios.tsx && grep -n -A 8 "_PLATFORM_MODULES" prism_backend/fastapi_app/services/publish_tools/__init__.py | 两侧对照：zhihu/toutiao/xigua 为禁用态且带「暂不支持发布」提示；可发布平台恰为 douyin/kuaishou/bilibili/xhs/channels 五个 | auto | verified | passed 2026-10-24 by controller |
| A2 | 社区文件三件存在 | git ls-files CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md | 恰三行输出（三个文件均被 git 跟踪） | auto | verified | passed 2026-10-24 by controller |
| A3 | SECURITY 渠道口径 | 人工通读 SECURITY.md 全文 | 全文无微信号文字、无邮箱，仅官网二维码渠道 | manual | confirmed | passed 2026-10-24 by controller |
| A4 | CHANGELOG 事实核对 | head -60 CHANGELOG.md && git log --date=short --format="%h %ad %s" -20 | 1.1.1→1.1.5 各版本日期与 commit 归属和 git log 一致 | auto | verified | passed 2026-10-24 by controller |
| A5 | systemd Documentation 修复 | grep -n "Documentation=" deploy/prism-cloud.service | Documentation=file:///opt/prism-fusion/app/docs/dev-reports/2026-10-13-deployment-guide.md（仓库与服务器 unit 均已验证，2026-10-24） | auto | verified | passed 2026-10-24 by controller |
| A6 | 收官 dev-report 存在 | ls docs/dev-reports/ \| grep 2026-10-24 | 恰 1 份，内容覆盖 2026-10-17～10-24 | auto | verified | passed 2026-10-24 by controller |
| A7 | 备份 HISTORY round18 章节 | grep round18 D:/Prism-Fusion-Backup/PROJECT_DEVELOPMENT_HISTORY.md | 命中（round18 章节已写入备份侧开发史） | auto | verified | passed 2026-10-24 by controller |
| A8 | 备份 verify | python scripts/backup/build_backup_manifest.py --backup-root D:/Prism-Fusion-Backup --verify | 校验完成：通过 14 个，不符/缺失 0 个 | auto | verified | passed 2026-10-24 by controller |
| A9 | 交接文档口径修正 | 人工核对 docs/handover/PROJECT-HANDOVER.md §7.1 | §7.1-5 已补齐口径；基线注明为 c24a11d 及之后 | manual | confirmed | passed 2026-10-24 by controller |
| A10 | U+FFFD/编码卫生 | git diff --name-only c24a11d -- "*.md" "*.py" "*.tsx" \| xargs -r grep -l $'\\uFFFD' | 无输出（本轮冲刺全部改动的 md/py/tsx 文件 U+FFFD 扫描 0 命中） | auto | verified | passed 2026-10-24 by controller |

## 组 B · R2 产品功能验收

> 命令里的 `-k` 关键字是入口约定；R2 测试合入后若实际命名不同，以实际测试文件为准（关键字可等价替换），期望列不变。

| 编号 | 验收项 | 可复跑命令 | 期望输出 | 验证方式 | 证据分级 | 状态 |
|---|---|---|---|---|---|---|
| B1 | 0.1 回执 schema 单测 | cd prism_backend && python -m pytest fastapi_app/tests/ -k "receipt" --tb=short -q | PublishReceipt 字段完整性 + 条件必填用例全部通过 | auto | verified | passed 2026-10-24 by controller |
| B2 | 0.1 回执集成测 | cd prism_backend && python -m pytest fastapi_app/tests/ -k "receipt" --tb=short -q | GET /receipts/{task_id} 返回 200 且全字段的集成用例通过 | auto | verified | passed 2026-10-24 by controller |
| B3 | 0.2 状态矩阵穷举 | cd prism_backend && python -m pytest fastapi_app/tests/ -k "state or transition" --tb=short -q | 合法转换全过 + 非法转换 InvalidTransition 100% | auto | verified | passed 2026-10-24 by controller |
| B4 | 0.2 幂等键 | cd prism_backend && python -m pytest fastapi_app/tests/ -k "idempot" --tb=short -q | 相同输入相同 key + 并发同 task_id | auto | verified | passed 2026-10-24 by controller |
| B5 | 验收表往返一致 | python scripts/docs/test_sprint_acceptance_roundtrip.py | ALL TESTS PASSED | auto | verified | passed 2026-10-24 by controller |
| B6 | 回归 | cd prism_backend && python -m pytest fastapi_app/tests/ tests/test_license_module.py tests/test_license_plan_derive.py tests/test_license_readonly_guard.py --tb=short -q && cd ../prism_frontend && npm test | 既有 pytest 全绿 + vitest 全绿（CI 8 硬门同口径） | auto | verified | passed 2026-10-24 by controller |

## 组 C · 文档与卫生门

| 编号 | 验收项 | 可复跑命令 | 期望输出 | 验证方式 | 证据分级 | 状态 |
|---|---|---|---|---|---|---|
| C1 | 链接检查 | git diff --name-only c24a11d -- "*.md" | 本轮改动文档的相对链接 0 缺失（收尾 probe 输出为准） | auto | verified | passed 2026-10-24 by controller |
| C2 | 提交卫生 | git status --short | 干净（未跟踪仅 .superpowers/） | manual | confirmed | passed 2026-10-24 by controller |
| C3 | commit message 扫描 | git log c24a11d..HEAD --pretty=%B | 无绝对路径/凭据/账号标识（逐条人工核对） | manual | confirmed | passed 2026-10-24 by controller |
| C4 | CI 硬门 | gh run list --workflow CI --limit 1（或网页 GitHub → Actions → CI 最新 run） | 8 个硬门 job 全绿：python-smoke / lint / deps-gate / lint-frontend / frontend-lint-test / backend-selftest / test / cloud-service-tests（e2e-packaged 为软门不计） | auto | verified | passed 2026-10-24 by controller |
