"""
创作工坊：Easel shared/scripts 工具的表单直调执行器。

把录用的技能脚本（确定性 Python 工具）封装成「工具注册表 + 子进程执行」，
跑在 Easel venv 里（依赖齐全），产物自动写入 Prism 素材库。
本模块不含 LLM 调用——零 token 成本。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from fastapi_app.core import paths
from fastapi_app.services.easel_workbench import EASEL_DIR
from fastapi_app.utils.subprocess_safe import safe_run

if sys.platform == "win32":
    PYTHON_EXE = EASEL_DIR / ".venv" / "Scripts" / "python.exe"
else:
    PYTHON_EXE = EASEL_DIR / ".venv" / "bin" / "python"
SCRIPTS_DIR = EASEL_DIR / "skills" / "shared" / "scripts"
WORKSHOP_DIR = paths.get_data_dir() / "workshop"

RUN_TIMEOUT_SECONDS = 900

# 工具注册表：curated specs（v1 先上零 Key 可跑 + 高频产线工具，逐步扩充）
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "id": "tts-voiceover",
        "label": "TTS 配音",
        "group": "音频",
        "script": "tts.py",
        "subcommand": "speak",
        "desc": "文字转语音口播/旁白。未配置 VOICE_PROVIDER 时自动走 edge 引擎（免费）。",
        "inputs": [],
        "params": [
            {"flag": "--text", "name": "text", "type": "textarea", "label": "配音文本", "required": True},
            {"flag": "-v", "name": "voice", "type": "text", "label": "音色（可选，如 zh-CN-XiaoxiaoNeural）"},
            {"flag": "--rate", "name": "rate", "type": "text", "label": "语速（如 +10%）"},
            {"flag": "--format", "name": "format", "type": "choice", "choices": ["auto", "mp3", "wav", "m4a"], "label": "音频格式", "default": "mp3"},
        ],
        "outputs": [{"name": "audio", "ext": ".mp3", "label": "配音音频"}],
    },
    {
        "id": "remove-bg",
        "label": "图片去背景",
        "group": "图像",
        "script": "remove_bg.py",
        "subcommand": "remove",
        "desc": "AI 语义分割抠图，输出透明 PNG 或换纯色背景。",
        "inputs": [{"name": "image", "label": "输入图片", "accept": "image/*", "required": True, "ext": ".png"}],
        "params": [
            {"flag": "--model", "name": "model", "type": "choice", "choices": ["u2net", "u2netp", "u2net_human_seg", "isnet-general-use", "silueta"], "label": "模型", "default": "u2net"},
            {"flag": "--bg-color", "name": "bg_color", "type": "text", "label": "背景色（如 #FFFFFF，留空=透明）"},
        ],
        "outputs": [{"name": "output", "ext": ".png", "label": "抠图结果"}],
    },
    {
        "id": "auto-subtitle",
        "label": "语音转字幕",
        "group": "音频",
        "script": "asr.py",
        "subcommand": "transcribe",
        "desc": "faster-whisper 语音识别生成字幕（首次运行需下载模型，耗时较长）。",
        "inputs": [{"name": "media", "label": "音频/视频文件", "accept": "audio/*,video/*", "required": True}],
        "params": [
            {"flag": "--format", "name": "format", "type": "choice", "choices": ["srt", "ass", "txt", "json"], "label": "字幕格式", "default": "srt"},
            {"flag": "--model", "name": "model", "type": "choice", "choices": ["tiny", "base", "small", "medium", "large-v3"], "label": "识别模型", "default": "base"},
        ],
        "outputs": [{"name": "subtitle", "ext": None, "label": "字幕文件"}],
    },
]


def get_tool_specs() -> List[Dict[str, Any]]:
    return TOOL_SPECS


def get_tool_spec(tool_id: str) -> Dict[str, Any]:
    for spec in TOOL_SPECS:
        if spec["id"] == tool_id:
            return spec
    raise LookupError(f"工具不存在: {tool_id}")


def _build_command(spec: Dict[str, Any], params: Dict[str, Any], workdir: Path) -> List[str]:
    cmd: List[str] = [str(PYTHON_EXE), str(SCRIPTS_DIR / spec["script"]), spec["subcommand"]]
    for p in spec["params"]:
        value = params.get(p["name"])
        if value is None or str(value).strip() == "":
            continue
        if p["type"] == "choice" and str(value) not in p.get("choices", []):
            continue
        cmd += [p["flag"], str(value)]
    # 输出路径约定：workdir/output<ext>；ext 为 None 时按 format 类参数决定
    for out in spec["outputs"]:
        ext = out.get("ext")
        if ext is None:
            fmt = str(params.get("format") or "").strip()
            if fmt:
                ext = f".{fmt}"
        if ext:
            cmd += ["-o", str(workdir / f"output{ext}")]
            break
    return cmd


def run_tool(
    tool_id: str,
    params: Dict[str, Any],
    input_files: Optional[Dict[str, bytes]] = None,
    input_exts: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """执行工具：写输入文件 → 子进程跑脚本 → 收集产物路径。返回产物文件路径列表。"""
    spec = get_tool_spec(tool_id)
    if not PYTHON_EXE.is_file():
        raise RuntimeError(f"Easel 运行环境缺失: {PYTHON_EXE}")

    workdir = WORKSHOP_DIR / f"{tool_id}-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)

    input_paths: Dict[str, str] = {}
    for inp in spec.get("inputs", []):
        content = (input_files or {}).get(inp["name"])
        if content:
            ext = (input_exts or {}).get(inp["name"]) or inp.get("ext") or ".bin"
            p = workdir / f"input-{inp['name']}{ext}"
            p.write_bytes(content)
            input_paths[inp["name"]] = str(p)

    cmd = _build_command(spec, params, workdir)
    # 输入文件路径注入：有输入的工具按脚本约定追加 -i <第一个输入路径>
    if input_paths:
        cmd += ["-i", next(iter(input_paths.values()))]

    logger.info(f"[Workshop] 运行 {tool_id}: {' '.join(cmd[:6])}...")
    started = time.time()
    # safe_run 内部自动注入 UTF-8 环境变量与 Windows CREATE_NO_WINDOW
    proc = safe_run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    elapsed = round(time.time() - started, 1)
    stdout = (proc.stdout or b"").decode("utf-8", errors="ignore")
    stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")

    if proc.returncode != 0:
        tail = (stderr or stdout)[-800:]
        logger.error(f"[Workshop] {tool_id} 失败 rc={proc.returncode}: {tail}")
        raise RuntimeError(f"工具执行失败（rc={proc.returncode}）: {tail}")

    # 收集产物：workdir 下递归查找 input-* 以外的新文件
    outputs = [
        str(p)
        for p in sorted(workdir.rglob("*"))
        if p.is_file() and not p.name.startswith("input-")
    ]
    if not outputs:
        raise RuntimeError(f"工具未产出文件。stdout: {stdout[-500:]} stderr: {stderr[-500:]}")

    logger.info(f"[Workshop] {tool_id} 完成: {elapsed}s, 产物 {len(outputs)} 个")
    return {
        "tool": tool_id,
        "elapsed_seconds": elapsed,
        "workdir": str(workdir),
        "outputs": outputs,
        "stdout_tail": stdout[-500:],
    }
