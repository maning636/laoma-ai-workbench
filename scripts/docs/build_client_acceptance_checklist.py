# -*- coding: utf-8 -*-
"""生成《老马AI工作台 客户端验收清单》Word 表（1.1.5）。

与「待决表」是**两份独立文档**：
  - 待决表（docs/client-release-decision-form.docx）= 马哥拍板用，一次性；
  - 本清单（docs/client-acceptance-checklist.docx）= 马哥在**自己机器上**
    逐项点、逐项看、逐项勾的验收记录。

设计要点：
  - 主表 5 列（编号 / 验收项 / 去哪怎么点 / 期望看到什么 / 结果），
    结果列是 **三个并列框**（□通过 □不通过 □跳过）——
    回读必须**逐框**判定，不能「行内有一个框勾了就算整行勾了」。
  - 问题记录单独一张表，不挤在主表里。
  - 敏感信息（注册码原文、云端测试账号密码）**不进文档**，
    只写「在哪台机器的哪个文件里」。

依赖：python-docx（装在 D:\\dev\\python\\python.exe，不写 C 盘）。
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts", "docs"))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402

from _decision_form_common import (  # noqa: E402
    C_DARK,
    C_GRAY,
    C_HDRBG,
    C_MID,
    FONT_BODY,
    FONT_HEAD,
    blank_lines,
    cell_text,
    heading,
    new_document,
    no_split,
    para,
    repeat_header,
    set_widths,
    shade,
    table_borders,
)

OUT = os.path.join(REPO, "docs", "client-acceptance-checklist.docx")

VERSION = "1.1.5"
BUILD_DATE = "2026-10-24"

#: (编号, 验收项, 去哪/怎么点, 期望看到什么)
ITEMS = [
    # ── 组 1：安装与首次启动 ───────────────────────────────
    ("A1", "双击桌面图标能启动", "桌面「老马AI工作台」图标，双击",
     "几秒内弹出客户端窗口，标题是「老马AI工作台」；不再出现安装向导"),
    ("A2", "首屏是仪表盘", "启动后自动进入的首页",
     "标题「矩阵投放仪表盘」，上方 4 张统计卡：账号总数 / 素材储备 / 异常待处理 / 系统时间"),
    ("A3", "左侧菜单能展开", "看左侧导航栏",
     "概览、资源、开发者工具、SYSTEM 各组都能点开，页面不空白、不报错"),
    ("A4", "左下角系统状态", "侧边栏最底部",
     "SYSTEM 后面是绿点 + Online（不是灰点 / Offline）"),
    ("A5", "窗口能正常缩放/切页", "拖窗口边缘、点不同菜单",
     "布局不塌、文字不重叠、窗口不白屏"),

    # ── 组 2：版本档位（限制功能版） ────────────────────────
    ("B1", "侧边栏显示「限制功能版」", "侧边栏底部那一块",
     "灰色徽标写着「限制功能版」，下面三格是 3 账号 / 3 平台 / 0 智能体"),
    ("B2", "「加微信开通」按钮能点", "点侧边栏底部「加微信开通」",
     "跳到 设置 → 更多设置 → 联系我们（不是报错页、不是空白）"),
    ("B3", "徽标刷新按钮", "点徽标右上角的 ↻",
     "数字重新读一次，不白屏、不弹错"),
    ("B4", "档位不是「完整版」", "看侧边栏底部徽标",
     "没激活注册码时**不应该**出现「完整版」；应保持「限制功能版」"),

    # ── 组 3：加微信（商业路径） ────────────────────────────
    ("C1", "「联系我们」卡片在位", "设置 → 更多设置 → 往下滚到「联系我们」",
     "卡片标题「联系我们」，下面有「扫码加我」和一张微信二维码"),
    ("C2", "二维码能正常显示", "看「联系我们」卡片里的图",
     "图片完整显示，**不是**空白框、不是裂图、不是「二维码暂时无法显示」"),
    ("C3", "二维码扫得出来", "用手机扫这张二维码",
     "扫出来是产品方的个人微信名片（不是群、不是别的号）"),
    ("C4", "页面没有内部英文变量名", "在「联系我们」这一页随便看",
     "整页看不到 NEXT_PUBLIC_ 开头的英文（这是给开发者看的，不该露给用户）"),
    ("C5", "充值引导口径正确", "看「联系我们」卡片上方的说明文字",
     "写的是「充值与开通请通过微信联系产品方人工办理（线上支付暂未开放）」之类，"
     "**不能**出现「立即支付 / 支付宝 / 微信支付」等在线支付字样"),

    # ── 组 4：注册码与开通（要真的贴码） ────────────────────
    ("D1", "注册码卡片初始态", "设置 → 更多设置 → 上面「本地 注册码」区",
     "授权状态 = 未激活，到期时间 = -，积分额度 = -，下方有「输入 / 更换注册码」输入框"),
    ("D2", "能粘贴注册码", "点输入框，粘贴（见下方「测试物料」）",
     "输入框提示形如 PRISM1.…；粘贴后「激活」按钮从灰变可点"),
    ("D3", "点「激活」成功", "点输入框右边的「激活」",
     "右上角弹「注册码已激活」；授权状态变成「有效」，到期时间变成具体日期，"
     "「已授权条目」一排徽章全部点亮"),
    ("D4", "登录云端账号", "设置 → 「订阅与云端账号」→ 登录/注册",
     "能用测试账号登录成功（登录状态 = 已登录；不是「未登录」）"),
    ("D5", "点「同步到云端」", "注册码卡片里的「同步到云端」按钮",
     "右上角弹「已同步到云端」；卡片里「云端订阅」显示已连接；"
     "（**这一步是 1.1.4 的断点**，1.1.4 会报「云端不可达」）"),
    ("D6", "档位切成「完整版」", "看侧边栏底部徽标",
     "徽标变金色，写着「完整版」；三格变成 无限账号 / 多平台 / 2 智能体；"
     "按钮文案从「加微信开通」变成「续费联系」"),
    ("D7", "完整版才有 AI 对话", "左侧「AI 对话」（完整版才可用）",
     "能打开对话页，页面不提示「未授权」"),
    ("D8", "清除注册码可回退", "注册码卡片里的「清除注册码」",
     "徽标回到「限制功能版」，AI 对话等 Pro 能力重新不可用（可逆，不锁死）"),

    # ── 组 5：核心功能页面 ─────────────────────────────────
    ("E1", "AI 生图页能开", "左侧「AI 生图」",
     "页面打开，提示词框/画布能操作，不报未授权"),
    ("E2", "视频流水线页能开", "左侧「视频流水线」",
     "页面打开，步骤条在，素材区能选"),
    ("E3", "图片编辑器能开", "左侧「图片编辑器」",
     "页面打开，编辑器能加载（提示 MS 已完成）"),
    ("E4", "账号管理能开", "左侧「账号管理」",
     "页面打开；没账号时显示空列表，不是报错"),
    ("E5", "矩阵发布能开", "左侧「矩阵发布」",
     "页面打开，平台列表/任务区能渲染"),
    ("E6", "选题库/素材管理能开", "左侧「选题库」「素材管理」",
     "两个页面都能打开，无报错"),

    # ── 组 6：中文界面与稳定性 ──────────────────────────────
    ("F1", "中文界面没有乱码", "随便翻 3-4 个页面",
     "没有方块、问号、半个字；标题和按钮都是完整中文"),
    ("F2", "深浅主题都正常", "设置里切换主题（深色 / 浅色）",
     "两种主题下文字和背景都清晰；徽标、卡片、按钮颜色正常不糊"),
    ("F3", "顶部搜索能跳转", "点顶部搜索框，输入「发布」或「设置」",
     "出候选，回车能跳到对应页面"),
    ("F4", "关掉重开档位保持", "完全退出客户端再双击打开",
     "能重新启动；档位仍是「完整版」（不丢授权）"),
    ("F5", "卸载能卸干净（可选）", "控制面板 → 卸载「老马AI工作台」",
     "桌面图标消失；安装目录和 %APPDATA%\\laoma-ai-workbench 被清掉"),
]

#: §2 问题记录表（空行若干）
PROBLEM_ROWS = 8


def build():
    doc = new_document("老马AI工作台 %s 客户端验收清单" % VERSION)

    # ── 封面 ──────────────────────────────────────────────
    para(doc, "老马AI工作台", size=13, bold=True, color=C_MID,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_before=40, space_after=2)
    para(doc, "客户端验收清单", size=26, bold=True, color=C_DARK,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6, name=FONT_HEAD)
    para(doc, "版本 %s　·　构建日期 %s" % (VERSION, BUILD_DATE),
         size=11, color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    para(doc, "（你自己的机器上逐项点、逐项看、逐项勾；填完发我）",
         size=10, color=C_GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=26)

    # ── §0 怎么填 ─────────────────────────────────────────
    heading(doc, "0　怎么填（先看这三条）", 1)
    para(doc,
         "这张表不是问卷，是**你自己的操作记录**。你点一遍、看一遍，"
         "把结果勾上；有问题的在第 2 节记一行。整个表填完发我，我按你记的逐条修。",
         size=10.5, space_after=6)

    for label, text in [
        ("① 结果只勾一个",
         "每一行的「结果」列有三个框：□ 通过 / □ 不通过 / □ 跳过。"
         "**只勾其中一个**。没来得及试的勾「跳过」，不要留空。"),
        ("② 不通过就记一笔",
         "「不通过」的行，去第 2 节「问题记录」里加一行：对应编号 + 你看到了什么。"
         "有报错就把报错原文抄上去；有截图就把图片存到同一个文件夹，"
         "文件名写进「截图文件名」列（我就按这个文件名找）。"),
        ("③ 整体意见写在最后",
         "第 3 节「总批注」可以写一句总规则，比如「生图先不管，先把发布链路跑通」。"),
    ]:
        para(doc, label, size=10.5, bold=True, color=C_MID, space_before=4, space_after=2)
        para(doc, text, size=10, indent=0.5, space_after=4)

    para(doc, "测试物料（在这台机器上，不在本文档里）", size=10.5, bold=True,
         color=C_MID, space_before=8, space_after=2)
    for k, v in [
        ("注册码原文", r"D:\dim开发\Prism-Fusion\tmp\_test_license.txt"),
        ("云端测试账号 + 密码", r"D:\Prism-Fusion-Backup\_acceptance\cloud_test_account.txt"),
        ("客户端安装包", r"https://maning789link.top/　→　下载客户端"),
    ]:
        p = para(doc, "%s：%s" % (k, v), size=9.5, indent=0.5, space_after=2)
        for run in p.runs:
            run.font.name = "Consolas"

    # ── §1 主表 ───────────────────────────────────────────
    doc.add_page_break()
    heading(doc, "1　逐项验收（主表）", 1)
    para(doc,
         "共 %d 项，分 6 组（A 启动 / B 档位 / C 加微信 / D 注册码与开通 / E 功能页 / F 界面）。"
         "「结果」列三选一勾。" % len(ITEMS),
         size=10, color=C_GRAY, space_after=8)

    widths = [1.3, 3.2, 5.0, 5.3, 3.4]
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table_borders(table)
    hdr = table.rows[0]
    repeat_header(hdr)
    no_split(hdr)
    for idx, name in enumerate(["编号", "验收项", "去哪 / 怎么点", "期望看到什么", "结果"]):
        cell_text(hdr.cells[idx], name, size=9, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade(hdr.cells[idx], C_HDRBG)

    groups = {
        "A": "组 1 · 安装与首次启动",
        "B": "组 2 · 版本档位（未激活时）",
        "C": "组 3 · 加微信（商业路径）",
        "D": "组 4 · 注册码与开通",
        "E": "组 5 · 核心功能页面",
        "F": "组 6 · 中文界面与稳定性",
    }
    last_group = None
    for no, title, how, expect in ITEMS:
        group = no[0]
        if group != last_group:
            last_group = group
            grow = table.add_row()
            no_split(grow)
            merged = grow.cells[0]
            for c in grow.cells[1:]:
                merged = merged.merge(c)
            cell_text(grow.cells[0], groups.get(group, group), size=9, bold=True, color=C_DARK)
            shade(grow.cells[0], "F2F6FB")
        row = table.add_row()
        no_split(row)
        cell_text(row.cells[0], no, size=9, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        cell_text(row.cells[1], title, size=9)
        cell_text(row.cells[2], how, size=8.5)
        cell_text(row.cells[3], expect, size=8.5)
        cell_text(row.cells[4], "□ 通过　□ 不通过　□ 跳过", size=9, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_widths(table, widths)

    # ── §2 问题记录 ───────────────────────────────────────
    doc.add_page_break()
    heading(doc, "2　问题记录", 1)
    para(doc,
         "每发现一个问题加一行。「严重程度」三选一："
         "□ 阻塞（主流程走不通）/ □ 严重（能用但不对）/ □ 小（体验问题）。",
         size=10, color=C_GRAY, space_after=8)

    pwidths = [1.3, 2.6, 7.2, 3.3, 3.8]
    ptable = doc.add_table(rows=1, cols=5)
    ptable.style = "Table Grid"
    table_borders(ptable)
    phdr = ptable.rows[0]
    repeat_header(phdr)
    no_split(phdr)
    for idx, name in enumerate(["编号", "对应验收项", "现象描述（报错请抄原文）",
                                 "严重程度", "截图文件名"]):
        cell_text(phdr.cells[idx], name, size=9, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade(phdr.cells[idx], C_HDRBG)
    for _ in range(PROBLEM_ROWS):
        r = ptable.add_row()
        no_split(r)
        cell_text(r.cells[0], "", size=9)
        cell_text(r.cells[1], "", size=9)
        cell_text(r.cells[2], "", size=9)
        cell_text(r.cells[3], "□ 阻塞　□ 严重　□ 小", size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER)
        cell_text(r.cells[4], "", size=9)
    set_widths(ptable, pwidths)

    # ── §3 总批注 ─────────────────────────────────────────
    heading(doc, "3　总批注", 1)
    para(doc, "一句话总规则就行（比如「先别管生图，把发布链路跑通」）。",
         size=9.5, color=C_GRAY, space_after=4)
    blank_lines(doc, 4)

    # ── §4 填完之后 ───────────────────────────────────────
    heading(doc, "4　填完之后我会做什么", 1)
    for i, text in enumerate([
        "按第 2 节逐条修，每个问题改完在下一版安装包里给你复验。",
        "「阻塞」级别优先，其余按你的总批注排序。",
        "改完重新出包 → 官网下载入口换新版 → 你再点一遍同样这几项。",
        "D1–D5 的发布形态待决表已于 2026-10-23 追认确认（D1=A　D2=A　D3=B　D4=A　D5=A），"
        "结论见 docs/release-delivery-statement.md；这份验收单只管客户端行为，不受影响。",
    ], start=1):
        para(doc, "%d) %s" % (i, text), size=10, indent=0.4, space_after=3)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc.save(OUT)
    print("written:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    build()
