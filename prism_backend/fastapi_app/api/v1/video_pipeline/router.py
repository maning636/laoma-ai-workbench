"""
视频流水线 API —— HyperFrames（HTML+GSAP→MP4）引擎，作为 Easel slideshow/ffmpeg 之外的
**第二条并行流水线**。编排逻辑对标 video-producer 编排库（路径由 core_paths 解析，非硬编码绝对路径；7 阶段：决策→内容→视觉
→素材→合成→输出→复盘）；本路由先落地 Flow 无关的引擎层：把一个 HyperFrames composition
渲染成 MP4 并自动入素材库。

- GET  /api/v1/video-pipeline/engines   列可用引擎 + 探测 HyperFrames 版本
- POST /api/v1/video-pipeline/render    composition → npx hyperframes render → MP4 → 入素材库
                                        (composition_dir 本地路径，或上传 composition zip)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core import paths as core_paths
from fastapi_app.utils.subprocess_safe import safe_run

router = APIRouter(prefix="/video-pipeline", tags=["视频流水线"])

# HyperFrames 渲染超时（秒）——HTML→MP4 较重，给宽一点
_RENDER_TIMEOUT_SECONDS = 600
# 走本机代理（npx 首次可能拉包；edge-tts/GitHub 等都走它）
_PROXY = "http://127.0.0.1:7997"
# 产物工作区
_PIPELINE_DIR = Path(settings.DATA_DIR) / "video-pipeline"


def _build_env() -> dict:
    env = os.environ.copy()
    env["HTTPS_PROXY"] = _PROXY
    env["HTTP_PROXY"] = _PROXY
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Node 输出含中文/emoji，GBK 控制台会崩
    env["NODE_NO_WARNINGS"] = "1"
    # 计划任务后端 PATH 可能精简，确保 nodejs 在 PATH 上（npx.cmd/node.exe 解析依赖它）
    node_dir = str(core_paths.get_nodejs_dir())
    path_sep = ";" if sys.platform == "win32" else ":"
    cur_path = env.get("PATH", "")
    if node_dir not in cur_path.split(path_sep):
        env["PATH"] = node_dir + path_sep + cur_path
    return env


def _resolve_npx() -> str:
    """解析 npx 可执行路径（Windows 上 npx 是 npx.cmd，subprocess 直接 ['npx',...] 找不到）。

    优先用 shutil.which（PATH 解析后），回退到常见 nodejs 安装位置，最后回退字符串 'npx'。
    """
    import shutil
    found = shutil.which("npx")
    if found:
        return found
    for cand in (Path(core_paths.get_nodejs_dir()) / "npx.cmd",
                 Path(core_paths.get_nodejs_dir()) / "npx.exe",
                 Path(str(Path.home() / "AppData/Roaming/nvm"))):
        if cand.exists():
            return str(cand)
    return "npx"


def _probe_hyperframes() -> dict:
    """探测 npx hyperframes 版本。"""
    try:
        proc = safe_run(
            [_resolve_npx(), "hyperframes", "--version"],
            timeout=30,
            env_extra=_build_env(),
            capture_output=True,
        )
        out = (proc.stdout or b"").decode("utf-8", errors="ignore").strip()
        err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
        version = (out or err).splitlines()[0] if (out or err) else ""
        return {"installed": proc.returncode == 0, "version": version}
    except Exception as e:
        return {"installed": False, "version": "", "error": str(e)}


@router.get("/engines")
async def list_engines():
    """列出可用视频引擎 + 探测状态。"""
    hf = _probe_hyperframes()
    engines = [
        {
            "id": "hyperframes",
            "label": "HyperFrames（HTML+GSAP→MP4）",
            "render_cmd": "npx hyperframes render --quality {quality} --fps {fps}",
            "installed": hf["installed"],
            "version": hf["version"],
            "default": True,
        },
        {
            "id": "openmontage",
            "label": "OpenMontage（Remotion Composer）",
            "path": str(core_paths.get_openmontage_dir()),
            "installed": core_paths.get_openmontage_dir().exists(),
            "default": False,
        },
        {
            "id": "moneyprinter",
            "label": "MoneyPrinterTurbo（AI 一键成片）",
            "path": str(core_paths.get_moneyprinter_dir()),
            "installed": core_paths.get_moneyprinter_dir().exists(),
            "default": False,
        },
    ]
    return {
        "status": "success",
        "result": {
            "engines": engines,
            "default_engine": "hyperframes",
            "pipeline_phases": [
                "1 决策", "2 内容", "3 视觉", "4 素材", "5 合成", "6 输出", "7 复盘"
            ],
        },
    }


def _run_hyperframes_render(composition_dir: Path, quality: str, fps: int, variables: dict | None = None, output_path: str | None = None) -> dict:
    """在 composition_dir 跑 npx hyperframes render，返回 {outputs, elapsed, stdout, stderr}。

    variables: 模板变量（merge 到 data-composition-variables 默认值），--variables flag。
    output_path: 指定输出 MP4 路径（-o），否则默认 renders/<name>.mp4 在 composition_dir 下。
    """
    # 渲染前可选 lint（失败不阻断，只记日志）
    for check in ("lint", "validate"):
        try:
            safe_run(
                [_resolve_npx(), "hyperframes", check],
                cwd=str(composition_dir),
                capture_output=True,
                timeout=60,
                env_extra=_build_env(),
            )
        except Exception as e:
            logger.warning(f"[VideoPipeline] hyperframes {check} 跳过: {e}")

    cmd = [_resolve_npx(), "hyperframes", "render", "--quality", quality, "--fps", str(fps)]
    if output_path:
        cmd += ["-o", str(output_path)]
    if variables:
        cmd += [f"--variables={json.dumps(variables, ensure_ascii=False)}"]
    logger.info(f"[VideoPipeline] render cwd={composition_dir} variables={'yes' if variables else 'no'} cmd={' '.join(cmd)}")
    started = time.time()
    proc = safe_run(
        cmd,
        cwd=str(composition_dir),
        capture_output=True,
        timeout=_RENDER_TIMEOUT_SECONDS,
        env_extra=_build_env(),
    )
    elapsed = round(time.time() - started, 1)
    stdout = (proc.stdout or b"").decode("utf-8", errors="ignore")
    stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
    if proc.returncode != 0:
        tail = (stderr or stdout)[-1200:]
        raise RuntimeError(f"hyperframes render 失败（rc={proc.returncode}）: {tail}")

    # 收集产物 MP4：优先 output_path，否则 composition_dir 下递归找 *.mp4
    outputs: list[str] = []
    if output_path and Path(output_path).is_file():
        outputs.append(str(output_path))
    if not outputs:
        outputs = [
            str(p) for p in sorted(composition_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() == ".mp4"
        ]
    if not outputs:
        raise RuntimeError(
            f"渲染完成但未找到 MP4 产物（检查 composition 是否正确）。stdout 尾: {stdout[-400:]}"
        )
    return {"outputs": outputs, "elapsed_seconds": elapsed, "stdout": stdout, "stderr": stderr}


@router.post("/render")
async def render(
    composition_dir: Optional[str] = Form(None, description="本地 composition 目录路径（含 index.html）"),
    composition_zip: Optional[UploadFile] = File(None, description="或上传 composition zip（解压后含 index.html）"),
    quality: str = Form("standard", description="渲染质量：draft/standard/high"),
    fps: int = Form(30, description="帧率"),
    variables: Optional[str] = Form(None, description='模板变量 JSON（merge 到 data-composition-variables 默认值），如 {"title":"你好"}'),
):
    """HyperFrames composition → MP4 → 自动入素材库，返回 file_ids。

    composition 路径可指向素材库模板目录（templates/{id}，路径经 core_paths.get_template_lib_dir() 解析），
    配合 variables 传参：`npx hyperframes render --variables '{...}'`。
    """
    if not composition_dir and not composition_zip:
        raise HTTPException(status_code=400, detail="需提供 composition_dir 或 composition_zip")

    _PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

    if composition_zip:
        # 解压上传的 zip 到临时工作区
        workdir = _PIPELINE_DIR / f"comp-{uuid.uuid4().hex[:8]}"
        workdir.mkdir(parents=True, exist_ok=True)
        zip_bytes = await composition_zip.read()
        zip_path = workdir / "composition.zip"
        zip_path.write_bytes(zip_bytes)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(workdir)
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail=f"composition_zip 解压失败: {e}")
        finally:
            zip_path.unlink(missing_ok=True)
        # 若解压出一个顶层目录，下钻一层
        children = [p for p in workdir.iterdir() if p.is_dir()]
        index_html = workdir / "index.html"
        if not index_html.exists() and len(children) == 1:
            workdir = children[0]
        comp_dir = workdir
    else:
        comp_dir = Path(composition_dir)
        if not comp_dir.is_dir():
            raise HTTPException(status_code=400, detail=f"composition_dir 不存在或不是目录: {composition_dir}")

    if not (comp_dir / "index.html").exists():
        raise HTTPException(
            status_code=400,
            detail=f"composition 目录缺少 index.html: {comp_dir}",
        )

    # 解析 variables（JSON 字符串 → dict）
    parsed_vars: Optional[dict] = None
    if variables:
        try:
            parsed_vars = json.loads(variables) if isinstance(variables, str) else variables
            if not isinstance(parsed_vars, dict):
                raise ValueError("variables 必须是 JSON 对象")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"variables JSON 解析失败: {e}")

    try:
        result = _run_hyperframes_render(comp_dir, quality, fps, variables=parsed_vars)
    except RuntimeError as e:
        logger.error(f"[VideoPipeline] render 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"渲染超时（>{_RENDER_TIMEOUT_SECONDS}s）")
    except Exception as e:
        logger.error(f"[VideoPipeline] render 异常: {e}")
        raise HTTPException(status_code=500, detail=f"渲染异常: {e}")

    # 产物自动入素材库（复用 files 的 save_file_record，与 workshop 同模式）
    from fastapi_app.api.v1.files.services import FileService
    from fastapi_app.db.session import main_db_pool

    service = FileService()
    file_ids: List[int] = []
    note = f"video-pipeline:hyperframes quality={quality} fps={fps}"
    with main_db_pool.get_connection() as conn:
        for out_path in result["outputs"]:
            p = Path(out_path)
            try:
                file_id = await service.save_file_record(
                    conn,
                    filename=f"[video-pipeline] {p.name}",
                    file_path=str(p),
                    filesize_mb=p.stat().st_size / (1024 * 1024),
                    note=note,
                    group_name="video-pipeline:hyperframes",
                )
                file_ids.append(file_id)
            except Exception as e:
                logger.error(f"[VideoPipeline] 产物入库失败 {p.name}: {e}")

    return {
        "status": "success",
        "result": {
            "engine": "hyperframes",
            "elapsed_seconds": result["elapsed_seconds"],
            "outputs": [Path(o).name for o in result["outputs"]],
            "file_ids": file_ids,
        },
    }


# ============================================================
# 8 阶段视频编排（对标 OpenMontage 的 pipeline_defs/animated-explainer.yaml，路径经 core_paths.get_openmontage_dir() 解析）
# ============================================================
from fastapi_app.api.v1.video_pipeline.orchestrator import (
    STAGES,
    start_run,
    get_run,
    approve_run,
    reject_run,
    list_templates,
    get_template,
    get_template_html,
)

router.add_api_route(
    "/templates", list_templates, methods=["GET"],
    summary="列素材库模板（542 专业 HyperFrames 模板，可 ?category= &q= 过滤）",
)
router.add_api_route(
    "/templates/{template_id}", get_template, methods=["GET"],
    summary="取单模板详情（含 schema 变量定义，供填参/渲染）",
)
router.add_api_route(
    "/templates/{template_id}/html", get_template_html, methods=["GET"],
    summary="取模板 index.html 原文（前端 srcdoc 注入变量实时预览用）",
    response_class=PlainTextResponse,
)
router.add_api_route(
    "/run", start_run, methods=["POST"],
    summary="启动 8 阶段视频编排 run（跑到首个 checkpoint 暂停）",
)
router.add_api_route(
    "/run/{run_id}", get_run, methods=["GET"],
    summary="查询 run 状态（阶段/artifacts/pending_approval）",
)
router.add_api_route(
    "/run/{run_id}/approve", approve_run, methods=["POST"],
    summary="批准当前 checkpoint，继续执行",
)
router.add_api_route(
    "/run/{run_id}/reject", reject_run, methods=["POST"],
    summary="打回当前阶段带 feedback 重做（每阶段最多 3 次）",
)
