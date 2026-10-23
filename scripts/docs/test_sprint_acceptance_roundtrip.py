# -*- coding: utf-8 -*-
"""《冲刺验收表》往返测试。

与 client-acceptance roundtrip 同粒度，验四件事：
  1) build → read 全字段往返一致（含转义地狱单元格：管道/反斜杠/中文）；
  2) 注入验收结果（pending → passed 日期+执行人 + 证据分级升级）→ 读回一致，
     统计从 20 pending 变成 19 pending + 1 passed；
  3) 反向自测：篡改数据列后 read 必须报出差异，证明读取器不是假闸门；
  4) 坏表拒识：列数不对/非法枚举/重复编号的 md，parse 必须抛错而非吞掉。

全程在临时目录跑（redirect OUT/DOC），不动仓库里的真实 md。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts", "docs"))

import build_sprint_acceptance as builder  # noqa: E402
import read_sprint_acceptance as reader  # noqa: E402

# 转义压力样例：管道、反斜杠、${var}、命令替换、中文、空元素
ESCAPED_CELL_ITEM = (
    "T9", "转义压力||\\path\\to|weird",
    "echo 'a|b' && cmd \\| grep",
    "期望 \\back\\ | slash || pair",
    "auto", "speculated", "pending",
)


def _assert_items_equal(src, back, ctx):
    assert len(src) == len(back), "%s: 条目数 %d != %d" % (ctx, len(back), len(src))
    for s, b in zip(src, back):
        assert b["no"] == s[0], (ctx, b["no"])
        assert b["title"] == s[1], (ctx, s[0], "title", repr(b["title"]), repr(s[1]))
        assert b["cmd"] == s[2], (ctx, s[0], "cmd", repr(b["cmd"]), repr(s[2]))
        assert b["expect"] == s[3], (ctx, s[0], "expect", repr(b["expect"]), repr(s[3]))
        assert b["method"] == s[4], (ctx, s[0], "method")
        assert b["evidence"] == s[5], (ctx, s[0], "evidence")
        assert b["status"]["state"] == s[6].split()[0], (ctx, s[0], "state")


def _write_and_parse(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return reader.parse(path)


def _expect_parse_error(path, text, needle, ctx):
    try:
        _write_and_parse(path, text)
    except ValueError as e:
        assert needle in str(e), "%s: 报错 %r 不含 %r" % (ctx, str(e), needle)
        return
    raise AssertionError("%s: 坏表未被拒识（未抛 ValueError）" % ctx)


def main():
    tmpdir = tempfile.mkdtemp(prefix="sprint_acc_roundtrip_")
    md_path = os.path.join(tmpdir, "SPRINT-ACCEPTANCE-R1R2.md")
    bad_path = os.path.join(tmpdir, "bad.md")
    orig_out, orig_doc = builder.OUT, reader.DOC
    builder.OUT = md_path
    reader.DOC = md_path
    try:
        # ── 1) build → read 全字段往返一致 ───────────────────
        builder.build()
        r = reader.parse(md_path)
        assert r["exists"], "生成的 md 不存在"
        _assert_items_equal(builder.ITEMS, r["items"], "roundtrip")
        s = r["summary"]
        assert s["total"] == 20 and s["pending"] == 20 and s["passed"] == 0, s
        assert s["by_group"] == {"A": {"total": 10, "passed": 0, "pending": 10},
                                 "B": {"total": 6, "passed": 0, "pending": 6},
                                 "C": {"total": 4, "passed": 0, "pending": 4}}, s["by_group"]
        assert builder.esc("|a\\b|") == "\\|a\\\\b\\|", builder.esc("|a\\b|")
        print("[1] PASS —— 20 项七列全字段往返一致（初始全 pending）")

        # ── 2) 注入验收结果 → 读回一致 ───────────────────────
        mutated = [list(it) for it in builder.ITEMS]
        for row in mutated:
            if row[0] == "A2":
                row[5] = "verified"
                row[6] = "passed 2026-10-24 by controller"
        builder.write_md(md_path, mutated)
        r2 = reader.parse(md_path)
        _assert_items_equal(mutated, r2["items"], "injected")
        s2 = r2["summary"]
        assert s2["passed"] == 1 and "A2" in s2["passed_ids"] and s2["pending"] == 19, s2
        a2 = next(i for i in r2["items"] if i["no"] == "A2")
        assert a2["status"]["date"] == "2026-10-24" and a2["status"]["owner"] == "controller", a2["status"]
        assert s2["passed_unupgraded_evidence"] == [], s2["passed_unupgraded_evidence"]
        print("[2] PASS —— 注入 passed（日期+执行人+证据升级）读回逐字段一致")

        # passed 但证据没升级 → 必须出现在 warn 统计里
        mutated2 = [list(it) for it in builder.ITEMS]
        for row in mutated2:
            if row[0] == "A3":
                row[6] = "passed 2026-10-24 by controller"
        builder.write_md(md_path, mutated2)
        r2b = reader.parse(md_path)
        assert r2b["summary"]["passed_unupgraded_evidence"] == ["A3"], r2b["summary"]
        print("[2] PASS —— passed 未升级证据分级会被 warn 统计点名")

        # ── 3) 反向自测：篡改数据列必须报出差异 ──────────────
        mutated3 = [list(it) for it in builder.ITEMS]
        for row in mutated3:
            if row[0] == "B5":
                row[3] = "ALL TESTS PASSED（被篡改）"
        builder.write_md(md_path, mutated3)
        r3 = reader.parse(md_path)
        b5 = next(i for i in r3["items"] if i["no"] == "B5")
        b5_baseline_expect = next(it[3] for it in builder.ITEMS if it[0] == "B5")
        assert b5["expect"] != b5_baseline_expect, "篡改未被读出（假闸门）"
        assert b5["expect"] == "ALL TESTS PASSED（被篡改）", b5["expect"]
        print("[3] PASS —— 篡改能被读出，读取器不是假闸门")

        # ── 4) 坏表拒识（宁可报错不能吞） ────────────────────
        good = builder.render(builder.ITEMS)
        # 4a 列数不对：去掉一个分隔符列
        bad1 = good.replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|", 1)
        _expect_parse_error(md_path, bad1, "列数", "4a 表头列数")
        # 4b 非法枚举：验证方式写成中文
        bad2 = good.replace("| auto | speculated | pending |", "| 自动 | speculated | pending |", 1)
        _expect_parse_error(md_path, bad2, "验证方式非法", "4b 非法枚举")
        # 4c 重复编号
        bad3 = good.replace("| A2 |", "| A1 |", 1)
        _expect_parse_error(md_path, bad3, "编号重复", "4c 重复编号")
        # 4d 非法状态
        bad4 = good.replace("| auto | speculated | pending |", "| auto | speculated | done |", 1)
        _expect_parse_error(md_path, bad4, "状态列无法解析", "4d 非法状态")
        # 4e 带 BOM 的 md 必须被拒识（BOM 走独立于状态解析的编码纪律检查）
        _expect_parse_error(md_path, "\ufeff" + good, "BOM", "4e BOM")
        print("[4] PASS —— 列数/枚举/重复编号/坏状态/BOM 全部拒识")

        # ── 5) 转义压力样例全链路 ────────────────────────────
        # 替换 A1 整行为含管道/反斜杠的压力内容（编号保持 A1，组计数不受影响）
        stressed = [list(it) for it in builder.ITEMS]
        for idx, row in enumerate(stressed):
            if row[0] == "A1":
                stressed[idx] = list(ESCAPED_CELL_ITEM)
                stressed[idx][0] = "A1"
        builder.write_md(md_path, stressed)
        rs = reader.parse(md_path)
        a1 = next(i for i in rs["items"] if i["no"] == "A1")
        assert a1["title"] == ESCAPED_CELL_ITEM[1], (a1["title"], ESCAPED_CELL_ITEM[1])
        assert a1["cmd"] == ESCAPED_CELL_ITEM[2], (a1["cmd"], ESCAPED_CELL_ITEM[2])
        assert a1["expect"] == ESCAPED_CELL_ITEM[3], (a1["expect"], ESCAPED_CELL_ITEM[3])
        print("[5] PASS —— 管道/反斜杠转义单元格全链路还原一致")

        print("ALL TESTS PASSED")
        return 0
    finally:
        builder.OUT = orig_out
        reader.DOC = orig_doc
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
