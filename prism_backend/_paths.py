"""打包入口用的路径解析(仅 stdlib,不触发 fastapi_app.settings)。

三份 PyInstaller service 入口(backend_service / celery_worker_service /
automation_worker_service)共享的后端根目录解析逻辑,避免各文件复制 60 行探测代码。

约束:
- 仅依赖 stdlib,绝不 import fastapi_app.* (打包入口在 fastapi_app 被 import 之前先跑本文件)。
- 探测限深:__file__ parents[0..3] + sys._MEIPASS + env LAOMA_BACKEND_ROOT,
  不再向上无限爬(避免误匹配 C:\\ 上其它项目的 fastapi_app 目录)。
- 永不抛异常,任何异常降级到 here.parent(等价于 parents[1]/prism_backend) 的保守兜底。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_backend_root() -> Path:
    """解析 prism_backend 根目录。

    优先级:
    1. env LAOMA_BACKEND_ROOT(用户显式配置,最高优先)
    2. sys._MEIPASS(PyInstaller 打包后临时解压目录)
    3. __file__ parents[0..3] 限深探测

    命中规则:
    - c/prism_backend/fastapi_app 存在 → c 是项目根,返回 c/prism_backend
    - c/fastapi_app 存在 → c 本身就是 prism_backend 根,直接返回 c

    兜底:__file__ 在 prism_backend/_paths.py 下,parents[0]=prism_backend,
    parents[1]=项目根,保守指向 parents[1]/prism_backend(等价于 here.parent)。
    """
    try:
        here = Path(__file__).resolve()
        candidates: list[Path] = []

        env_root = (os.getenv("LAOMA_BACKEND_ROOT") or "").strip()
        if env_root:
            candidates.append(Path(env_root).expanduser().resolve())

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass).resolve())

        for i in range(0, 4):
            if i < len(here.parents):
                candidates.append(here.parents[i])

        for c in candidates:
            if (c / "prism_backend" / "fastapi_app").is_dir():
                return c / "prism_backend"
            if (c / "fastapi_app").is_dir():
                return c

        return (here.parents[1] / "prism_backend") if len(here.parents) >= 1 else Path("prism_backend")
    except Exception:
        return Path("prism_backend")


__all__ = ["get_backend_root"]
