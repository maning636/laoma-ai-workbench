# -*- coding: utf-8 -*-
"""回读《Prism-Fusion 客户端发布形态 · 待决表》。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\read_client_release_decision_form.py
  D:\\dev\\python\\python.exe scripts\\docs\\read_client_release_decision_form.py <填好的副本.docx>

不带参数时读仓库里的 docs/client-release-decision-form.docx。

输出：结构化 JSON（stdout），便于直接落到发布口径文档与官网文案。
勾选框识别：☑ √ ✓ ✔ ■ ▣ ☒ 等都算「勾上」；同一行多个并列框按框逐个判定。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _decision_form_common import parse_sections, structure_ok, verify

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(REPO, "docs", "client-release-decision-form.docx")

IDS = {"D1", "D2", "D3", "D4", "D5"}
SEC_RE = re.compile(r"^(D[1-5])[\s　]")
GLOBAL_HEADING = "3　总快速批注"
# 结尾标题有两种：空白待决表是「4　填完之后我会做什么」，
# 2026-10-23 追认后重建的确认表是「4　确认落地清单」。两种都要能读。
END_HEADINGS = ("4　填完之后", "4　确认落地清单")
TABLE_ROWS = 6          # 表头 + 5 个待决项


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    info = verify(path)
    print("== 结构验收 ==")
    for k, v in info.items():
        print("   %-22s %s" % (k, v))
    if not info.get("exists"):
        sys.exit(2)
    ok = structure_ok(info)
    print("   结构验收:", "通过" if ok else "有问题")
    print()
    print("== 回读结果 ==")
    print(json.dumps(parse_sections(path, SEC_RE, IDS, GLOBAL_HEADING,
                                    END_HEADINGS, TABLE_ROWS),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
