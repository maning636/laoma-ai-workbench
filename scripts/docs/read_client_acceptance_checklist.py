# -*- coding: utf-8 -*-
"""回读《客户端验收清单》Word 表 → 结构化结果。

要点（上一轮踩过的坑）：
  - 结果列是**三个并列框**（□通过 □不通过 □跳过），必须**逐框**判定，
    不能「行内有一个框被勾就整行算通过」。
  - 问题记录表的严重程度同样是三个并列框，也要逐框判定。
  - 主表有**分组行**（跨列合并），解析时要跳过，不能当成数据行。
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts", "docs"))

from docx import Document  # noqa: E402

from _decision_form_common import split_boxes  # noqa: E402

DOC = os.path.join(REPO, "docs", "client-acceptance-checklist.docx")

RESULT_LABELS = ("通过", "不通过", "跳过")
SEVERITY_LABELS = ("阻塞", "严重", "小")


def _cell_text(cell):
    return (cell.text or "").strip()


def _pick(box_text, candidates):
    """在一行里逐框判定，返回命中的那个候选标签（没勾返回 None）。

    ⚠️ 必须**精确匹配**。「通过」是「不通过」的子串，用 `cand in label` 判定
    会把「☑ 不通过」读成「通过」—— 结果全部反着，验收表就成了假闸门。
    所以先试完全相等，再退回前缀匹配。
    """
    hits = []
    for _prefix, label, checked in split_boxes(box_text):
        if not checked:
            continue
        lab = label.strip()
        exact = [c for c in candidates if lab == c]
        if exact:
            hits.append(exact[0])
            continue
        pref = [c for c in candidates if lab.startswith(c)]
        hits.append(pref[0] if pref else lab)
    if not hits:
        return None
    # 多个框同时勾上 → 取第一个（并由上层标记为异常）
    return hits[0]


def parse(path=DOC):
    doc = Document(path)

    # ── §1 主表：找含「编号 / 验收项」表头的表 ──────────────
    items = []
    problems = []
    global_notes = []

    for t in doc.tables:
        head = [_cell_text(c) for c in t.rows[0].cells]
        if head[:2] == ["编号", "验收项"]:
            for r in t.rows[1:]:
                cells = r.cells
                # 合并后的分组行：整行只有一个非空文本
                texts = [_cell_text(c) for c in cells]
                if len(set(texts)) == 1:
                    continue
                no = texts[0]
                if not no or len(no) > 4:
                    continue
                items.append({
                    "no": no,
                    "title": texts[1],
                    "how": texts[2],
                    "expect": texts[3],
                    "result": _pick(texts[4], RESULT_LABELS),
                    "result_raw": texts[4],
                })
        elif head[:2] == ["编号", "对应验收项"]:
            for r in t.rows[1:]:
                texts = [_cell_text(c) for c in r.cells]
                # 空行：编号与现象描述都没填（严重程度列有预置的三个框，不能拿它判空）
                if not texts[0] and not texts[2]:
                    continue
                problems.append({
                    "no": texts[0],
                    "item": texts[1],
                    "desc": texts[2],
                    "severity": _pick(texts[3], SEVERITY_LABELS),
                    "shot": texts[4],
                })

    # ── §3 总批注：标题之后的非空段落 ─────────────────────
    in_notes = False
    seen_heading = False
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if text.startswith("3") and "总批注" in text:
            in_notes = True
            seen_heading = True
            continue
        if seen_heading and in_notes:
            if text.startswith("4"):
                break
            global_notes.append(text)

    done = [i for i in items if i["result"]]
    failed = [i for i in items if i["result"] == "不通过"]
    skipped = [i for i in items if i["result"] == "跳过"]
    pending = [i for i in items if not i["result"]]

    return {
        "file": path,
        "exists": os.path.exists(path),
        "items": items,
        "problems": problems,
        "global_notes": global_notes,
        "summary": {
            "total": len(items),
            "passed": len([i for i in done if i["result"] == "通过"]),
            "failed": len(failed),
            "skipped": len(skipped),
            "pending": len(pending),
            "failed_ids": [i["no"] for i in failed],
            "pending_ids": [i["no"] for i in pending],
            "problem_count": len(problems),
        },
    }


def main():
    r = parse()
    s = r["summary"]
    print("file:", r["file"], "exists =", r["exists"])
    print("items   :", s["total"])
    print("passed  :", s["passed"])
    print("failed  :", s["failed"], s["failed_ids"])
    print("skipped :", s["skipped"])
    print("pending :", s["pending"], s["pending_ids"])
    print("problems:", s["problem_count"])
    for p in r["problems"]:
        print("   -", p["no"], "|", p["item"], "|", p["severity"], "|", p["desc"][:60])
    for n in r["global_notes"]:
        print("note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
