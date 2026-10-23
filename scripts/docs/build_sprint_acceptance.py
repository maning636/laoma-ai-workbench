# -*- coding: utf-8 -*-
r"""生成《冲刺验收表 · R1 收尾 + R2 产品地基》Markdown 表。

与 client-acceptance 三件套同一工程模式（build / read / roundtrip），差别：
  - 输出是 **md 不是 docx** —— 本表是内部交接/收工闸门，不是给马哥点的 Word 表；
  - 数据源单一化：20 条验收项全部定义在本文件 ITEMS 里，表由脚本生成，
    改验收项改这里再重跑，**不要手改生成的 md 的非状态列**。

状态列是唯一允许人工编辑的列：验收执行人在 md 里把 `pending` 改成
`passed 2026-10-24 by controller` 这类形式；read_sprint_acceptance.py 负责读回。

转义约定（往返一致的关键）：
  - 单元格里的 `\` → `\\`，`|` → `\|`（GFM 表格内转义管道，渲染仍显示 `|`）；
  - read 侧按同一规则还原，roundtrip 测试据此断言逐字段一致。

依赖：仅标准库（无 python-docx），D:\\dev\\python\\python.exe 可直接跑。
"""
from __future__ import annotations

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "docs", "handover", "SPRINT-ACCEPTANCE-R1R2.md")

BUILD_DATE = "2026-10-24"
SPRINT_BASELINE = "c24a11d"  # 本轮冲刺起算提交（T1 文档批之前的基线）

METHODS = ("auto", "manual", "external")
EVIDENCE = ("verified", "confirmed", "speculated")

#: 每条七列：编号 / 验收项 / 可复跑命令 / 期望输出 / 验证方式 / 证据分级 / 状态。
#: 状态列文本：pending | partial | passed <date> by <owner>。
#: 初始全部 pending / speculated —— 本表构建于冲刺验收执行之前，勾选是验收动作。
ITEMS = [
    # ── 组 A · R1 收尾验收（10 条） ──────────────────────────
    ("A1", "向导平台对齐",
     'grep -n -A 9 "PUBLISH_PLATFORMS" prism_frontend/src/components/wizard/scenarios.tsx && grep -n -A 8 "_PLATFORM_MODULES" prism_backend/fastapi_app/services/publish_tools/__init__.py',
     "两侧对照：zhihu/toutiao/xigua 为禁用态且带「暂不支持发布」提示；可发布平台恰为 douyin/kuaishou/bilibili/xhs/channels 五个",
     "auto", "speculated", "pending"),
    ("A2", "社区文件三件存在",
     "git ls-files CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md",
     "恰三行输出（三个文件均被 git 跟踪）",
     "auto", "speculated", "pending"),
    ("A3", "SECURITY 渠道口径",
     "人工通读 SECURITY.md 全文",
     "全文无微信号文字、无邮箱，仅官网二维码渠道",
     "manual", "speculated", "pending"),
    ("A4", "CHANGELOG 事实核对",
     'head -60 CHANGELOG.md && git log --date=short --format="%h %ad %s" -20',
     "1.1.1→1.1.5 各版本日期与 commit 归属和 git log 一致",
     "auto", "speculated", "pending"),
    ("A5", "systemd Documentation 修复",
     'grep -n "Documentation=" deploy/prism-cloud.service',
     "Documentation=file:///opt/prism-fusion/app/docs/dev-reports/2026-10-13-deployment-guide.md（服务器侧同步由收尾批验证，本项只验仓库文件）",
     "auto", "speculated", "pending"),
    ("A6", "收官 dev-report 存在",
     "ls docs/dev-reports/ | grep 2026-10-24",
     "恰 1 份，内容覆盖 2026-10-17～10-24",
     "auto", "speculated", "pending"),
    ("A7", "备份 HISTORY round18 章节",
     "grep round18 D:/Prism-Fusion-Backup/PROJECT_DEVELOPMENT_HISTORY.md",
     "命中（round18 章节已写入备份侧开发史）",
     "auto", "speculated", "pending"),
    ("A8", "备份 verify",
     "python scripts/backup/build_backup_manifest.py --backup-root D:/Prism-Fusion-Backup --verify",
     "校验完成：通过 14 个，不符/缺失 0 个",
     "auto", "speculated", "pending"),
    ("A9", "交接文档口径修正",
     "人工核对 docs/handover/PROJECT-HANDOVER.md §7.1",
     "§7.1-5 已补齐口径；基线注明为 c24a11d 及之后",
     "manual", "speculated", "pending"),
    ("A10", "U+FFFD/编码卫生",
     "git diff --name-only " + SPRINT_BASELINE + ' -- "*.md" "*.py" "*.tsx" | xargs -r grep -l $\'\\uFFFD\'',
     "无输出（本轮冲刺全部改动的 md/py/tsx 文件 U+FFFD 扫描 0 命中）",
     "auto", "speculated", "pending"),

    # ── 组 B · R2 产品功能验收（6 条） ───────────────────────
    ("B1", "0.1 回执 schema 单测",
     'cd prism_backend && python -m pytest fastapi_app/tests/ -k "receipt" --tb=short -q',
     "PublishReceipt 字段完整性 + 条件必填用例全部通过",
     "auto", "speculated", "pending"),
    ("B2", "0.1 回执集成测",
     'cd prism_backend && python -m pytest fastapi_app/tests/ -k "receipt" --tb=short -q',
     "GET /receipts/{task_id} 返回 200 且全字段的集成用例通过",
     "auto", "speculated", "pending"),
    ("B3", "0.2 状态矩阵穷举",
     'cd prism_backend && python -m pytest fastapi_app/tests/ -k "state or transition" --tb=short -q',
     "合法转换全过 + 非法转换 InvalidTransition 100%",
     "auto", "speculated", "pending"),
    ("B4", "0.2 幂等键",
     'cd prism_backend && python -m pytest fastapi_app/tests/ -k "idempot" --tb=short -q',
     "相同输入相同 key + 并发同 task_id",
     "auto", "speculated", "pending"),
    ("B5", "验收表往返一致",
     "python scripts/docs/test_sprint_acceptance_roundtrip.py",
     "ALL TESTS PASSED",
     "auto", "speculated", "pending"),
    ("B6", "回归",
     "cd prism_backend && python -m pytest fastapi_app/tests/ tests/test_license_module.py tests/test_license_plan_derive.py tests/test_license_readonly_guard.py --tb=short -q && cd ../prism_frontend && npm test",
     "既有 pytest 全绿 + vitest 全绿（CI 8 硬门同口径）",
     "auto", "speculated", "pending"),

    # ── 组 C · 文档与卫生门（4 条） ──────────────────────────
    ("C1", "链接检查",
     'git diff --name-only ' + SPRINT_BASELINE + ' -- "*.md"',
     "本轮改动文档的相对链接 0 缺失（收尾 probe 输出为准）",
     "auto", "speculated", "pending"),
    ("C2", "提交卫生",
     "git status --short",
     "干净（未跟踪仅 .superpowers/）",
     "manual", "speculated", "pending"),
    ("C3", "commit message 扫描",
     "git log " + SPRINT_BASELINE + "..HEAD --pretty=%B",
     "无绝对路径/凭据/账号标识（逐条人工核对）",
     "manual", "speculated", "pending"),
    ("C4", "CI 硬门",
     "gh run list --workflow CI --limit 1（或网页 GitHub → Actions → CI 最新 run）",
     "8 个硬门 job 全绿：python-smoke / lint / deps-gate / lint-frontend / frontend-lint-test / backend-selftest / test / cloud-service-tests（e2e-packaged 为软门不计）",
     "auto", "speculated", "pending"),
]

