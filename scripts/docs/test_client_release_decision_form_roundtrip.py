# -*- coding: utf-8 -*-
"""《客户端发布形态 · 待决表》往返测试：造一份填好的副本 → 回读 → 断言读出的结果一致。

证明「填了能读、读得准」，否则「生成了表」不等于「能读回来」。

重点回归两件上一轮真踩到过的事：
  ① 同一小节里只勾一个框时，别的框必须仍是「未勾」—— 整行算勾上是错的；
  ② 同一行里出现**并列两个框**时，必须按框拆成两个独立选项，
     勾第一个不能让第二个被读成已勾（上一轮 R4 就是这么炸的）。

本轮（2026-10-23 追认后）新增两条：
  ③ 仓库里的默认表已是**确认态**（D1=A D2=A D3=B D4=A D5=A），
     回读必须读出五项各恰好一个勾 —— 这是 P4=A 的落地自证；
  ④ 往返测试必须从**空白态**出发（builder --blank），不能再拿确认态当底，
     否则会重演「在已勾的框上再勾一个」的假失败。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\test_client_release_decision_form_roundtrip.py
"""
import os
import shutil
import subprocess
import sys

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _decision_form_common import parse_sections, verify  # noqa: E402
from read_client_release_decision_form import (  # noqa: E402
    END_HEADINGS, GLOBAL_HEADING, IDS, SEC_RE, TABLE_ROWS,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(REPO, "docs", "client-release-decision-form.docx")
BUILDER = os.path.join(REPO, "scripts", "docs", "build_client_release_decision_form.py")
TMP = os.path.join(REPO, "tmp", "_roundtrip_client_filled.docx")   # 落在 gitignore 的 tmp/ 下
BLANK = os.path.join(REPO, "tmp", "_blank_client_release_form.docx")

# 2026-10-23 马哥在《开源发布收尾 · 待决表》P4=A 的追认结果
CONFIRMED = {"D1": "A", "D2": "A", "D3": "B", "D4": "A", "D5": "A"}

# 模拟马哥的填写：勾第几个框（按小节内出现顺序）、选择行写什么、批注写什么
FILL = {
    "D1": {"check_box": 0, "choice": "A", "note": "就 ASCII，简单省事"},
    "D2": {"check_box": 0, "choice": "A", "note": "源码包跟官网一起给"},
    "D3": {"check_box": 0, "choice": "A", "note": ""},
    "D4": {"check_box": 2, "choice": "C（分阶段）", "note": "先 A，后面补云端账号"},
    "D5": {"check_box": 0, "choice": "A", "note": ""},
}

SECTION_IDS = ("D1", "D2", "D3", "D4", "D5")


def build_blank_form():
    """用 builder 的 --blank 重建空白待决表。

    为什么不用仓库里的默认表当底：默认表已经是确认态（D1–D5 都勾好了），
    在已勾的框上再填一遍会读到两个勾，测的就不是「填了能读」而是「填了会打架」。
    """
    os.makedirs(os.path.dirname(BLANK), exist_ok=True)
    if os.path.exists(BLANK):
        os.remove(BLANK)
    r = subprocess.run(
        [sys.executable, BUILDER, "--blank", "--out", BLANK],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, "builder --blank 失败:\n%s\n%s" % (r.stdout, r.stderr)
    assert os.path.exists(BLANK), "builder --blank 没产出文件"
    return BLANK


def replace_nth_box(paragraph, n):
    """把段落里第 n 个「□」换成「☑」，返回是否成功。

    只在**本地副本**上跳过已数过的框，绝不能改 run 里未命中的框 ——
    否则未勾的框被改坏，回读时就看不出它没被勾。
    """
    idx = 0
    for r in paragraph.runs:
        t = r.text
        pos = t.find("□")
        while pos >= 0:
            if idx == n:
                r.text = t[:pos] + "☑" + t[pos + 1:]
                return True
            idx += 1
            t = t[:pos] + "\x00" + t[pos + 1:]   # 仅本地副本
            pos = t.find("□", pos + 1)
    return False


def fill(doc, no, spec):
    cur = None
    state = None
    box_index = 0
    for p in doc.paragraphs:
        text = p.text.strip()
        if text.startswith(no + "　"):
            cur = no
            state = "ctx"
            continue
        if cur != no:
            continue
        if text[:2] in SECTION_IDS and "　" in text[:4]:
            break  # 下一个小节
        if text.startswith("→"):
            if spec["choice"] and p.runs:
                head = p.text.strip().split("：", 1)[0].split("→", 1)[-1].strip()
                p.runs[0].text = "→ " + head + "：" + spec["choice"]
                for r in p.runs[1:]:
                    r.text = ""
            state = "notes"
            continue
        if "□" in text:
            n = text.count("□")
            if spec["check_box"] >= box_index and spec["check_box"] < box_index + n:
                replace_nth_box(p, spec["check_box"] - box_index)
            box_index += n
            continue
        if state == "notes" and spec["note"]:
            if not p.text.strip():
                p.add_run(spec["note"])
                spec["note"] = ""
            continue
        if state == "ctx":
            state = "opt"


def inject_parallel_box(doc, no):
    """在指定小节的最后一个选项行**后面**塞一行「并列两个框」，用来回归逐框判定。

    真实表格里一行一个框，这条是故意造的**最坏情况**：
    行内两个框，只勾第一个时，第二个必须读成未勾。

    注意插入点必须在小节标题**之后**：插到标题前会被解析成上一个小节的选项。
    """
    anchor = None
    in_sec = False
    for p in doc.paragraphs:
        text = p.text.strip()
        if text.startswith(no + "　"):
            in_sec = True
            continue
        if not in_sec:
            continue
        if text[:2] in SECTION_IDS and "　" in text[:4]:
            break  # 下一个小节
        if text.startswith("→"):
            break
        if "□" in text:
            anchor = p
    if anchor is None:
        raise AssertionError("找不到小节 " + no + " 的选项行")
    new_p = doc.add_paragraph("□ 甲方案（第一个）　　□ 乙方案（第二个）")
    anchor._p.addnext(new_p._p)
    # 只勾并列行的第一个框
    assert replace_nth_box(new_p, 0), "并列行的第一个框没勾上"


def check_confirmed_form():
    """回归 ③：仓库默认表（确认态）必须能读出五项各恰好一个勾。

    这是 P4=A 的落地自证 —— 表里的 D1–D5 不是「空着的待决」，
    而是「已按实际落地追认的记录」。读不出 / 读出两个勾都算回归。
    """
    fails = []
    info = verify(DEFAULT)
    if not (info.get("zip_ok") and not info.get("xml_parse_failures")
            and info.get("footer_page_field")):
        fails.append("确认态默认表结构验收没过: %s" % info)
    data = parse_sections(DEFAULT, SEC_RE, IDS, GLOBAL_HEADING, END_HEADINGS, TABLE_ROWS)
    sec = data["sections"]
    for no in SECTION_IDS:
        s = sec.get(no)
        if s is None:
            fails.append("确认态默认表里 %s 没被解析出来" % no)
            continue
        checked = [o for o in s.get("options", []) if o["checked"]]
        if len(checked) != 1:
            fails.append("%s 确认态应恰好一个勾，实际 %d 个: %s"
                         % (no, len(checked), [o["label"][:26] for o in checked]))
            continue
        letter = checked[0]["label"].split(".")[0].strip()
        if letter != CONFIRMED[no]:
            fails.append("%s 确认态勾错：期望 %s 实际 %s" % (no, CONFIRMED[no], letter))
        choice = (s.get("choice") or "").strip()
        if not choice.startswith(CONFIRMED[no]):
            fails.append("%s 「我的选择」读错：期望以 %s 开头，实际 %r"
                         % (no, CONFIRMED[no], choice))
    notes = data.get("global_notes") or []
    if not any("D1=A" in n for n in notes):
        fails.append("确认态总批注区没读到追认记录（notes=%s）" % notes)
    return fails


def main():
    fails = check_confirmed_form()
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("结论: 确认态默认表回归失败 %d 项" % len(fails))
        sys.exit(1)
    print("确认态默认表回归: OK（D1–D5 各恰好一个勾，与 P4=A 一致）")
    print()

    shutil.copyfile(build_blank_form(), TMP)
    doc = Document(TMP)
    for no, spec in FILL.items():
        fill(doc, no, spec)
    # 并列框回归：插到 D5 开头，只勾第一个
    inject_parallel_box(doc, "D5")
    doc.save(TMP)
    print("已造填好的副本:", TMP, os.path.getsize(TMP), "bytes")

    info = verify(TMP)
    assert info["zip_ok"], "zip 不完整"
    assert not info["xml_parse_failures"], info["xml_parse_failures"]
    assert info["footer_page_field"], "页脚 PAGE 域缺失"
    print("结构验收: OK（zip 完整 / %d 个 XML 部件全解析 / PAGE 域在位）" % info["xml_parts"])

    data = parse_sections(TMP, SEC_RE, IDS, GLOBAL_HEADING, END_HEADINGS, TABLE_ROWS)
    sec = data["sections"]

    for no, spec in FILL.items():
        s = sec.get(no)
        if s is None:
            fails.append("%s 未被解析出来" % no)
            continue
        all_opts = s.get("options", [])
        # 注入的并列框单独拎出来，不参与「本节只勾了一个」的判定
        opts = [o for o in all_opts if "方案（第" not in o["label"]]
        if len(opts) <= spec["check_box"]:
            fails.append("%s 框数不足: %s" % (no, opts))
            continue
        if not opts[spec["check_box"]]["checked"]:
            fails.append("%s 第 %d 个框应勾未勾: %s" % (no, spec["check_box"], opts[spec["check_box"]]))
        for i, o in enumerate(opts):
            if i != spec["check_box"] and o["checked"]:
                fails.append("%s 第 %d 个框被误判为已勾: %s" % (no, i, o))
        if spec["choice"] and s["choice"] != spec["choice"]:
            fails.append("%s 选择读错: 期望 %r 实际 %r" % (no, spec["choice"], s["choice"]))
        if spec["note"] and spec["note"] not in " ".join(s["notes"]):
            fails.append("%s 批注没读到: %s" % (no, s["notes"]))

    # 并列框：必须拆成两个独立选项，且只有第一个被勾
    d5 = sec.get("D5", {})
    labels = [o["label"] for o in d5.get("options", [])]
    if not any("甲方案" in l for l in labels) or not any("乙方案" in l for l in labels):
        fails.append("并列框没拆开: %s" % labels)
    else:
        jia = [o for o in d5["options"] if "甲方案" in o["label"]][0]
        yi = [o for o in d5["options"] if "乙方案" in o["label"]][0]
        if not jia["checked"]:
            fails.append("并列框「甲方案」应勾未勾: %s" % jia)
        if yi["checked"]:
            fails.append("并列框「乙方案」被误判为已勾: %s" % yi)

    print()
    print("== 回读结果（节选） ==")
    for no in SECTION_IDS:
        s = sec.get(no, {})
        print("  %s choice=%r checked=%s" % (
            no, s.get("choice"),
            [o["label"][:22] for o in s.get("options", []) if o["checked"]]))
        print("     unchecked=%d 项" % len(s.get("unchecked", [])))
    print()
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("结论: 往返测试失败 %d 项" % len(fails))
        sys.exit(1)
    print("结论: 往返测试全部通过 PASS（勾选 / 未勾互不干扰 / 选择 / 批注 / 并列框分组 均读得准）")


if __name__ == "__main__":
    main()
