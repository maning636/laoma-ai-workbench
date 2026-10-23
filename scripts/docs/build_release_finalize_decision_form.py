# -*- coding: utf-8 -*-
"""生成《Prism-Fusion 开源发布收尾 · 待决表》Word 文档。

仓库 / Release / 官网三件核心交付已经完成并对公网生效，CI 也打到全绿了。
这一轮收的是**发布收尾的尾巴**：

  P1 国内下载通道怎么提速（GitHub 直连 0.12 MB/s vs 自建 0.36 MB/s）
  P2 版权署名（NOTICE.txt 第 3 行）最终写什么
  P3 自动更新通道（build.publish）要不要切 GitHub provider
  P4 D1-D5 追认（上一张 client-release-decision-form.docx 实际已落地）
  P5 官网要不要留个人微信号
  P6 1.1.5 升级安装验收 + 备份 round18
  P7 云端 LLM Key / TikHub Key 缺（能不能真跑通云端链路）

用法：
  D:\\dev\\python\\python.exe scripts\\docs\\build_release_finalize_decision_form.py

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
OUT = os.path.join(REPO, "docs", "release-finalize-decision-form.docx")
FOOTER = "Prism-Fusion 开源发布收尾 · 待决表　v1.0　2026-10-23"

DECISIONS = [
    dict(
        no="P1",
        title="国内下载通道怎么提速（官网现在是 GitHub 主按钮 + 自建兜底）",
        ctx="官网下载区现在两个入口：主按钮指 GitHub Release（v1.1.5，639,437,816 B），"
            "旁边一个自建镜像兜底（maning789link.top/downloads）。三档速度都实测过，不是估算：",
        facts=(
            ("GitHub Release 直连", "0.12 MB/s", "约 89 分钟", "国内终端用户的主按钮就走这条"),
            ("GitHub Release 走代理", "2.25 MB/s", "约 4.7 分钟", "国内用户不会挂代理，指望不上"),
            ("自建服务器直连", "0.36 MB/s", "约 29 分钟", "现在的国内兜底通道"),
        ),
        opts=[
            "A. 保留现状双通道不动 —— 0 成本，但国内用户点主按钮仍然是 89 分钟量级",
            "B. 腾讯云 COS 作国内主通道，GitHub Release 保留作全球 / 离线 / 校验入口（推荐）",
            "C. 服务器升带宽 —— 现在 0.36 MB/s 是被实例带宽卡住的，升上去也就 1 MB/s 量级",
            "D. 第三方加速 / 网盘镜像 —— 有供应链风险，镜像上的二进制不是我们自己签的 sha512",
        ],
        rec="建议 B。COS 是腾讯云自家对象存储，国内走 CDN，实测通常能到几 MB/s 以上；"
            "610 MB × 几个下载量级的流量费很小。做法：安装包放进 COS 对外可读，官网主按钮改指 COS，"
            "GitHub Release 照旧留着。C 只能把 29 分钟压到十几分钟，而且带宽一涨就是常年账单。"
            "D 不建议 —— 第三方镜像上的 exe 你没法给用户签 sha512。",
        rec_short="B（腾讯云 COS 作国内主通道）",
        mine="我的选择：",
    ),
    dict(
        no="P2",
        title="版权署名（NOTICE.txt 第 3 行）最终写什么",
        ctx="NOTICE.txt 第 3 行现在是占位："
            "Copyright (c) 2026 老马AI工作台（Prism-Fusion）贡献者"
            "desktop-electron/package.json 里 author 已经是 maning636，license 是 AGPL-3.0。"
            "这一行要么写具体的人、要么写具体主体 —— 占位符看着像没写完。"
            "提醒一句：改 NOTICE.txt 只影响仓库和以后打的包；已经发出去的 1.1.5 安装包里还是现在这行，"
            "要改到用户手上得等 1.1.6 重打包。",
        opts=[
            "A. maning636 —— 与 GitHub 账号一致，可追溯到人，不用等公司主体（推荐）",
            "B. 老马AI工作台（Prism-Fusion）贡献者 —— 保持现状，就是个占位",
            "C. 写公司主体全称 —— 需要你把工商全称给我",
            "D. 双写：maning636 / 老马AI工作台（Prism-Fusion）贡献者",
        ],
        rec="建议 A。人名 + GitHub 账号是开源项目最常见的写法，AGPL 要求保留版权声明但不强制主体形式；"
            "后面真注册了公司再改成 C 或 D，改一行的事。选 C 的话我需要公司工商全称。"
            "另外提醒：无论选哪个，都要 1.1.6 重打包才能真正改到用户手上的安装包。",
        rec_short="A（maning636）",
        mine="我的选择（若选 C 请写公司全称）：",
    ),
    dict(
        no="P3",
        title="自动更新通道（build.publish）要不要切到 GitHub provider",
        ctx="desktop-electron/package.json 的 build.publish 现在是 generic provider，"
            "指向 https://maning789link.top/downloads —— 自动更新查自建通道的 latest.yml，不查 GitHub。"
            "切 GitHub provider 的好处是「发个 tag 就自动更新」；坏处是自动更新下载也走 GitHub 直连 "
            "0.12 MB/s，610 MB 要等约 89 分钟，而且直连时断断续续。"
            "这一项是 P1 的下游：如果 P1 选了 B（COS），那 generic URL 直接指 COS 就行，"
            "两件事一起解决，不必切 GitHub provider。",
        opts=[
            "A. 暂留 generic 自建通道，本版不动 —— 等 P1 定了再一起处理（推荐）",
            "B. 切 GitHub provider（1.1.6 重打包时切）：自动更新跟 Release 走，下载速度按 GitHub 直连算",
            "C. 留 generic，但把 URL 改成 P1 选定的国内通道（COS，或升带宽后的自建）",
            "D. 关掉自动更新，只在官网手动下载新版",
        ],
        rec="建议 A（若 P1 选 B，这里就是 C）。切 GitHub provider 对国内用户是净退化 —— "
            "自动更新本来就是给「懒得手动下新版」的人用的，这条路径最不能慢。"
            "B 唯一省掉的是维护自建通道那点活，代价是每个自动更新的用户多等一个多小时。"
            "C 是最省事的组合，不用动发布方式，只换一个 URL。",
        rec_short="A（配合 P1 选 B 时改 C）",
        mine="我的选择：",
    ),
    dict(
        no="P4",
        title="D1-D5 追认：上一张「客户端发布形态待决表」实际已经落地了",
        ctx="那张表（docs/client-release-decision-form.docx）D1-D5 还空着，"
            "但代码已经按选项落地并对公网生效了："
            "D1 安装包命名 → A（LaomaAI-1.1.5-setup.exe，纯 ASCII，官网按钮就是这个名）；"
            "D2 客户端 license → A（标 AGPL-3.0，Hermes 一并含在包里）；"
            "D3 源码交付 → B（公开 GitHub 仓库 + 官网链接）—— 这张表的建议本来是 A（官网下载区放源码包），"
            "实际落地选了 B，比建议更彻底；"
            "D4 完整版解锁 → A（只认本地注册码，云端只管 AI 额度）；"
            "D5 安装包体积 → A（接受 610 MB 单包）。"
            "所以这张表实际只差你一句确认，尤其 D3，它跟你当时的建议不一样。",
        opts=[
            "A. 全部按实际落地确认（D1=A　D2=A　D3=B　D4=A　D5=A）（推荐）",
            "B. D3 改回 A：官网下载区放 Prism-Fusion-source-1.1.5.zip，GitHub 仓保留但不作为交付口径",
            "C. 我要改某几项，在下面写「D 编号 + 新选择」",
        ],
        rec="建议 A。D3 选 B 是因为你后来把仓库开到了 GitHub（maning636/laoma-ai-workbench），"
            "这比官网放一个 zip 强得多 —— 用户能 clone、能看历史、能提 issue，"
            "而且 AGPL 的「提供对应源码」义务走公开仓本身就是最干净的履约方式。"
            "选 B 的话我要额外打一个与 1.1.5 对齐的源码 zip 并改官网下载区。",
        rec_short="A（按实际落地确认）",
        mine="我的选择：",
    ),
    dict(
        no="P5",
        title="官网要不要留个人微信号",
        ctx="官网现在只有企业微信名「马哥AI落地」+ 一个个人收款码图片，没有个人微信号。"
            "用户下完 610 MB 的包，卡住了该问谁 —— 现在没有明确入口。这一项是可选增强，不影响上线。",
        opts=[
            "A. 加上个人微信号 —— 请写在下面「我的选择」里",
            "B. 保持现状：只留企业微信名「马哥AI落地」+ 收款码",
            "C. 加「加微信答疑」入口，但只放二维码图片、不写号码（避免被爬号）",
        ],
        rec="建议 A 或 C。你说过要留个人微信，我现在没拿到号 —— 你把号给我我加到官网下载区下面。"
            "如果不想公开号码，C 最稳：二维码图片我直接用你给的那张。"
            "另提醒一句：小红书 / 抖音那边本来就不允许站外引流，这只是官网自己的联系方式，不算引流。",
        rec_short="A（给微信号）或 C（只放二维码）",
        mine="我的选择（微信号 / 或写「用二维码」）：",
    ),
    dict(
        no="P6",
        title="1.1.5 升级安装验收 + 备份 round18",
        ctx="两件事。① 1.1.5 安装包已发布，但从来没做过「从 1.1.4 升到 1.1.5」的验收 —— "
            "用户升级后数据目录、注册码、设置、Agent 配置会不会保留，没验过。"
            "1.1.4 → 1.1.5 的差异里有 cloud_service 的注册码校验改动（base64 编码方式），"
            "这类改动最怕影响老用户已有的 license.json。"
            "② 备份目录现在停在 1.1.4 三件套（LaomaAI-1.1.4-setup.exe / .blockmap / latest.yml "
            "+ Prism-Fusion-source.zip + MANIFEST.txt），round17 已被 _superseded_round17 标记；"
            "round18（对齐 1.1.5）还没做。",
        opts=[
            "A. 我提供一台干净 Windows 机器 / 虚拟机的操作权，你装完把结果给我",
            "B. 你给操作步骤，我自己在另一台机器上装（你把步骤发我）",
            "C. 升级验收暂缓，先只做备份 round18",
            "D. 两件都暂缓",
        ],
        rec="建议 C，有余力再做 B。备份 round18 我随时能做，不依赖你（把 1.1.5 三件套 + 对齐的源码包 "
            "+ MANIFEST 刷进 D:\\Prism-Fusion-Backup）。升级验收需要一台干净机 —— "
            "你手上有 Windows 机器的话，我可以给一份十分钟能走完的检查单（装 → 升 → 看注册码还在不在）。",
        rec_short="C（先做备份 round18，升级验收有余力再做）",
        mine="我的选择：",
    ),
    dict(
        no="P7",
        title="云端 LLM Key / TikHub Key 缺（决定云端链路能不能真跑通）",
        ctx="两个必填的外部密钥现在都没有："
            "CLOUD_LLM_API_KEY —— 云端调 LLM 用的，缺了 cloud_service 的 call_cloud_llm() 直接抛 "
            "LLMKeyNotConfiguredError，云端 AI 这条链路跑不通；"
            "TIKHUB_API_KEY —— 抖音 / 小红书等平台的数据采集用的"
            "（prism_backend/myUtils/tikhub_client.py 读它）。"
            "所以「云端 AI 能不能真用」「数据采集能不能真用」这两件事，目前只验到 mock 层。",
        opts=[
            "A. 我提供 —— 放 D 盘某个目录，只给我路径，不要贴进对话",
            "B. 该功能先关掉 —— 客户端隐藏入口 / 后端返回明确的「未配置」提示",
            "C. 用服务器上已有的密钥，我不给新 key",
        ],
        rec="建议 A 或 C。密钥一律不要贴在对话里 —— 你在 D 盘建个目录把 .env 放进去，我按路径读，"
            "不打印内容、不写进仓库、不进 git。B 是合法兜底：功能关掉比「点了报一个看不懂的错」体验好。"
            "顺带一提，云端测试账号密码已经在 D:\\Prism-Fusion-Backup\\_acceptance\\ 下，不会外泄。",
        rec_short="A（给路径）或 C（用服务器上的）",
        mine="我的选择（密钥路径 / 或写「用服务器上的」）：",
    ),
]

SHORT = {
    "P1": "国内下载通道提速方案",
    "P2": "NOTICE.txt 版权署名写法",
    "P3": "自动更新通道切不切 GitHub",
    "P4": "D1-D5 追认（已落地待确认）",
    "P5": "官网要不要留个人微信号",
    "P6": "1.1.5 升级验收 + 备份 round18",
    "P7": "云端 LLM / TikHub 密钥",
}


def build():
    doc = new_document(FOOTER)

    # ---------------- 封面
    para(doc, "", space_after=26)
    para(doc, "Prism-Fusion（老马AI工作台）", size=12.5, color=C_GRAY,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    para(doc, "开源发布收尾 · 待决表", size=25, bold=True, color=C_DARK,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8, name=FONT_HEAD)
    para(doc, "仓库 / Release / 官网都已上线，剩下这 7 处等你拍板", size=12, color=C_MID,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=22)
    para(doc, "版本 v1.0　|　日期 2026-10-23　|　对应代码 206a202", size=10,
         color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=3)
    para(doc, "CI 已全绿（run 39919068812，8 个硬门全 success）｜Release v1.1.5 已发布并挂到官网",
         size=9.5, color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=26)

    t = doc.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_borders(t)
    for k, v in [
        ("这份表解决什么", "三件核心交付已经完成并对公网生效：公开仓 maning636/laoma-ai-workbench、"
                        "Release v1.1.5（639,437,816 B）、官网下载区双通道。"
                        "剩下的是发布收尾：下载通道提速、版权署名、自动更新通道、"
                        "D1-D5 追认、微信号、升级验收与备份、两个缺失的密钥。"),
        ("一共几处要你拍板", "7 项（P1-P7）。每一项我都写了「我已核实的事实」「选项」「当前建议」，你只需要勾。"),
        ("填完怎么给我", "① 把这个 .docx 存回发给我；"
                     "② 或者直接念勾选结果（「P1 选 B、P2 选 A、P3 选 C、P4 选 A、P5 选 A、P6 选 C、P7 选 A」）。两种都行。"),
        ("填不完怎么办", "不想逐项勾，就在最下面的「总快速批注」区写一句总规则，例如「都按建议来」。"),
        ("会不会影响已经上线的东西", "P1 / P5 会改官网（要重新发一次静态页）；"
                            "P2 / P3 要等 1.1.6 重打包才影响用户手上的安装包；"
                            "P4 只是把已落地的口径追认成你确认过的；其余三项不卡上线。"),
    ]:
        row = t.add_row()
        shade(row.cells[0], C_HDRBG)
        cell_text(row.cells[0], k, size=10, bold=True, color=C_DARK)
        cell_text(row.cells[1], v, size=10)
    set_widths(t, [4.0, 12.6])

    doc.add_page_break()

    # ---------------- §0 怎么填
    heading(doc, "0　怎么填这份表", 1)
    how = doc.add_table(rows=0, cols=2)
    table_borders(how)
    for k, v in [
        ("选项行", "一行几个候选，前面带 □ 框。在框里打「√」，或者把 □ 改成 ☑"
                "（Word 里输入 2611 字符），也可以直接在框后写「选 A」。"),
        ("「我的选择」行", "每个小节最后那行「→ 我的选择：____」，直接写 A/B/C 或一句话。"),
        ("快速批注", "小节下面的横线区，或文末的总批注区。写一句总规则就够，我按它兜底。"),
        ("回读脚本", "scripts/docs/read_release_finalize_decision_form.py —— 你填完我直接跑，"
                 "它把你勾的每一项读成结构化结果，不靠我肉眼猜。"),
    ]:
        row = how.add_row()
        shade(row.cells[0], C_HDRBG)
        cell_text(row.cells[0], k, size=10, bold=True, color=C_DARK)
        cell_text(row.cells[1], v, size=10)
    set_widths(how, [3.4, 13.2])

    # ---------------- §1 速览
    heading(doc, "1　待决 7 项速览（一屏看完）", 1)
    para(doc, "「当前建议」是我基于已核实事实给的推荐，不是结论；「我的选择」列留空给你填。",
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
        cell_text(row.cells[2], d["rec_short"], size=8.5)
        cell_text(row.cells[3], "", size=9)
    set_widths(ts, w)

    para(doc, "", space_after=6)
    para(doc, "⚠️ P1 / P5 要改官网（重新发一次静态页）；P2 / P3 要等 1.1.6 重打包才影响用户手上的安装包；"
              "P4 只是把已经落地的口径追认成你确认过的。", size=9.5, color=C_MID, space_after=8)

    doc.add_page_break()

    # ---------------- §2 逐项
    heading(doc, "2　逐项详述", 1)
    for d in DECISIONS:
        heading(doc, "%s　%s" % (d["no"], d["title"]), 3)
        if d["ctx"]:
            para(doc, d["ctx"], size=9.5, color=C_GRAY, space_after=4)
        if d.get("facts"):
            tf = doc.add_table(rows=1, cols=4)
            tf.style = "Table Grid"
            table_borders(tf)
            for i, c in enumerate(["通道", "实测速度", "610 MB 大概要", "备注"]):
                cell = tf.rows[0].cells[i]
                shade(cell, C_HDRBG)
                cell_text(cell, c, size=9, bold=True, color=C_DARK)
            repeat_header(tf.rows[0])
            for a, b, c, e in d["facts"]:
                row = tf.add_row()
                no_split(row)
                cell_text(row.cells[0], a, size=8.5)
                cell_text(row.cells[1], b, size=8.5, bold=True, color=C_MID)
                cell_text(row.cells[2], c, size=8.5)
                cell_text(row.cells[3], e, size=8.5)
            set_widths(tf, [3.6, 2.4, 2.8, 7.8])
            para(doc, "", size=6, space_after=2)
        for o in d["opts"]:
            para(doc, "%s %s" % (BOX, o), size=10, indent=0.4, space_after=3)
        if d["rec"]:
            para(doc, "💡 " + d["rec"], size=9.5, color=C_MID, indent=0.4, space_after=3)
        para(doc, "→ " + d["mine"] + "_______________________________________________",
             size=10, bold=True, space_before=2, space_after=6)
        blank_lines(doc, 2, "小节批注（可留空）：")

    doc.add_page_break()

    # ---------------- §3 总批注
    heading(doc, "3　总快速批注", 1)
    para(doc, "任何一项不想细勾，就在这里写一句总规则，我按它兜底（并会在回执里标明哪些是兜底的）。",
         size=10, color=C_GRAY, space_after=6)
    blank_lines(doc, 8)

    heading(doc, "4　填完之后我会做什么", 1)
    for txt in [
        "① 跑回读脚本读出你的选择 → 写回 docs/PROJECT_OVERVIEW.md 与发布口径文档；",
        "② P1 / P5 若改官网 → 改 /var/www/fde/index.html 并做公网验收（改前先备份，"
        "现有备份在 index.html.bak.20261023_132000）；",
        "③ P2 / P3 若要落地 → 改 NOTICE.txt 与 desktop-electron/package.json 的 build.publish，"
        "打 1.1.6，重跑「latest.yml 名字 / 大小 / sha512 与磁盘一致」守卫；",
        "④ P4 → 把 D1-D5 的确认结果写进发布口径文档，并同步 client-release-decision-form.docx 的回执；",
        "⑤ P6 → 刷备份 round18（1.1.5 三件套 + 对齐源码包 + MANIFEST）；"
        "若你选了 A / B，升级验收我出一份十分钟能走完的检查单；",
        "⑥ P7 → 按你给的路径读密钥（不打印、不入库、不进 git），跑真实云端链路而不是 mock；",
        "⑦ 全部改动跑回归（pytest / tsc / vitest / 产物守卫）后提交并推 origin + prism-server + 备份。",
    ]:
        para(doc, txt, size=10, indent=0.3, space_after=4)

    doc.save(OUT)
    print("已生成:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    build()
