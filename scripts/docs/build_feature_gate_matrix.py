"""生成 feature gate 矩阵：机器可读 JSON + 人读 Markdown（同一份源，防漂移）。

用法（仓库根执行）：
    python scripts/docs/build_feature_gate_matrix.py

生成时会**回读代码**做交叉校验：flag 缺失、或 data_recovery 的 Community 值不是 true，直接报错中止。

数据源：
  - docs/feature-inventory-and-oss-boundary.md 的 §1（55 项）/ §2（54 个能力域）「你选」列
  - 2026-10-22 拍板结论 D1–D10
输出：
  - docs/feature-gate-matrix.json
  - docs/feature-gate-matrix.md
"""
import io
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INV = os.path.join(REPO, "docs", "feature-inventory-and-oss-boundary.md")
OUT_JSON = os.path.join(REPO, "docs", "feature-gate-matrix.json")
OUT_MD = os.path.join(REPO, "docs", "feature-gate-matrix.md")

md = io.open(INV, encoding="utf-8").read()
s1 = md[md.index("## 1. 功能清单"):md.index("## 2. 有后端能力")]
s2 = md[md.index("## 2. 有本"):md.index("## 3. 注册码")] if "## 2. 有本" in md else \
    md[md.index("## 2. 有后端能力"):md.index("## 3. 注册码")]

