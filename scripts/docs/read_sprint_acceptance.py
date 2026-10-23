# -*- coding: utf-8 -*-
"""回读《冲刺验收表 · R1 收尾 + R2 产品地基》md 表 → 结构化结果。

与 client-acceptance 的 reader 同职责，读的是 GFM 表格而不是 docx：
  - 按「未被转义的 |」切列，再按 build 侧转义约定还原（\\ → \\，\\| → |）；
  - 状态列解析出 state（pending/partial/passed），passed 时附日期与执行人；
  - 严格校验（列数 / 枚举值 / 编号重复 / 组计数），坏行直接抛错 ——
    这个 reader 是收工闸门，宁可报错也不能「永远输出 OK」。

统计口径：items 总数 / passed / partial / pending（含各状态编号清单），
自运行打统计摘要即可（build 才负责 ALL TESTS PASSED 之外的事，
往返断言在 test_sprint_acceptance_roundtrip.py）。
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(REPO, "docs", "handover", "SPRINT-ACCEPTANCE-R1R2.md")

METHODS = ("auto", "manual", "external")
EVIDENCE = ("verified", "confirmed", "speculated")
STATES = ("pending", "partial", "passed")

#: 状态列合法形态：pending / partial / passed <YYYY-MM-DD> by <owner>
_STATUS_RE = re.compile(
    r"^(pending|partial|passed)"
    r"(?:\s+(\d{4}-\d{2}-\d{2})\s+by\s+(\S+))?$"
)

_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_UNESCAPE = re.compile(r"\\(.)")

GROUP_TITLES = {
    "A": "组 A · R1 收尾验收",
    "B": "组 B · R2 产品功能验收",
    "C": "组 C · 文档与卫生门",
}
GROUP_COUNTS = {"A": 10, "B": 6, "C": 4}


def unescape(text: str) -> str:
    """build 侧 esc() 的逆：\\\\ → \\，\\| → |。"""
    return _UNESCAPE.sub(r"\1", text)


def _split_row(line: str):
    """`| a | b |` → ['a','b']（按未被转义的管道切，两侧边界列去掉）。"""
    parts = _CELL_SPLIT.split(line.strip())
    # parts[0]/parts[-1] 是行首行尾管道之外的空串
    cells = [p.strip() for p in parts[1:-1]]
    return [unescape(c) for c in cells]


def _parse_status(raw: str):
    m = _STATUS_RE.match(raw.strip())
    if not m:
        raise ValueError("状态列无法解析: %r（合法：pending/partial/passed <date> by <owner>）" % raw)
    state, date, owner = m.group(1), m.group(2), m.group(3)
    if state == "passed" and not date:
        raise ValueError("passed 必须附日期与执行人: %r" % raw)
    return {"state": state, "date": date, "owner": owner, "raw": raw.strip()}


def parse(path=None):
    if path is None:
        path = DOC
    if not os.path.exists(path):
        return {"file": path, "exists": False, "items": [], "summary": {}}

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if text.startswith("\ufeff"):
        raise ValueError("文件带 BOM，违反编码纪律: %s" % path)

    items = []
    seen = set()
    in_table = False
    header_seen = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = _split_row(stripped)
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            if len(cells) != 7:
                raise ValueError("分隔行列数 %d ≠ 7: %r" % (len(cells), line))
            in_table = header_seen
            continue
        if cells[:2] == ["编号", "验收项"]:
            if len(cells) != 7:
                raise ValueError("表头列数 %d ≠ 7: %r" % (len(cells), line))
            in_table = True
            header_seen = True
            continue
        if not (in_table and header_seen):
            continue
        if len(cells) != 7:
            raise ValueError("数据行列数 %d ≠ 7: %r" % (len(cells), line))
        no, title, cmd, expect, method, evidence, status_raw = cells
        if no in seen:
            raise ValueError("编号重复: %s" % no)
        seen.add(no)
        if method not in METHODS:
            raise ValueError("%s 验证方式非法: %r" % (no, method))
        if evidence not in EVIDENCE:
            raise ValueError("%s 证据分级非法: %r" % (no, evidence))
        items.append({
            "no": no,
            "group": no[0],
            "title": title,
            "cmd": cmd,
            "expect": expect,
            "method": method,
            "evidence": evidence,
            "status": _parse_status(status_raw),
        })

    for g, n in GROUP_COUNTS.items():
        got = len([i for i in items if i["group"] == g])
        if got != n:
            raise ValueError("%s 应 %d 条，实际 %d 条" % (GROUP_TITLES[g], n, got))

    passed = [i for i in items if i["status"]["state"] == "passed"]
    partial = [i for i in items if i["status"]["state"] == "partial"]
    pending = [i for i in items if i["status"]["state"] == "pending"]
    # passed 但证据分级没升级 → 提醒（不抛错，统计里可见）
    unupgraded = [i["no"] for i in passed
                  if not (i["method"] == "auto" and i["evidence"] == "verified"
                          or i["method"] != "auto" and i["evidence"] == "confirmed")]

    return {
        "file": path,
        "exists": True,
        "items": items,
        "summary": {
            "total": len(items),
            "passed": len(passed),
            "partial": len(partial),
            "pending": len(pending),
            "passed_ids": [i["no"] for i in passed],
            "partial_ids": [i["no"] for i in partial],
            "pending_ids": [i["no"] for i in pending],
            "passed_unupgraded_evidence": unupgraded,
            "by_group": {g: {
                "total": len([i for i in items if i["group"] == g]),
                "passed": len([i for i in passed if i["group"] == g]),
                "pending": len([i for i in pending if i["group"] == g]),
            } for g in GROUP_COUNTS},
        },
    }


def main():
    r = parse()
    if not r["exists"]:
        print("file:", r["file"], "MISSING —— 先跑 build_sprint_acceptance.py")
        return 1
    s = r["summary"]
    print("file   :", r["file"])
    print("items  :", s["total"])
    print("passed :", s["passed"], s["passed_ids"])
    print("partial:", s["partial"], s["partial_ids"])
    print("pending:", s["pending"], s["pending_ids"])
    if s["passed_unupgraded_evidence"]:
        print("warn   : passed 但证据分级未升级 ->", s["passed_unupgraded_evidence"])
    for g, info in s["by_group"].items():
        print("group %s: total %d / passed %d / pending %d" % (g, info["total"], info["passed"], info["pending"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
