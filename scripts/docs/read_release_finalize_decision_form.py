# -*- coding: utf-8 -*-
"""回读《Prism-Fusion 开源发布收尾 · 待决表》。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\read_release_finalize_decision_form.py
  D:\\dev\\python\\python.exe scripts\\docs\\read_release_finalize_decision_form.py <填好的副本.docx>

不带参数时读仓库里的 docs/release-finalize-decision-form.docx。

输出：结构化 JSON（stdout），便于直接落到发布口径文档与后续动作。
勾选框识别：☑ √ ✓ ✔ ■ ▣ ☒ 等都算「勾上」；同一行多个并列框按框逐个判定
（整行算勾上是错的 —— 上一轮 R4 就是这么炸的）。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _decision_form_common import parse_sections, structure_ok, verify

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(REPO, "docs", "release-finalize-decision-form.docx")

IDS = {"P1", "P2", "P3", "P4", "P5", "P6", "P7"}
SEC_RE = re.compile(r"^(P[1-7])[\s　]")
GLOBAL_HEADING = "3　总快速批注"
END_HEADING = "4　填完之后"
TABLE_ROWS = 8          # 表头 + 7 个待决项


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
    if not ok:
        sys.exit(3)
    print()
    print("== 回读结果 ==")
    print(json.dumps(parse_sections(path, SEC_RE, IDS, GLOBAL_HEADING,
                                    END_HEADING, TABLE_ROWS),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
