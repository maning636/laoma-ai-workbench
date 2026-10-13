import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 _paths(仅 stdlib,不触发 fastapi_app.settings)以做根目录探测。
# 双 try 兼容源码(prism_backend 加 sys.path 后 from _paths)与 PyInstaller 打包
# (prism_backend 打包为子目录后 from prism_backend._paths)两种布局。
_path_src_root = Path(__file__).resolve().parents[2] / "prism_backend"
if str(_path_src_root) not in sys.path:
    sys.path.insert(0, str(_path_src_root))

try:
    from _paths import get_backend_root  # type: ignore[import-not-found]  # noqa: E402
except ModuleNotFoundError:
    from prism_backend._paths import get_backend_root  # noqa: E402

backend_root = get_backend_root()
os.chdir(backend_root)
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from fastapi_app.core.config import settings  # noqa: E402
from fastapi_app.main import app  # noqa: E402


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
