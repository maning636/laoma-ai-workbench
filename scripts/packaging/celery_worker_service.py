import os
import sys
from pathlib import Path

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

from fastapi_app.tasks.celery_app import celery_app  # noqa: E402
from fastapi_app.tasks import publish_tasks  # noqa: E402,F401


def main() -> None:
    loglevel = os.getenv("CELERY_LOGLEVEL", "info")
    pool = os.getenv("CELERY_POOL", "threads")
    concurrency = int(os.getenv("CELERY_CONCURRENCY", "1000"))
    hostname = os.getenv("CELERY_HOSTNAME", "prism-worker@packaged")

    celery_app.worker_main(
        [
            "worker",
            f"--loglevel={loglevel}",
            f"--pool={pool}",
            f"--concurrency={concurrency}",
            f"--hostname={hostname}",
        ]
    )


if __name__ == "__main__":
    main()
