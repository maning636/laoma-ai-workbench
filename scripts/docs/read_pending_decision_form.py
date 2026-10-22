"""回读《Prism-Fusion 开源边界 · 第二轮待决表》。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\read_pending_decision_form.py

不带参数时读仓库里的 docs/oss-boundary-round2-decision-form.docx；
也可指定路径读马哥填好的副本。

输出：结构化 JSON（stdout），便于直接落到功能清单文档与 feature gate 矩阵。
勾选框识别：☑ √ ✓ ✔ ■ / [x] 等都算「勾上」。
"""
import io
import json
import os
import re
import sys
import zipfile

from docx import Document

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(REPO, "docs", "oss-boundary-round2-decision-form.docx")

BOX = "□"
CHECK_MARKS = ["☑", "√", "✓", "✔", "■", "▣", "☒", "x", "X"]
SEC_RE = re.compile(r"^(R[1-4])[\s　]")


def is_checked(text):
    """这一行是不是被勾了。"""
    if not text:
        return False
    for m in CHECK_MARKS:
        if m in text[:8]:
            return True
    if re.search(r"\[[xX√✓]\s*\]", text[:8]):
        return True
    return False


def strip_box(text):
    """去掉行首的勾选框与标记，返回纯选项文本。"""
    t = text.strip()
    t = re.sub(r"^[\s　]*[□☑√✓✔■▣☒]?[\s　]*", "", t)
    t = re.sub(r"^[\[\(]?\s*[xX√✓]?\s*[\]\)]?\s*", "", t) if is_checked(text) else t
    return t.strip().strip(".").strip()


def verify(path):
    """结构验收：zip 完整性 + XML 部件可解析 + 关键结构在位。"""
    out = {"file": path, "exists": os.path.exists(path)}
    if not out["exists"]:
        return out
    out["bytes"] = os.path.getsize(path)
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        out["zip_ok"] = bad is None
        names = zf.namelist()
        out["xml_parts"] = len([n for n in names if n.endswith(".xml")])
        import lxml.etree as ET
        fail = []
        for n in names:
            if n.endswith(".xml"):
                try:
                    ET.fromstring(zf.read(n))
                except Exception as e:
                    fail.append("%s: %s" % (n, e))
        out["xml_parse_failures"] = fail
    doc = Document(path)
    out["paragraphs"] = len(doc.paragraphs)
    out["tables"] = len(doc.tables)
    out["table_rows"] = [len(t.rows) for t in doc.tables]
    out["table_cells"] = [sum(len(r.cells) for r in t.rows) for t in doc.tables]
    # 页脚 PAGE 域
    xml = doc.sections[0].footer._element.xml
    out["footer_page_field"] = 'w:instr=" PAGE "' in xml and "<w:t>1</w:t>" in xml
    return out


BOX_CHARS = "□☑√✓✔■▣☒"
BOX_RE = re.compile("[" + BOX_CHARS + "]")


def split_boxes(text):
    """把一行拆成若干个「框 + 选项」。

    一行里可能有并列的多个框（R4 就是：□ 推进　□ 暂缓）。
    必须**逐框**判定勾选状态 —— 只要行内有一个框被勾就整行算勾上，是错的。
    返回 [(行前缀, 选项文本, 是否勾上)]，行内第一个框会带上行前缀作为分组名。
    """
    hits = list(BOX_RE.finditer(text))
    if not hits:
        return []
    prefix = text[:hits[0].start()].strip()
    out = []
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        label = text[h.end():end].strip().lstrip(".、 ").strip()
        out.append((prefix, label, h.group(0) in CHECK_MARKS))
    return out


def parse(path):
    doc = Document(path)
    sections = {}
    cur = None
    state = None
    global_notes = []
    in_global = False
    global_first = True

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        m = SEC_RE.match(text)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, {"context": "", "recommend": "", "options": [],
                                      "checked": [], "unchecked": [], "choice": "", "notes": []})
            state = "ctx"
            in_global = False
            continue
        if text.startswith("3　总快速批注"):
            in_global = True
            global_first = True
            cur = None
            continue
        if text.startswith("4　填完之后"):
            in_global = False
            continue

        if in_global:
            # 标题后的第一段是填写说明，其余才是他写的总规则
            if global_first:
                global_first = False
                continue
            global_notes.append(text)
            continue

        if cur is None:
            continue

        if text.startswith("小节批注"):
            continue
        if text.startswith("→"):
            sections[cur]["choice"] = text.split("：", 1)[-1].strip().strip("_").strip()
            state = "notes"
            continue
        if text.startswith("💡"):
            sections[cur]["recommend"] = text[1:].strip()
            state = "opt"
            continue
        if BOX in text or is_checked(text):
            for prefix, label, checked in split_boxes(text):
                if not label:
                    continue
                sections[cur]["options"].append(
                    {"group": prefix, "label": label, "checked": checked})
                key = "checked" if checked else "unchecked"
                sections[cur][key].append(label)
            state = "opt"
            continue
        if state == "ctx":
            sections[cur]["context"] = text
            state = "opt"
            continue
        if state == "notes":
            sections[cur]["notes"].append(text)

    # 速览表里的「我的选择」列（若他填在表里）
    for t in doc.tables:
        if len(t.rows) == 5 and len(t.columns) == 4:
            for r in t.rows[1:]:
                no = r.cells[0].text.strip()
                if re.fullmatch(r"R[1-4]", no):
                    v = r.cells[3].text.strip()
                    if v and not sections.get(no, {}).get("choice"):
                        sections.setdefault(no, {"context": "", "recommend": "", "options": [],
                                                 "checked": [], "unchecked": [], "choice": "", "notes": []})
                        sections[no]["choice"] = v

    return {"sections": sections, "global_notes": global_notes}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    info = verify(path)
    print("== 结构验收 ==")
    for k, v in info.items():
        print("   %-22s %s" % (k, v))
    if not info.get("exists"):
        sys.exit(2)
    ok = (info.get("zip_ok") and not info.get("xml_parse_failures")
          and info.get("footer_page_field"))
    print("   结构验收:", "通过" if ok else "有问题")
    print()
    print("== 回读结果 ==")
    print(json.dumps(parse(path), ensure_ascii=False, indent=1))