GROUPS = (
    ("A", "组 A · R1 收尾验收", 10),
    ("B", "组 B · R2 产品功能验收", 6),
    ("C", "组 C · 文档与卫生门", 4),
)

HEADER_CELLS = ("编号", "验收项", "可复跑命令", "期望输出", "验证方式", "证据分级", "状态")


def esc(text: str) -> str:
    """单元格转义：反斜杠与管道（GFM 表格内 \\| 渲染为 |）。"""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def row_line(cells) -> str:
    return "| " + " | ".join(esc(c) for c in cells) + " |"


def render(items=ITEMS) -> str:
    by_group = {g: [it for it in items if it[0].startswith(g)] for g, _t, _n in GROUPS}
    for (g, _t, n) in GROUPS:
        assert len(by_group[g]) == n, "组 %s 条数应为 %d，实际 %d" % (g, n, len(by_group[g]))

    lines = []
    lines.append("<!-- 由 scripts/docs/build_sprint_acceptance.py 生成；状态列由验收执行人更新，")
    lines.append("     其余列的改动请改数据源后重跑 build。统计以 read_sprint_acceptance.py 输出为准。 -->")
    lines.append("")
    lines.append("# 冲刺验收表 · R1 收尾 + R2 产品地基")
    lines.append("")
    lines.append("> 冲刺窗口：2026-10-17 ～ 2026-10-24（R1 收尾 + R2 Phase 0.1/0.2）· 基线提交 %s 起计" % SPRINT_BASELINE)
    lines.append("> 构建：%s · 共 %d 项（A %d / B %d / C %d）" % (
        BUILD_DATE, len(items),
        len(by_group["A"]), len(by_group["B"]), len(by_group["C"])))
    lines.append(">")
    lines.append("> 列口径：验证方式 auto=命令可复跑 / manual=人工核对 / external=外部系统；")
    lines.append("> 证据分级 verified=自动命令证据 / confirmed=人工确认 / speculated=未验证（初始态）；")
    lines.append("> 状态 pending / partial / passed，passed 需附日期与执行人，如 `passed 2026-10-24 by controller`；")
    lines.append("> 项通过后证据分级同步升级：auto → verified，manual/external → confirmed。")

    for g, title, _n in GROUPS:
        lines.append("")
        lines.append("## " + title)
        lines.append("")
        if g == "B":
            lines.append("> 命令里的 `-k` 关键字是入口约定；R2 测试合入后若实际命名不同，以实际测试文件为准（关键字可等价替换），期望列不变。")
            lines.append("")
        lines.append(row_line(HEADER_CELLS))
        lines.append("|---|---|---|---|---|---|---|")
        for no, name, cmd, expect, method, evidence, status in by_group[g]:
            assert method in METHODS, (no, method)
            assert evidence in EVIDENCE, (no, evidence)
            lines.append(row_line((no, name, cmd, expect, method, evidence, status)))

    lines.append("")
    return "\n".join(lines)


def write_md(path=None, items=None):
    if path is None:
        path = OUT
    if items is None:
        items = ITEMS
    text = render(items)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # LF、无 BOM：与仓库中文文档编码纪律一致
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def build():
    path = write_md()
    print("written:", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    build()
