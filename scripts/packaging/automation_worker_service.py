import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 _paths(仅 stdlib,不触发 fastapi_app.settings)以做根目录探测。
# 双 try 兼容源码与 PyInstaller 打包两种布局。
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

from automation_worker.worker import app  # noqa: E402


def main() -> None:
    host = os.getenv("AUTOMATION_WORKER_HOST", "127.0.0.1")
    port = int(os.getenv("AUTOMATION_WORKER_PORT", "7001"))

    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
