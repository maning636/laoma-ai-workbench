# -*- coding: utf-8 -*-
"""生成《Prism-Fusion 客户端发布形态 · 待决表》Word 文档。

这一轮要拍的是「单一客户端」落地后的五个岔路口：
  D1 安装包命名（官网下载链接显示的名字，也是自动更新链路的锚）
  D2 客户端 license 元数据口径（AGPL-3.0 与 Hermes 商业内核的关系）
  D3 开源交付形态（AGPL 要求的「提供对应源码」怎么给）
  D4 完整版怎么解锁（注册码 / 云端账号 / 两者）
  D5 合并后约 610 MB 的安装包体积能不能接受

两种生成态：
  默认（确认态）—— 2026-10-23 马哥在《开源发布收尾 · 待决表》P4 选了 A，
  「全部按实际落地确认（D1=A　D2=A　D3=B　D4=A　D5=A）」。
  代码早已按选项落地并对公网生效，这张表当时只差一句追认，
  所以现在生成的是**已确认记录**：选项框按结果打勾，每项下面写明
  实际落地的事实（可当场核对的字节数 / 链接 / 配置值）。
  --blank（空白态）—— 重建当初的空白待决表，往返测试与历史对照用。

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\build_client_release_decision_form.py
  D:\\dev\\python\\python.exe scripts\\docs\\build_client_release_decision_form.py --blank
  D:\\dev\\python\\python.exe scripts\\docs\\build_client_release_decision_form.py --blank --out <路径.docx>

为什么确认态写进 builder 而不是直接改 .docx 二进制：
  表要能随时重建、能回读自证，而且「哪天拍的、依据哪张表拍的」必须
  留在可审计的文本里 —— 直接改二进制会让这两件事都无从查证。

依赖：python-docx（装在 D 盘 dev python，不写 C 盘、不动项目 venv）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from _decision_form_common import (
    BOX, C_DARK, C_GRAY, C_HDRBG, C_MID, FONT_HEAD,
    blank_lines, cell_text, heading, new_document, no_split,
    para, repeat_header, set_widths, shade, table_borders,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "docs", "client-release-decision-form.docx")
FOOTER = "Prism-Fusion 客户端发布形态 · 待决表（已确认）　v1.1　2026-10-24"
BLANK_MODE = False

# ---------------------------------------------------------------------------
# 确认态数据（2026-10-23 追认）
#
# 依据：马哥在《开源发布收尾 · 待决表》P4 选 A —— 「全部按实际落地确认
# （D1=A　D2=A　D3=B　D4=A　D5=A）」。其中 D3 与本表当初的建议不同
# （当初建议 A ＝ 官网下载区放源码包，实际落地选了 B ＝ 公开 GitHub 仓），
# 按实际落地追认。
# ---------------------------------------------------------------------------
CONFIRMED = {
    "D1": "A",
    "D2": "A",
    "D3": "B",
    "D4": "A",
    "D5": "A",
}

# 每项实际落地的事实（追认依据，全部来自 1.1.5 的真实产物与仓库配置）
LANDING = {
    "D1": "已落地：desktop-electron/package.json 的 build.artifactName = "
         "LaomaAI-${version}-setup.${ext}；1.1.5 实际产物 LaomaAI-1.1.5-setup.exe"
         "（639,437,816 B，纯 ASCII，官网按钮、Release 资产、latest.yml 三处同名）。",
    "D2": "已落地：客户端 license 字段 AGPL-3.0，LICENSE.txt 为 AGPL 全文，"
         "NOTICE.txt 版权署名 maning636；Hermes（Nous Research，MIT）随包分发并在 NOTICE.txt 归属。",
    "D3": "已落地（按 B，比当初建议的 A 更彻底）：源码走公开 GitHub 仓库 "
         "github.com/maning636/laoma-ai-workbench，官网下载区已有源码与 Releases 入口，"
         "AGPL 的「提供对应源码」义务由公开仓履行。",
    "D4": "已落地：本地注册码（Ed25519 验签）决定功能档位，云端订阅只给额度"
         "（账号数 / 平台数 / Agent 配额）；两者取交集派生「完整版 / 限制功能版」。",
    "D5": "已落地：单包 639,437,816 B（约 610 MiB），官网按 640 MB 量级提示并给出 SHA-512 校验值。",
}

CONFIRM_SOURCE = (
    "2026-10-23 马哥在《开源发布收尾 · 待决表》P4 选 A —— 「全部按实际落地确认"
    "（D1=A　D2=A　D3=B　D4=A　D5=A）」。代码早已按选项落地并对公网生效，"
    "这张表当时只差一句追认。"
)

DECISIONS = [
    dict(
        no="D1",
        title="安装包叫什么名字（官网下载链接 + 自动更新链路的锚）",
        ctx="1.1.3 线上踩过的坑：latest.yml 里写的是 laoma-ai-workbench-setup-1.1.3.exe，"
            "而磁盘上真实文件叫「老马AI工作台-1.1.3-setup.exe」—— 名字对不上，自动更新链路直接失效。"
            "根因我已读 electron-builder 24.13.3 源码确认：它给 latest.yml 写文件名时只接受纯 ASCII，"
            "含中文就回退成 ${name}-setup-${version}.exe。"
            "本轮我把 artifactName 改成纯 ASCII 的 LaomaAI-${version}-setup.${ext}，1.1.4 正在按这个打。",
        opts=[
            "A. LaomaAI-1.1.4-setup.exe —— 纯 ASCII（当前正在打的这个）",
            "B. 老马AI工作台-1.1.4-setup.exe —— 保留中文品牌名，靠构建后重写 latest.yml 指向它",
            "C. 两个都发：ASCII 名作官网主入口，中文名作镜像备用",
        ],
        rec="建议 A。根因就是 ASCII 限制，B 在技术上也能跑通（构建后重写 latest.yml 那一步我已经写好了，"
            "会自动用磁盘真实名覆盖），代价是下载链接要 percent-encoding，微信内置浏览器偶尔会截断长链接。"
            "C 风险最大：两套文件名 = 官网和更新器可能指向不同文件，这正是老坑的变体。",
        mine="我的选择：",
    ),
    dict(
        no="D2",
        title="客户端的 license 元数据写什么",
        ctx="本轮我按「分发含 AGPL 代码的客户端」把 desktop-electron/package.json 的 license 改成 AGPL-3.0，"
            "desktop-electron/LICENSE.txt 换成 AGPL 全文。但这个安装器里还含 Hermes（Agent 运行时 + WebUI），"
            "那是你打算长期商业化的自有内核 —— 整体标 AGPL，理论上会把 Hermes 也拖进 AGPL 义务。"
            "需要说明的是：AGPL §13 本身允许把 AGPL 程序用在商业闭源产品里，"
            "真正的义务是**必须向用户提供对应源码**；把 AGPL 代码打进商业安装包并不是问题本身。",
        opts=[
            "A. 整个客户端标 AGPL-3.0，官网同时提供含 Hermes 的完整源码包",
            "B. 客户端按闭源商业软件处理：把 prism_backend / prism_frontend 换成编译产物、不分发 AGPL 源码",
            "C. 标 AGPL-3.0，但把 Hermes 拆成独立进程 / 独立安装包，主包不含 Hermes 源码",
        ],
        rec="建议 A 先跑通（当前已按此落地），C 作为下一版方向。理由：AGPL 真正卡住的不是 license 那个字符串，"
            "而是「用户拿不拿得到源码」—— 补上源码包这一步，义务就履行了，Hermes 也可以留在包里。"
            "B 要重做构建链（源码不进包），工程量最大且会拖慢这一版上线。",
        mine="我的选择：",
    ),
    dict(
        no="D3",
        title="开源交付形态：源码怎么给用户",
        ctx="承接 D2：AGPL 要求分发时提供对应源码。备份目录里已经有一份 Prism-Fusion-source.zip，"
            "但它对应的是 1.1.3，得跟 1.1.4 的内容对齐。这一项定的是「用户在哪儿能拿到源码」。",
        opts=[
            "A. 官网下载区同时放 Prism-Fusion-source-1.1.4.zip，安装器首次运行提示源码位置",
            "B. 独立公开 GitHub 仓库 + 官网链接（更新方便，但公开后不可撤回，且要维护两个仓）",
            "C. 官网做一个源码页：核心文件在线展示 + 打包下载",
        ],
        rec="建议 A。备份目录已有现成 zip，改成与 1.1.4 对应即可，改动最小。"
            "B 看着更正规，但公开仓一旦推上去就没法收回，需要你先确认哪些内容真能公开（含云端 prompt 的部分要一起处理）。",
        mine="我的选择：",
    ),
    dict(
        no="D4",
        title="完整版怎么解锁：注册码 / 云端账号 / 两者",
        ctx="现在客户端内是双轨判档：本地注册码（Ed25519 验签）+ 云端订阅，取交集，"
            "再派生「完整版 / 部分开通 / 限制功能版」三态；"
            "Hermes Agent 能力的门禁只看本地注册码里的 agent 条目（要验签，改 license.json 没用）。"
            "这一项定的是：用户到底拿什么来解锁。",
        opts=[
            "A. 只认注册码（本地验签，离线可用）—— 当前已实现；云端只管 AI 额度不管档位",
            "B. 只认云端账号（登录云端看订阅）—— 能远程吊销、能改档，但断网就掉档，且要先有账号体系",
            "C. 两者都要：注册码激活本地能力，云端账号用于远程改档 / 续费 / 吊销",
        ],
        rec="建议 C 的分阶段版：这一版按 A 落地（客户端内切换体验已经通了），"
            "云端账号体系等第一批卖出去再补。纯 A 的短板是「发出去的码收不回来」，"
            "但这在个人微信收款 + 人工发码的模式下本来也不是主要矛盾。",
        mine="我的选择：",
    ),
    dict(
        no="D5",
        title="合并后约 610 MB 的安装包体积能不能接受",
        ctx="合并前 Pro 是 639,419,551 B、Community 是 570,630,903 B；合成单一客户端后约 610 MB。"
            "体积主要来自三处：本地 Python 环境 prismenv、Electron 运行时、Hermes 运行时。"
            "官网下载按钮我已经按 640 MB 量级提示 + sha512 校验来写了。",
        opts=[
            "A. 接受 ~610 MB 单包：一个下载入口、一个安装器、装完就能用",
            "B. 瘦客户端：Python 环境改成按需下载，装完首次启动联网拉运行时（可压到 200 MB 上下）",
            "C. 拆基础包 + 运行时包，官网仍是一个入口（基础包自动拉运行时）",
        ],
        rec="建议 A 先上。这一版的第一优先级是你说的「就一个客户端、一个链接」，"
            "瘦身是下一版的体验优化，不该卡在这一版。补充一句：如果后面真有人抱怨下载慢，"
            "先把官网下载区加上断点续传支持（nginx 一行配置）比重做打包链划算得多。",
        mine="我的选择：",
    ),
]

SHORT = {
    "D1": "安装包命名（官网链接 + 更新锚）",
    "D2": "客户端 license 元数据口径",
    "D3": "开源交付形态（源码怎么给）",
    "D4": "完整版解锁方式（注册码/账号）",
    "D5": "约 610 MB 体积能不能接受",
}


def build():
    # 空白态用当初的页脚，确认态用「已确认」页脚 —— 两者不能混，
    # 否则历史空白表和当前确认表在页脚上分不出来。
    footer = FOOTER if not BLANK_MODE else \
        "Prism-Fusion 客户端发布形态 · 待决表　v1.0　2026-10-24"
    doc = new_document(footer)

    # ---------------- 封面
    para(doc, "", space_after=26)
    para(doc, "Prism-Fusion（老马AI工作台）", size=12.5, color=C_GRAY,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    para(doc, "客户端发布形态 · 待决表", size=25, bold=True, color=C_DARK,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8, name=FONT_HEAD)
    if BLANK_MODE:
        para(doc, "单一客户端已落地，5 处岔路口等你拍板", size=12, color=C_MID,
             align=WD_ALIGN_PARAGRAPH.CENTER, space_after=22)
        para(doc, "版本 v1.0　|　日期 2026-10-24　|　对应代码 e6c1925", size=10,
             color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=3)
    else:
        para(doc, "D1–D5 已全部确认并落地（这张表不用再填了）", size=12, color=C_MID,
             align=WD_ALIGN_PARAGRAPH.CENTER, space_after=22)
        para(doc, "版本 v1.1（已确认）　|　日期 2026-10-24　|　对应交付 v1.1.5", size=10,
             color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=3)
    para(doc, "支付已下线（个人微信收款 + 人工发注册码）；社区版双安装器已合并为单一客户端 1.1.4",
         size=9.5, color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=26)

    t = doc.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_borders(t)
    if BLANK_MODE:
        cover_rows = [
            ("这份表解决什么", "单一客户端已经打出来了（1.1.4），但发布前有 5 处必须你定：安装包叫什么、"
                            "license 怎么写、源码怎么给、用户拿什么解锁、610 MB 能不能接受。"),
            ("一共几处要你拍板", "5 项（D1–D5）。每一项我都写了「我已核实的事实」「选项」「我的建议」，你只需要勾。"),
            ("填完怎么给我", "① 把这个 .docx 存回发给我；② 或者直接念勾选结果（「D1 选 A、D2 选 A、D3 选 A、D4 选 A、D5 选 A」）。两种都行。"),
            ("填不完怎么办", "不想逐项勾，就在最下面的「总快速批注」区写一句总规则，例如「五项都按建议来」。"),
            ("会影响已经做完的事吗", "D1 会改安装包文件名（要重打）；D2/D3 要动官网与源码包；D4/D5 动的是下一版的规划，不影响这一版上线。"),
        ]
    else:
        cover_rows = [
            ("这份表解决什么", "单一客户端（1.1.5）已经打出来并发布，这张表记录发布形态 5 处岔路口的最终口径。"),
            ("确认结果", "D1=A　D2=A　D3=B　D4=A　D5=A —— 五项全部按实际落地追认，选项框已按结果打勾。"),
            ("确认依据", "2026-10-23《开源发布收尾 · 待决表》P4=A：代码早已按选项落地并对公网生效，"
                       "这张表当时只差一句追认。"),
            ("和当初建议的差异", "只有 D3 不同：当初建议 A（官网下载区放源码包），实际落地选了 B（公开 GitHub 仓），"
                         "按实际落地追认。"),
            ("还要你做什么吗", "不需要。已落地的部分不再改代码；要改的是下一版（安装包瘦身 / 云端账号体系）。"),
        ]
    for k, v in cover_rows:
        row = t.add_row()
        shade(row.cells[0], C_HDRBG)
        cell_text(row.cells[0], k, size=10, bold=True, color=C_DARK)
        cell_text(row.cells[1], v, size=10)
    set_widths(t, [4.0, 12.6])

    doc.add_page_break()

    # ---------------- §0 确认记录
    if BLANK_MODE:
        heading(doc, "0　怎么填这份表", 1)
        how_rows = [
            ("选项行", "一行几个候选，前面带 □ 框。在框里打「√」，或者把 □ 改成 ☑（Word 里输入 2611 字符），也可以直接在框后写「选 A」。"),
            ("「我的选择」行", "每个小节最后那行「→ 我的选择：____」，直接写 A/B/C 或一句话。"),
            ("快速批注", "小节下面的横线区，或文末的总批注区。写一句总规则就够，我按它兜底。"),
        ]
    else:
        heading(doc, "0　确认记录（这张表不用再填）", 1)
        how_rows = [
            ("这份表现在的状态", "已确认。五个选项框已按确认结果打勾，每项下面写明实际落地的事实"
                           "（可当场核对的字节数 / 链接 / 配置值）。"),
            ("还能改吗", "能，但要走流程：先改对应代码与对外文案，再同步更新本表，并在当轮提交里写明改了什么。"),
            ("空白版怎么要回来", "builder 支持 --blank：重跑 scripts/docs/build_client_release_decision_form.py "
                         "--blank 可重建当初的空白待决表（往返测试用的就是它）。"),
        ]
    how = doc.add_table(rows=0, cols=2)
    table_borders(how)
    for k, v in how_rows:
        row = how.add_row()
        shade(row.cells[0], C_HDRBG)
        cell_text(row.cells[0], k, size=10, bold=True, color=C_DARK)
        cell_text(row.cells[1], v, size=10)
    set_widths(how, [3.4, 13.2])

    # ---------------- §1 速览
    heading(doc, "1　待决 5 项速览（一屏看完）", 1)
    if BLANK_MODE:
        para(doc, "「当前建议」是我基于已核实事实给的推荐，不是结论；「我的选择」列留空给你填。",
             size=10, color=C_GRAY, space_after=6)
    else:
        para(doc, "「当前建议」是当初我给的推荐；「我的选择」列是 2026-10-23 追认的结果"
                  "（D1=A　D2=A　D3=B　D4=A　D5=A），五项各恰好一个。",
             size=10, color=C_GRAY, space_after=6)

    cols = ["项", "要你定什么", "当前建议", "我的选择"]
    w = [1.4, 5.4, 6.8, 3.0]
    ts = doc.add_table(rows=1, cols=4)
    ts.style = "Table Grid"
    table_borders(ts)
    for i, c in enumerate(cols):
        cell = ts.rows[0].cells[i]
        shade(cell, C_HDRBG)
        cell_text(cell, c, size=9.5, bold=True, color=C_DARK,
                  align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else None)
    repeat_header(ts.rows[0])

    for d in DECISIONS:
        row = ts.add_row()
        no_split(row)
        cell_text(row.cells[0], d["no"], size=9.5, bold=True, color=C_DARK,
                  align=WD_ALIGN_PARAGRAPH.CENTER)
        cell_text(row.cells[1], SHORT[d["no"]], size=9)
        cell_text(row.cells[2], d["rec"], size=8.5)
        if BLANK_MODE:
            cell_text(row.cells[3], "", size=9)
        else:
            cell_text(row.cells[3], "%s ✅ 已落地" % CONFIRMED[d["no"]], size=9, bold=True)
    set_widths(ts, w)

    para(doc, "", space_after=6)
    if BLANK_MODE:
        para(doc, "⚠️ D1 会改安装包文件名（要重打一次）；D2 / D3 要动官网与源码包，"
                  "其余两项影响的是下一版规划，不卡这一版上线。", size=9.5, color=C_MID, space_after=8)
    else:
        para(doc, "✅ D1–D5 五项已按实际落地追认并写回本表；D3 采用公开 GitHub 仓"
                  "（比当初建议的官网源码包更彻底），官网下载区已有源码入口。",
             size=9.5, color=C_MID, space_after=8)

    doc.add_page_break()

    # ---------------- §2 逐项
    heading(doc, "2　逐项详述", 1)
    for d in DECISIONS:
        heading(doc, "%s　%s" % (d["no"], d["title"]), 3)
        if d["ctx"]:
            para(doc, d["ctx"].replace("**", ""), size=9.5, color=C_GRAY, space_after=4)
        if BLANK_MODE:
            for o in d["opts"]:
                para(doc, "%s %s" % (BOX, o), size=10, indent=0.4, space_after=3)
            if d["rec"]:
                para(doc, "💡 " + d["rec"], size=9.5, color=C_MID, indent=0.4, space_after=3)
            para(doc, "→ " + d["mine"] + "_______________________________________________",
                 size=10, bold=True, space_before=2, space_after=6)
        else:
            # 确认态：先写实际落地的事实，再逐项打勾
            para(doc, "✅ 确认落地：" + LANDING[d["no"]], size=9.5, color=C_MID,
                 indent=0.4, space_after=4)
            for o in d["opts"]:
                mark = "☑" if o.lstrip().startswith(CONFIRMED[d["no"]] + ".") else BOX
                para(doc, "%s %s" % (mark, o), size=10, indent=0.4, space_after=3)
            if d["rec"]:
                para(doc, "💡 " + d["rec"], size=9.5, color=C_MID, indent=0.4, space_after=3)
            para(doc, "→ " + d["mine"] + CONFIRMED[d["no"]] + "　（已按此落地）"
                       + "_______________________",
                 size=10, bold=True, space_before=2, space_after=6)
        blank_lines(doc, 2, "小节批注（可留空）：")

    doc.add_page_break()

    # ---------------- §3 总批注
    heading(doc, "3　总快速批注" + ("（已确认）" if not BLANK_MODE else ""), 1)
    if BLANK_MODE:
        para(doc, "任何一项不想细勾，就在这里写一句总规则，我按它兜底（并会在回执里标明哪些是兜底的）。",
             size=10, color=C_GRAY, space_after=6)
        blank_lines(doc, 8)
    else:
        para(doc, "原为「不想逐项勾就写一句总规则」的兜底区；现已追认确认，记录如下：",
             size=10, color=C_GRAY, space_after=6)
        para(doc, CONFIRM_SOURCE, size=10, indent=0.3, space_after=4)
        para(doc, "D1=A　D2=A　D3=B　D4=A　D5=A —— 五项各恰好一个选项被勾，无并列勾选、无总规则兜底。",
             size=10, bold=True, indent=0.3, space_after=4)
        para(doc, "对应交付 v1.1.5（Release tag v1.1.5）；对外口径全文见 docs/release-delivery-statement.md。",
             size=10, indent=0.3, space_after=4)
        blank_lines(doc, 5)

    heading(doc, "4　" + ("填完之后我会做什么" if BLANK_MODE else "确认落地清单"), 1)
    if BLANK_MODE:
        steps = [
            "① 读出你的选择 → 写回 docs/PROJECT_OVERVIEW.md 与发布口径文档；",
            "② D1 若改文件名 → 改 artifactName，重打安装器，并重跑「latest.yml 名字/大小/sha512 与磁盘一致」守卫；",
            "③ D2 / D3 → 按你定的口径改 package.json 的 license 元数据、准备与安装包同版本的源码 zip、官网下载区补上源码入口；",
            "④ D4 / D5 → 落到 feature gate 与下一版打包路线；",
            "⑤ 全部改动跑回归（pytest / tsc / vitest / 产物守卫）后提交并推私有仓库 + 刷新备份 round17。",
        ]
    else:
        steps = [
            "① 读出你的选择 → 写回 docs/PROJECT_OVERVIEW.md 与发布口径文档（docs/release-delivery-statement.md）；",
            "② D1 安装包命名 → artifactName = LaomaAI-${version}-setup.${ext}，"
            "1.1.5 产物已按此发布（639,437,816 B），latest.yml 与磁盘同名同大小；",
            "③ D2 / D3 license 与源码交付 → package.json license=AGPL-3.0、NOTICE.txt 署名 maning636；"
            "源码走公开 GitHub 仓，官网下载区已有源码与 Releases 入口；",
            "④ D4 / D5 → 已落到 feature gate（注册码 ∩ 云端订阅）与 1.1.5 单包体积；",
            "⑤ 全部改动跑回归（pytest / tsc / vitest / 产物守卫）后提交并推仓库 + 刷新备份 round18。",
        ]
    for txt in steps:
        para(doc, txt, size=10, indent=0.3, space_after=4)

    doc.save(OUT)
    print("已生成:", OUT, os.path.getsize(OUT), "bytes", "(blank)" if BLANK_MODE else "(confirmed)")


if __name__ == "__main__":
    BLANK_MODE = "--blank" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            OUT = sys.argv[i + 1]
    build()
