"""集中路径解析（P0 阶段最小落地，P1b 补齐 paths.json 层）。

统一 fallback 模板（所有 get_*_dir 一致，例外见下）：
    env（用户显式配置，最高优先）
    > paths.json 层（DATA_DIR/paths.json，本文件 P1b 实现）
    > 默认探测/候选
    > 保守兜底

特例：
- get_data_dir 不读 paths.json：paths.json 自身位置依赖 get_data_dir 返回，
  若 get_data_dir 反过来读 paths.json 会形成循环依赖。故 get_data_dir 保持
  env > APPDATA > LOCALAPPDATA > repo_root 的原链路。

设计原则：
- env 永远最高优先；paths.json 次之；默认探测兜底
- 所有函数永不抛异常，永远返回 Path / dict / None
- paths.json 读失败或字段缺失时静默降级到默认层，不影响主流程

新增环境变量（可选，用于生产打包）：
- LAOMA_TEMPLATE_LIB_DIR: 视频模板素材库目录
- LAOMA_NODEJS_DIR: Node.js 安装目录
- LAOMA_OPENMONTAGE_DIR: OpenMontage 目录
- LAOMA_MONEYPRINTER_DIR: MoneyPrinterTurbo 目录
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional


def _env_path(*keys: str, default: Optional[Path] = None) -> Path:
    """从多个 env 名中取第一个非空值，均不存在时返回 default。"""
    for key in keys:
        raw = (os.getenv(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return default or Path(".")


def _cfg_path(cfg: dict, key: str) -> Optional[Path]:
    """从 paths.json 字典里取字符串路径；缺失/空/非字符串返回 None。"""
    raw = cfg.get(key)
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser().resolve()
    return None


def get_repo_root() -> Path:
    """仓库根目录。prism_backend/fastapi_app/core/paths.py 上溯 4 级。"""
    return Path(__file__).resolve().parents[3]


def get_template_lib_dir() -> Path:
    """视频模板素材库。找不到时降级为空目录，_load_catalog 会捕获文件缺失。

    fallback 链：env LAOMA_TEMPLATE_LIB_DIR > paths.json(template_lib_dir) > repo_root/tools/templates
    """
    env = (os.getenv("LAOMA_TEMPLATE_LIB_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cfg = _cfg_path(load_paths_config(), "template_lib_dir")
    if cfg:
        return cfg
    return get_repo_root() / "tools" / "templates"


def get_nodejs_dir() -> Path:
    """Node.js 安装目录。

    fallback 链：env LAOMA_NODEJS_DIR > paths.json(nodejs_dir) > shutil.which("node") > ProgramFiles\nodejs
    注：env 最高优先；paths.json 次之；均无时才走 which 探测（"env 优先于探测"原则）。
    """
    env = (os.getenv("LAOMA_NODEJS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cfg = _cfg_path(load_paths_config(), "nodejs_dir")
    if cfg:
        return cfg
    # 默认探测：which("node") 返回 node.exe 完整路径，取其父目录
    node = shutil.which("node")
    if node:
        p = Path(node).parent
        if p.exists():
            return p
    # Windows 常见位置兜底
    pf = os.getenv("ProgramFiles") or r"C:\Program Files"
    return Path(pf) / "nodejs"


def get_openmontage_dir() -> Path:
    """fallback 链：env LAOMA_OPENMONTAGE_DIR / LAOMA_THIRD_PARTY_ROOT > paths.json(openmontage_dir) > DATA_DIR/third-party/OpenMontage"""
    env = (os.getenv("LAOMA_OPENMONTAGE_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    third = (os.getenv("LAOMA_THIRD_PARTY_ROOT") or "").strip()
    if third:
        return Path(third).expanduser().resolve() / "OpenMontage"
    cfg = _cfg_path(load_paths_config(), "openmontage_dir")
    if cfg:
        return cfg
    # 降级到 DATA_DIR 下的 third-party 目录，让 /engines 显示 installed=False 但不硬指 F:
    return get_data_dir() / "third-party" / "OpenMontage"


def get_moneyprinter_dir() -> Path:
    """fallback 链：env LAOMA_MONEYPRINTER_DIR / LAOMA_THIRD_PARTY_ROOT > paths.json(moneyprinter_dir) > DATA_DIR/third-party/MoneyPrinterTurbo"""
    env = (os.getenv("LAOMA_MONEYPRINTER_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    third = (os.getenv("LAOMA_THIRD_PARTY_ROOT") or "").strip()
    if third:
        return Path(third).expanduser().resolve() / "MoneyPrinterTurbo"
    cfg = _cfg_path(load_paths_config(), "moneyprinter_dir")
    if cfg:
        return cfg
    return get_data_dir() / "third-party" / "MoneyPrinterTurbo"


def _is_dev_source_tree() -> bool:
    """是否运行在项目源码树内(开发环境)——把数据落项目内，避免写 C 盘。

    严格条件：非 PyInstaller 打包(sys.frozen 不存在/False) + 本文件在 repo_root/prism_backend 下。
    打包后 sys.frozen=True 直接返回 False，安装机仍用默认 %APPDATA%。
    仅在本模块加载时评估一次路径结构；任何异常都降级为 False（保守：走原有链路）。
    """
    if getattr(sys, "frozen", False):
        return False
    try:
        here = Path(__file__).resolve()
        repo = get_repo_root()
        # 兼容 Python 3.8(无 Path.is_relative_to)：手工字符串前缀判断，且排除同前缀但不同目录的误判
        repo_str = str(repo)
        here_str = str(here)
        if not (here_str == repo_str or here_str.startswith(repo_str + os.sep)):
            return False
        # 只有真的落在 repo_root/prism_backend/... 才算源码树运行(而非打包副本被拷到别处)
        return (repo / "prism_backend").is_dir()
    except Exception:
        return False


def get_data_dir() -> Path:
    """应用数据目录。

    fallback 链：env LAOMA_DATA_DIR > 开发环境源码树(_is_dev_source_tree) > 显式 dev env
    (LAOMA_ENV/NODE_ENV=dev/development/local) > APPDATA > LOCALAPPDATA > repo_root
    注：本函数不读 paths.json —— paths.json 自身位置由本函数返回的 DATA_DIR 决定
    (见 get_paths_config_path)，若此处再读 paths.json 会形成循环依赖。
    与 core.config.Settings.DATA_DIR 使用同一优先级（env > 开发环境检测 > 常见用户数据目录 > 仓库根）。
    为避免循环 import，这里直接读 env 而不引用 settings 实例。

    语义区分：
    - env LAOMA_DATA_DIR：用户显式配置，最高优先，返回原值(不追加 data/)。
    - 开发环境源码树(_is_dev_source_tree)：非打包 + 本文件在 repo_root/prism_backend 下时，
      返回 repo_root/"data" —— 让 python -c / uvicorn 直连 fastapi_app 时也落项目内，禁止写 C 盘。
    - LAOMA_ENV=dev 显式分支：返回 repo_root —— 保留 P1a 旧语义(用户显式声明 dev 时数据落仓库根)。
    - APPDATA/LOCALAPPDATA/repo_root：生产/打包默认链路。
    """
    env_dir = (os.getenv("LAOMA_DATA_DIR") or "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    # 开发环境兜底：运行在源码树内(非打包)时落项目内 data/，禁止写 C 盘。
    # 覆盖绕过 run.py 直接 import 的场景(python -c / uvicorn fastapi_app.main:app)。
    # 优先级在 LAOMA_ENV=dev 之前：源码树内一律走 repo_root/data，即使未设 LAOMA_ENV。
    if _is_dev_source_tree():
        return get_repo_root() / "data"
    # P1a review: 窄化 dev 分支——只在显式 LAOMA_ENV=dev/development/local 时落仓库根
    # (不照抄旧 _is_dev_repo 的 .git 判断，避免打包机保留 .git 误命中)
    # 到达此分支意味着 _is_dev_source_tree() 为 False(打包机或非源码树运行)，
    # 用户在打包副本里显式声明 dev 时数据仍落 repo_root(与旧语义一致)。
    laoma_env = (os.getenv("LAOMA_ENV") or os.getenv("NODE_ENV") or "").strip().lower()
    if laoma_env in ("dev", "development", "local"):
        return get_repo_root()
    # 不读 paths.json（避免与 get_paths_config_path 形成循环依赖）
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "老马AI工作台" / "data"
    localappdata = os.getenv("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "老马AI工作台" / "data"
    return get_repo_root()


def get_paths_config_path() -> Path:
    """paths.json 配置文件路径。位于 DATA_DIR/paths.json（文档选 A）。"""
    return get_data_dir() / "paths.json"


def load_paths_config() -> dict:
    """读 paths.json，返回 dict。文件不存在、解析失败或格式非 dict 时返回 {}。

    永不抛异常：任何异常都静默降级为 {}，保证 paths.json 层缺失不影响主流程。
    """
    p = get_paths_config_path()
    try:
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_paths_config(d: dict) -> None:
    """原子写 paths.json：先写同目录临时文件，再 os.replace 覆盖，避免半写状态。

    永不抛异常：写失败时清理临时文件并静默返回，避免污染调用方。
    非 dict 输入直接忽略（保守兜底）。
    """
    if not isinstance(d, dict):
        return
    p = get_paths_config_path()
    tmp_path: Optional[Path] = None
    try:
        os.makedirs(p.parent, exist_ok=True)
        # 与目标同目录的临时文件，保证 os.replace 在同一文件系统上原子
        fd, tmp_name = tempfile.mkstemp(
            prefix=".paths.json.", suffix=".tmp", dir=str(p.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, p)
        tmp_path = None
    except Exception:
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass


def get_hermes_runtime_config_path() -> Path:
    """Hermes 模型配置 config.yaml 路径。委托给 agent.hermes_config 模块的权威实现。"""
    # 延迟 import 避免循环依赖
    from fastapi_app.agent.hermes_config import get_hermes_runtime_config_path as _f
    return _f()


def get_skills_dir() -> Path:
    """Skills 根目录。统一收敛 hermes_config 的双路径。

    fallback 链：env LAOMA_SKILLS_DIR > paths.json(skills_dir) > hermes_home/skills
    hermes_home 由 hermes_config.get_hermes_home_path 权威提供，避免多入口分叉。
    """
    env = (os.getenv("LAOMA_SKILLS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cfg = _cfg_path(load_paths_config(), "skills_dir")
    if cfg:
        return cfg
    # 延迟 import 避免循环（hermes_config 反过来会读 get_hermes_runtime_config_path）
    from fastapi_app.agent.hermes_config import get_hermes_home_path
    return get_hermes_home_path() / "skills"


__all__ = [
    "get_repo_root",
    "get_data_dir",
    "get_paths_config_path",
    "load_paths_config",
    "save_paths_config",
    "get_template_lib_dir",
    "get_nodejs_dir",
    "get_openmontage_dir",
    "get_moneyprinter_dir",
    "get_hermes_runtime_config_path",
    "get_skills_dir",
]
