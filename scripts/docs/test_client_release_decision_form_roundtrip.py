# -*- coding: utf-8 -*-
"""《客户端发布形态 · 待决表》往返测试：造一份填好的副本 → 回读 → 断言读出的结果一致。

证明「填了能读、读得准」，否则「生成了表」不等于「能读回来」。

重点回归两件上一轮真踩到过的事：
  ① 同一小节里只勾一个框时，别的框必须仍是「未勾」—— 整行算勾上是错的；
  ② 同一行里出现**并列两个框**时，必须按框拆成两个独立选项，
     勾第一个不能让第二个被读成已勾（上一轮 R4 就是这么炸的）。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\test_client_release_decision_form_roundtrip.py
"""
import os
import shutil
import sys

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _decision_form_common import parse_sections, verify  # noqa: E402
from read_client_release_decision_form import (  # noqa: E402
    END_HEADING, GLOBAL_HEADING, IDS, SEC_RE, TABLE_ROWS,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(REPO, "docs", "client-release-decision-form.docx")
TMP = os.path.join(REPO, "tmp", "_roundtrip_client_filled.docx")   # 落在 gitignore 的 tmp/ 下

# 模拟马哥的填写：勾第几个框（按小节内出现顺序）、选择行写什么、批注写什么
FILL = {
    "D1": {"check_box": 0, "choice": "A", "note": "就 ASCII，简单省事"},
    "D2": {"check_box": 0, "choice": "A", "note": "源码包跟官网一起给"},
    "D3": {"check_box": 0, "choice": "A", "note": ""},
    "D4": {"check_box": 2, "choice": "C（分阶段）", "note": "先 A，后面补云端账号"},
    "D5": {"check_box": 0, "choice": "A", "note": ""},
}

SECTION_IDS = ("D1", "D2", "D3", "D4", "D5")


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



def main():
    shutil.copyfile(DEFAULT, TMP)
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

    data = parse_sections(TMP, SEC_RE, IDS, GLOBAL_HEADING, END_HEADING, TABLE_ROWS)
    sec = data["sections"]
    fails = []

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