# ---- §1
feat = []
r1 = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*`([^`]+)`\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*\*\*(开源|注册码|不做)\*\*\s*\|",
    re.M)
for m in r1.finditer(s1):
    feat.append({"no": int(m.group(1)), "name": m.group(2).strip(), "route": m.group(3).strip(),
                 "desc": m.group(4).strip(), "eps": int(m.group(5)),
                 "advice": m.group(6).replace("**", "").strip(),
                 "pick": m.group(8).strip()})

# ---- §2
dom = []
r2 = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*\*\*(做入口且开源|做入口但注册码|不做入口)\*\*[^|]*\|",
    re.M)
for m in r2.finditer(s2):
    cell = m.group(2).strip()
    bk = re.search(r"`([^`]+)`", cell)
    dom.append({"no": int(m.group(1)), "domain": bk.group(1) if bk else cell,
                "groups": int(m.group(3)), "ops": int(m.group(4)),
                "desc": m.group(6).strip(),
                "advice": m.group(7).replace("**", "").strip(),
                "pick": m.group(8).strip()})

assert len(feat) == 55, "§1 %d" % len(feat)
assert len(dom) == 54, "§2 %d" % len(dom)

# ---------------------------------------------------------------- 判定模型
# 注册码条目（可组合授权包）—— D1=C：本地注册码给白名单，云端订阅给配额
ENTRIES = [
    {"key": "core", "name": "基础包", "desc": "全部开源功能（默认包含）",
     "features": ["max_accounts", "max_platforms", "team_members"]},
    {"key": "ai_cloud", "name": "云端 AI", "desc": "云端 prompt / 云端生图 / 云端模型（自配 key 走本地模式不需此条目）",
     "features": ["ai_mode", "image_gen", "cloud_prompt"]},
    {"key": "agent", "name": "Agent 配额", "desc": "Hermes Agent 配额与流式对话",
     "features": ["agent_quota", "stream_chat"]},
    {"key": "persona", "name": "Persona 与代理", "desc": "Persona 指纹 / 代理管理 / 代理网关",
     "features": ["persona", "proxy_management"]},
    {"key": "campaign", "name": "营销活动编排", "desc": "营销活动 → 任务包 → 发布任务整链",
     "features": ["campaign_orchestration"]},
    {"key": "multi_platform", "name": "多平台发布", "desc": "超出社区版 3 平台的发布能力（数量随版本扩充，不写死）",
     "features": ["max_platforms"]},
]

# ---------------------------------------------------------------- flag 真源表
# community / pro 取自 prism_backend/fastapi_app/api/billing_client.py 的
# COMMUNITY_FLAGS / PRO_FLAGS，再按 D5 / D7 修正
FLAGS = [
    {"flag": "max_accounts", "type": "numeric", "community": 3, "pro": -1,
     "entry": "core", "status": "已实现", "note": "账号数配额，云端订阅维度"},
    {"flag": "max_platforms", "type": "numeric", "community": 3, "pro": 8,
     "entry": "multi_platform", "status": "已实现",
     "note": "D5：对外不承诺具体数量（README/前端文案统一写「多平台」）；此值为内部配额，随版本扩充"},
    {"flag": "ai_mode", "type": "mode", "community": "local_key", "pro": "cloud",
     "entry": "ai_cloud", "status": "已实现", "note": "云端模式需 ai_cloud 条目"},
    {"flag": "image_gen", "type": "mode", "community": "local_key", "pro": "cloud",
     "entry": "ai_cloud", "status": "已实现", "note": "云端生图需 ai_cloud 条目"},
    {"flag": "agent_quota", "type": "numeric", "community": 0, "pro": 2,
     "entry": "agent", "status": "已实现", "note": "0 = 禁用"},
    {"flag": "data_recovery", "type": "bool", "community": True, "pro": True,
     "entry": "core", "status": "已实现",
     "note": "D7：不收进 Pro，社区版即可用（已同步改云端 / 客户端 / 前端三处）"},
    {"flag": "persona", "type": "bool", "community": False, "pro": True,
     "entry": "persona", "status": "已实现", "note": ""},
    {"flag": "proxy_management", "type": "bool", "community": False, "pro": True,
     "entry": "persona", "status": "已实现", "note": ""},
    {"flag": "stream_chat", "type": "bool", "community": False, "pro": True,
     "entry": "agent", "status": "已实现", "note": ""},
    {"flag": "team_members", "type": "numeric", "community": 1, "pro": 1,
     "entry": "core", "status": "已实现", "note": ""},
    {"flag": "cloud_prompt", "type": "bool", "community": False, "pro": True,
     "entry": "ai_cloud", "status": "新增待实现",
     "note": "D6：云端 prompt 资产，随 prompts.py 移出开源树（B2）"},
    {"flag": "campaign_orchestration", "type": "bool", "community": False, "pro": True,
     "entry": "campaign", "status": "新增待实现",
     "note": "新增：营销活动与任务包编排（注册码授权）"},
]

# ---------------------------------------------------------------- 代码交叉校验
# 矩阵不能只自说自话：把三处代码里的 flag 名与 COMMUNITY_FLAGS 回读比对。
CODE_SOURCES = {
    "cloud_service/billing/feature_gate.py": "云端实现",
    "prism_backend/fastapi_app/api/billing_client.py": "客户端实现",
    "prism_frontend/src/lib/plan-flags.ts": "前端默认",
}

existing_flags = [f["flag"] for f in FLAGS if f["status"] == "已实现"]
new_flags = [f["flag"] for f in FLAGS if f["status"] != "已实现"]
known = set(existing_flags) | set(new_flags)


def _dict_block(src, varname):
    """取 `<varname> = {` 的真实字典体（跳过文档字符串里的同名提及）。"""
    m = re.search(r"^[^\n]*?\b" + varname + r"[^=\n{]*=\s*\{", src, re.M)
    assert m, "未找到 %s 赋值" % varname
    body = src[m.end():]
    return body[:body.index("}")]


def _flag_names(block):
    return re.findall(r'"([a-z_]+)"\s*:', block)


crosscheck = []
for rel, role in CODE_SOURCES.items():
    src = io.open(os.path.join(REPO, rel), encoding="utf-8").read()
    if rel.endswith(".py"):
        names = set(_flag_names(_dict_block(src, "COMMUNITY_FLAGS"))) | \
            set(_flag_names(_dict_block(src, "PRO_FLAGS")))
    else:
        blk = src[src.index("export const FEATURE_NAMES"):]
        blk = blk[:blk.index("] as const")]
        names = set(re.findall(r'"([a-z_]+)"', blk))
        names |= set(_flag_names(_dict_block(src, "DEFAULT_COMMUNITY_FLAGS")))
    missing = [f for f in existing_flags if f not in names]
    assert not missing, "%s 缺少 flag: %s" % (rel, missing)
    crosscheck.append({"file": rel, "role": role,
                       "flag_count": len([n for n in names if n in known])})

# data_recovery 的 Community 值必须为 True（D7）：三处都要是 True
for rel in CODE_SOURCES:
    src = io.open(os.path.join(REPO, rel), encoding="utf-8").read()
    varname = "DEFAULT_COMMUNITY_FLAGS" if rel.endswith(".ts") else "COMMUNITY_FLAGS"
    blk = _dict_block(src, varname)
    m = re.search(r'"?data_recovery"?\s*:\s*(\w+)', blk)
    assert m, "%s 未找到 data_recovery" % rel
    assert m.group(1) in ("True", "true"), \
        "%s 的 data_recovery Community 仍是 %s（D7 要求 true）" % (rel, m.group(1))

# 前端 Pro 平台数文案不得写死数字（D5）
pf = io.open(os.path.join(REPO, "prism_frontend/src/lib/plan-flags.ts"), encoding="utf-8").read()
assert '"多"' in pf, "前端 platformsLabel 未按 D5 改为「多」"

matrix = {
    "version": "1.0",
    "decided_at": "2026-10-22",
    "decided_by": "maning636",
    "source": "docs/feature-inventory-and-oss-boundary.md §7 + docs/oss-boundary-decision-form.docx",
    "model": {
        "route": "C",
        "formula": "allowed = 注册码授权条目（本地校验） ∩ 订阅配额（云端）",
        "code_binding": False,
        "code_expiry": "固定期限（年卡 / 季卡 / 月卡）",
        "expired_behavior": "到期后已产生数据「能看，不能新增」",
        "notes": [
            "注册码只决定『能不能用』，云端订阅只决定『能用多少』",
            "注册码默认不绑机器；离线宽限期待实现时定（建议 7–14 天）",
            "未登录 / 云端不可达 → 回落 Community flag（既有行为不变）",
        ],
    },
    "registration_entries": ENTRIES,
    "flags": FLAGS,
    "code_crosscheck": crosscheck,
    "feature_items": feat,
    "capability_domains": dom,
}

with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
    json.dump(matrix, f, ensure_ascii=False, indent=1)
print("已生成:", OUT_JSON, os.path.getsize(OUT_JSON), "bytes")

# ---------------------------------------------------------------- Markdown
L = []
A = L.append
A("# Feature Gate 矩阵（拍板落地版）")
A("")
A("> 生成时间：2026-10-22 ｜ 数据源：`docs/feature-inventory-and-oss-boundary.md` §1/§2「你选」列 + 拍板结论 D1–D10")
A("> 机器可读版本：`docs/feature-gate-matrix.json`（与本文件同源生成，改一处两处一起变）")
A("> 定位：**自媒体矩阵发布 + AI 生图/生视频内容生产平台**")
A("")
A("---")
A("")
A("## 0. 判定模型（D1 = C 双轨）")
A("")
A("```")
A("allowed(功能) = 注册码授权条目（本地校验） ∩ 订阅配额（云端）")
A("```")
A("")
A("| 规则 | 结论 | 依据 |")
A("|---|---|---|")
A("| 判定公式 | 注册码给**白名单**（能不能用）∩ 云端订阅给**额度**（能用多少） | D1 |")
A("| 设备绑定 | **默认不绑**（一码通用）；若启用绑定则允许自助解绑 | D2 |")
A("| 有效期 | **固定期限**（年卡 / 季卡 / 月卡），license 必带到期时间 | D3 |")
A("| 到期语义 | 已产生数据**能看，不能新增** | D4 |")
A("| 平台数 | **不承诺具体数量**，只写「多平台」 | D5 |")
A("| 云端 prompt | **移出开源树**，只在 Pro 包提供（新增 flag `cloud_prompt`） | D6 |")
A("| 数据回收 | **不收进 Pro**，社区版即可用（flag `data_recovery` Community 已改 true） | D7 |")
A("| 平台细粒度 API | 不给前端入口 | D8 |")
A("| 版权署名 | 保持「老马AI工作台（Prism-Fusion）贡献者」 | D9 |")
A("| README 开放级别 | 按现状不调整 | D10 |")
A("")
A("## 1. Flag 真源表（10 个既有 + 2 个新增）")
A("")
A("| flag | 类型 | Community | Pro | 注册码条目 | 状态 | 说明 |")
A("|---|---|---|---|---|---|---|")
for f in FLAGS:
    A("| `%s` | %s | `%s` | `%s` | `%s` | %s | %s |" % (
        f["flag"], f["type"], f["community"], f["pro"], f["entry"], f["status"], f["note"]))
A("")
A("> ✅ **D7 已落代码**：`data_recovery` 的 Community 值已在云端实现 / 客户端实现 / 前端默认三处同步为 `true`；"
  "D5 已把 Pro 平台数对外文案从「8 平台」改为「多平台」，内部配额值不变。")
A("")
A("> 🔍 **代码交叉校验**（生成时自动回读代码，缺 flag 或口径不符直接报错）：")
A(">")
for c in crosscheck:
    A("> - `%s`（%s）：%d 个 flag 全部对齐" % (c["file"], c["role"], c["flag_count"]))
A("")
A("## 1. Flag 真源表（11 个既有 + 2 个新增）")
A("")
A("| flag | 类型 | Community | Pro | 注册码条目 | 说明 |")
A("|---|---|---|---|---|---|")
for f in FLAGS:
    pro = f["pro"] if f["pro"] is not None else "随版本扩充"
    A("| `%s` | %s | `%s` | `%s` | `%s` | %s |" % (
        f["flag"], f["type"], f["community"], pro, f["entry"], f["note"]))
A("")
A("> ⚠️ **需要同步改代码**：`prism_backend/fastapi_app/api/billing_client.py` 的 "
  "`COMMUNITY_FLAGS[\"data_recovery\"]` 仍是 `False`，与 D7 冲突（B1 批次改）。")
A("")
A("## 2. 注册码条目（可组合的授权包）")
A("")
A("| 条目键 | 名称 | 解锁 | 说明 |")
A("|---|---|---|---|")
for e in ENTRIES:
    A("| `%s` | %s | %s | %s |" % (e["key"], e["name"],
                                    "、".join("`%s`" % x for x in e["features"]), e["desc"]))
A("")
A("## 3. 功能清单 55 项（按「你选」列）")
A("")
A("| # | 功能 | 路由 | 我的选择 | 当前建议 |")
A("|---|---|---|---|---|")
for f in feat:
    A("| %d | %s | `%s` | **%s** | %s |" % (f["no"], f["name"], f["route"], f["pick"], f["advice"]))
A("")
A("## 4. 无入口能力域 54 项（按「你选」列）")
A("")
A("| # | 能力域 | 组 | 操作 | 我的选择 | 当前建议 |")
A("|---|---|---|---|---|---|")
for d in dom:
    A("| %d | `%s` | %d | %d | **%s** | %s |" % (
        d["no"], d["domain"], d["groups"], d["ops"], d["pick"], d["advice"]))
A("")
A("---")
A("")
A("## 5. 统计")
A("")
c1 = {}
for f in feat:
    c1[f["pick"]] = c1.get(f["pick"], 0) + 1
c2 = {}
for d in dom:
    c2[d["pick"]] = c2.get(d["pick"], 0) + 1
A("| 维度 | 分布 |")
A("|---|---|")
A("| §1 功能清单 | " + " ｜ ".join("**%s %d**" % (k, v) for k, v in sorted(c1.items())) + " |")
A("| §2 能力域 | " + " ｜ ".join("**%s %d**" % (k, v) for k, v in sorted(c2.items())) + " |")
A("")
A("> §1 / §2 逐项选择为**按「当前建议」兜底**（拍板表里未逐项勾选），")
A("> 其中 `recovery`（D7）、`ai-prompts`（D6）按拍板结论覆盖。")

with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(L) + "\n")
print("已生成:", OUT_MD, os.path.getsize(OUT_MD), "bytes")
print("§1 分布:", c1)
print("§2 分布:", c2)
