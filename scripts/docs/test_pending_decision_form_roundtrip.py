"""《第二轮待决表》往返测试：造一份填好的副本 → 回读 → 断言读出的结果一致。

证明「填了能读、读得准」，否则"生成了表"不等于"能读回来"。

重点回归：R4 一行里有**并列的两个框**（□ 推进　□ 暂缓），
只勾前一个时，后一个必须仍是「未勾」—— 整行算勾上是错的。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\test_pending_decision_form_roundtrip.py
"""
import io
import json
import os
import shutil
import sys

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_pending_decision_form import DEFAULT, parse, verify  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(REPO, "tmp", "_roundtrip_filled.docx")   # 落在 gitignore 的 tmp/ 下

# 模拟马哥的填写：勾第几个框（按小节内出现顺序）、选择行写什么、批注写什么
FILL = {
    "R1": {"check_box": 0, "choice": "A", "note": "先不绑，卖出去再看盗版情况"},
    "R2": {"check_box": 0, "choice": "A", "note": "stub 记得给明确报错文案"},
    "R3": {"check_box": 0, "choice": "A", "note": ""},
    "R4": {"check_box": 0, "choice": "凭证放 D:\\secrets\\prod\\.env", "note": ""},
}
BOX_CHARS = "□☑√✓✔■▣☒"


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
        if text[:2] in ("R1", "R2", "R3", "R4") and "　" in text[:4]:
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


def main():
    shutil.copyfile(DEFAULT, TMP)
    doc = Document(TMP)
    for no, spec in FILL.items():
        fill(doc, no, spec)
    doc.save(TMP)
    print("已造填好的副本:", TMP, os.path.getsize(TMP), "bytes")

    info = verify(TMP)
    assert info["zip_ok"], "zip 不完整"
    assert not info["xml_parse_failures"], info["xml_parse_failures"]
    assert info["footer_page_field"], "页脚 PAGE 域缺失"
    print("结构验收: OK（zip 完整 / %d 个 XML 部件全解析 / PAGE 域在位）" % info["xml_parts"])

    data = parse(TMP)
    sec = data["sections"]
    fails = []

    for no, spec in FILL.items():
        s = sec.get(no)
        if s is None:
            fails.append("%s 未被解析出来" % no)
            continue
        opts = s.get("options", [])
        if len(opts) <= spec["check_box"]:
            fails.append("%s 框数不足: %s" % (no, opts))
            continue
        if not opts[spec["check_box"]]["checked"]:
            fails.append("%s 第 %d 个框应勾未勾: %s" % (no, spec["check_box"], opts[spec["check_box"]]))
        # 其它框必须仍是未勾（并列框互不影响）
        for i, o in enumerate(opts):
            if i != spec["check_box"] and o["checked"]:
                fails.append("%s 第 %d 个框被误判为已勾: %s" % (no, i, o))
        if spec["choice"] and s["choice"] != spec["choice"]:
            fails.append("%s 选择读错: 期望 %r 实际 %r" % (no, spec["choice"], s["choice"]))
        if spec["note"] and spec["note"] not in " ".join(s["notes"]):
            fails.append("%s 批注没读到: %s" % (no, s["notes"]))

    # R4：并列的「推进 / 暂缓」必须拆成独立选项，且只勾了推进
    r4 = sec.get("R4", {})
    labels = [o["label"] for o in r4.get("options", [])]
    if not any("推进" in l for l in labels) or not any("暂缓" in l for l in labels):
        fails.append("R4 并列选项没拆开: %s" % labels)
    checked_r4 = [o["label"] for o in r4.get("options", []) if o["checked"]]
    if len(checked_r4) != 1 or "推进" not in checked_r4[0]:
        fails.append("R4 勾选状态不对: checked=%s" % checked_r4)
    for o in r4.get("options", []):
        if "暂缓" in o["label"] and o["checked"]:
            fails.append("R4「暂缓」被误判为已勾: %s" % o)

    print()
    print("== 回读结果（节选） ==")
    for no in ("R1", "R2", "R3", "R4"):
        s = sec.get(no, {})
        print("  %s choice=%r checked=%s" % (no, s.get("choice"),
                                            [o["label"][:18] for o in s.get("options", []) if o["checked"]]))
        print("     unchecked=%d 项" % len(s.get("unchecked", [])))
    print()
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("结论: 往返测试失败 %d 项" % len(fails))
        sys.exit(1)
    print("结论: 往返测试全部通过 ✅（勾选 / 未勾互不干扰 / 选择 / 批注 / 并列框分组 均读得准）")


if __name__ == "__main__":
    main()
