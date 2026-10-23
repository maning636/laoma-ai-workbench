"""D6 开源边界测试:云端 prompt 模板正文是否随开源仓一起泄露。

覆盖:
  1. 开源仓的 `prompts.py` 里 **不含** 任何云端模板正文(静态扫描源码)
  2. 云端模板正文只存在于被 gitignore 的 `_pro_assets/` 目录
  3. 资产缺失时,云端能力**明确降级**(可用性清单仍在,但 `available=False`)
  4. 资产损坏时**不拖垮服务**(降级为空 + 记日志,而不是抛异常)
  5. 基础 tier 不受影响(开源仓可用)
  6. 清单(manifest)与资产内容一致(防"清单说有、资产没有")

用法:
    python cloud_service/test_prompts_oss_boundary.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

# ── 环境准备:临时 SQLite,避免污染仓库 ────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_FAILED: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> bool:
    """打印 [PASS]/[FAIL] 并记录失败项。"""
    status = "PASS" if cond else "FAIL"
    line = f"[{status}] {label}"
    if extra:
        line += f"  ({extra})"
    print(line)
    if not cond:
        _FAILED.append(label)
    return cond


# ──────────────────────────────────────────────────────────────
# 1. 静态扫描:开源源码里不得出现云端模板正文
# ──────────────────────────────────────────────────────────────

#: 云端模板正文的特征片段(base64 存储的 5 个独特句式)。
#:
#: 这里用 base64 存,不用明文 —— 否则 marker 本身就会出现在开源仓里,
#: 扫描会命中**测试文件自己**(自指假阳性),而且明文 marker 等于把
#: 模板特征又抄了一份进开源仓。
_MARKER_B64 = (
    "6ZSK5pmT5piO5bu25a6J5Zmo54K55L2/5omL5Zyo56iL",   # matrix_evaluate
    "55So5oi35Z+56K6t5b6E5bu25qCH",                    # audience_persona
    "5a6J5b6E5LiL5omL5Y+C546H5Lu25qCH",                # platform_style
    "54K55b2x6L6b",                                    # hot_topic
    "5Y+R5L2N6KeG6KeJ5a6J5Zmo54K5",                    # moderator
)

CLOUD_TEMPLATE_MARKERS: tuple[str, ...] = tuple(
    base64.b64decode(s).decode("utf-8") for s in _MARKER_B64
)


def _scan_public_sources() -> list[str]:
    """在**会被 git 跟踪**的源码里扫云端模板特征片段。

    只扫 `cloud_service/`,排除 `_pro_assets/`(私有目录,本来就该有正文)。
    """
    hits: list[str] = []
    root = _repo_root / "cloud_service"
    for p in root.rglob("*.py"):
        if "_pro_assets" in p.parts:
            continue
        if "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for marker in CLOUD_TEMPLATE_MARKERS:
            if marker in text:
                hits.append(f"{p.relative_to(_repo_root)}::{marker}")
    return hits


def _scan_git_tracked() -> list[str]:
    """在 git 已跟踪的文件里扫(比目录扫描更严格:只认会进开源仓的)。"""
    import subprocess

    hits: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "-C", str(_repo_root), "ls-files", "--", "cloud_service"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
    except Exception:
        return hits
    for rel in proc.stdout.splitlines():
        rel = rel.strip()
        if not rel or rel.endswith("/"):
            continue
        p = _repo_root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for marker in CLOUD_TEMPLATE_MARKERS:
            if marker in text:
                hits.append(f"{rel}::{marker}")
    return hits


# ──────────────────────────────────────────────────────────────
# 2. .gitignore 必须排除私有资产目录
# ──────────────────────────────────────────────────────────────

def _gitignore_excludes_pro_assets() -> bool:
    gi = _repo_root / ".gitignore"
    if not gi.is_file():
        return False
    text = gi.read_text(encoding="utf-8", errors="replace")
    return "cloud_service/llm_proxy/_pro_assets/" in text


def _git_tracks_pro_assets() -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "-C", str(_repo_root), "ls-files", "--",
             "cloud_service/llm_proxy/_pro_assets"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
    except Exception:
        return False
    return bool(proc.stdout.strip())


# ──────────────────────────────────────────────────────────────
# 3. 运行时行为
# ──────────────────────────────────────────────────────────────

def _run_runtime_checks() -> None:
    from cloud_service.llm_proxy import prompts as P

    # 3.1 基础 tier 始终可用(开源仓的基础能力)
    check(len(P.BASIC_PROMPTS) == 4, "BASIC_PROMPTS 有 4 条(开源仓可用)",
          str(len(P.BASIC_PROMPTS)))
    check("title.basic_generate" in P.ALL_PROMPTS, "basic prompt 在 ALL_PROMPTS 里")

    # 3.2 清单声明了 5 条云端能力(能力目录公开)
    check(len(P.CLOUD_PROMPT_MANIFEST) == 5, "CLOUD_PROMPT_MANIFEST 声明 5 条",
          str(len(P.CLOUD_PROMPT_MANIFEST)))

    # 3.3 清单与资产一致:manifest 的每个 name,要么在资产里,要么明确 available=False
    man = P.list_prompt_manifest("cloud")
    check(len(man) == 5, "cloud manifest 列出 5 条", str(len(man)))
    check(all("name" in e and "available" in e for e in man),
          "manifest 项含 name/available 字段")

    # 3.4 降级:资产缺失 → 明确「需 Pro」而不是「不存在」
    missing = Path(__file__).resolve().parent / "llm_proxy" / "_pro_assets" / "__no_such_asset__.py"
    ok = P.reload_cloud_prompts(missing)
    check(ok is False, "资产缺失 → reload 返回 False")
    check(len(P.CLOUD_PROMPTS) == 0, "资产缺失 → CLOUD_PROMPTS 为空",
          str(len(P.CLOUD_PROMPTS)))
    check(P.get_prompt("platform_style.match") is None, "资产缺失 → 云端 prompt 取不到")
    check(P.is_pro_required("platform_style.match") is True,
          "资产缺失 → is_pro_required == True")
    check(P.is_pro_required("not.exist") is False,
          "不存在的名字 → is_pro_required == False")
    check(len(P.list_prompt_manifest("cloud")) == 5,
          "资产缺失 → 能力清单仍是 5 条")
    check(all(e["available"] is False for e in P.list_prompt_manifest("cloud")),
          "资产缺失 → cloud 项 available=False")
    check(len(P.list_prompt_names("basic")) == 4, "资产缺失 → basic 不受影响")
    check(len(P.ALL_PROMPTS) == 4, "资产缺失 → ALL_PROMPTS 只剩 basic", str(len(P.ALL_PROMPTS)))

    # 3.5 资产损坏 → 降级为空,不抛异常(服务不能因为资产坏就起不来)
    broken = Path(__file__).resolve().parent / "llm_proxy" / "_pro_assets" / "__broken__.py"
    # _pro_assets/ 被 .gitignore 排除(Pro 资产是私有注入物),开源仓的干净检出里
    # 根本没有这个目录 → 直接 write_text 会 FileNotFoundError(CI 上已实测复现)。
    # 这里先把父目录建出来,测完只留一个空目录,不影响 git。
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("CLOUD_PROMPT_ASSETS = 'not a dict'\n", encoding="utf-8")
    try:
        ok2 = P.reload_cloud_prompts(broken)
        check(ok2 is False, "资产损坏 → reload 返回 False 而不是抛异常")
        check(len(P.CLOUD_PROMPTS) == 0, "资产损坏 → 降级为空")
    finally:
        try:
            broken.unlink()
        except OSError:
            pass

    # 3.6 恢复真实资产(如果本机/Pro 部署有注入)
    ok3 = P.reload_cloud_prompts()
    if ok3:
        check(len(P.CLOUD_PROMPTS) == 5, "恢复真实资产 → cloud == 5",
              str(len(P.CLOUD_PROMPTS)))
        p = P.get_prompt("platform_style.match")
        check(p is not None and p.tier == "cloud", "恢复后 platform_style.match 可取")
        if p is not None:
            rendered = p.render({"platform": "douyin", "topic": "AI", "constraints": "无"})
            check("douyin" in rendered and "{{" not in rendered,
                  "恢复后模板能正常渲染")
    else:
        print("[INFO] 本机未注入云端资产(开源仓预期形态),跳过恢复后断言")

    # 3.7 prompt_count_by_tier 的口径
    counts = P.prompt_count_by_tier()
    check(set(counts) >= {"cloud", "cloud_declared", "basic", "total", "pro_assets_loaded"},
          "prompt_count_by_tier 字段齐全", str(sorted(counts)))
    check(counts["cloud_declared"] == 5, "cloud_declared == 5", str(counts["cloud_declared"]))
    check(counts["pro_assets_loaded"] in (0, 1), "pro_assets_loaded 是 0/1",
          str(counts["pro_assets_loaded"]))
    check(counts["total"] == counts["cloud"] + counts["basic"],
          "total == cloud + basic", str(counts))


# ──────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────

def run() -> int:
    """返回失败计数;0 = 全绿。"""
    # 1. 公开源码里不得有云端模板正文
    hits = _scan_public_sources()
    check(not hits, "cloud_service 公开源码不含云端模板正文", "; ".join(hits[:5]))

    # 2. git 已跟踪的文件里也不得有
    tracked_hits = _scan_git_tracked()
    check(not tracked_hits, "git 已跟踪文件不含云端模板正文", "; ".join(tracked_hits[:5]))

    # 3. 私有目录被 gitignore 排除
    check(_gitignore_excludes_pro_assets(), ".gitignore 排除 _pro_assets/ 目录")
    check(not _git_tracks_pro_assets(), "git 未跟踪 _pro_assets/ 下的文件")

    # 4. 运行时行为
    _run_runtime_checks()

    print()
    if _FAILED:
        print(f"ALL TESTS FAILED: {len(_FAILED)} check(s) failed")
        for label in _FAILED:
            print(f"  - {label}")
        return len(_FAILED)
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
