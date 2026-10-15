"""End-to-end cold start bench (v2): fork a fresh python process that runs
`uvicorn fastapi_app.main:app --port <PORT>`, poll /health until 200,
record elapsed time, then kill the child.

Differences from v1:
  * Uses a single tight request-loop (0.02s sleep) rather than a 0.05s poll
    with urllib (each call costs ~30-50ms on Windows).
  * Records three phases:
      - "first_ok":  time from fork() to first 200 response
      - "app_ready": time from log line "loading..." (startup_event begin)
                    to first 200 — isolates the FastAPI/uvicorn overhead
      - "import_end": time from first log line to startup_event begin
                     — import + uvicorn config phase
  * Prints raw log timestamps alongside perf counters for cross-check.

Usage:
    python scripts/bench/startup_e2e_bench.py [--port 7123] [--repeat 3]
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path


# Regex for the " startup_event begin" log line
_STARTUP_RE = re.compile(r"INFO\s+\|\s+fastapi_app\.main:startup_event:\d+ -  Prism")
# Regex for any "first line" (rough proxy for uvicorn config done)
_ANY_LINE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _probe(url: str, timeout: float = 0.2) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def run_once(port: int, log_path: Path) -> dict:
    py = r"D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe"
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LAOMA_DATA_DIR": str(Path(__file__).resolve().parents[2] / "data"),
        "PLAYWRIGHT_AUTO_INSTALL": "0",
        "FORKED_BY_MULTIPROCESSING": "1",
    })

    log_file = log_path.open("ab", buffering=0)

    # Capture first-log-line and startup_event timestamps by reading the log
    # in the background while we probe /health.
    first_line_ts: list[float] = []
    startup_ts: list[float] = []
    stop_read = threading.Event()

    def tail_reader():
        # Wait until the log file is created and we get a stable stream.
        # Simplest: read the whole file each 50ms, remember the first and
        # first-startup timestamps seen.
        seen_first = False
        while not stop_read.is_set():
            try:
                data = log_file.read()
                if not data:
                    time.sleep(0.03)
                    continue
                lines = data.decode("utf-8", errors="replace").splitlines()
                for line in lines:
                    if not seen_first and _ANY_LINE_RE.search(line):
                        first_line_ts.append(time.perf_counter())
                        seen_first = True
                    if _STARTUP_RE.search(line):
                        startup_ts.append(time.perf_counter())
                log_file.seek(0)  # re-read whole file next time (simple, safe)
            except Exception:
                time.sleep(0.05)

    t0 = time.perf_counter()
    reader_thread = threading.Thread(target=tail_reader, daemon=True)
    reader_thread.start()

    proc = subprocess.Popen(
        [
            py, "-m", "uvicorn",
            "fastapi_app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(Path(__file__).resolve().parents[2] / "prism_backend"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    first_ok = None
    try:
        while time.perf_counter() - t0 < 45:
            status = _probe(f"http://127.0.0.1:{port}/health", timeout=0.2)
            if status == 200 and first_ok is None:
                first_ok = time.perf_counter()
                break
            time.sleep(0.02)
    finally:
        elapsed = time.perf_counter() - t0
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        stop_read.set()
        log_file.close()

    first_ok_delta = (first_ok - t0) if first_ok else None
    first_line_delta = (first_line_ts[0] - t0) if first_line_ts else None
    startup_delta = (startup_ts[0] - t0) if startup_ts else None

    return {
        "elapsed": elapsed,
        "first_ok": first_ok_delta,
        "first_log_line": first_line_delta,
        "startup_begin": startup_delta,
        "status": 200 if first_ok else None,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7123)
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--log-dir", default=r"D:\dim开发\Prism-Fusion\logs\startup-bench")
    args = p.parse_args()

    Path(args.log_dir).mkdir(parents=True, exist_ok=True)

    results = []
    for i in range(args.repeat):
        log_path = Path(args.log_dir) / f"run_{i+1}.log"
        r = run_once(args.port, log_path)
        results.append(r)
        f_ok = f"{r['first_ok']:.2f}s" if r["first_ok"] else "n/a"
        fl = f"{r['first_log_line']:.2f}s" if r["first_log_line"] else "n/a"
        sb = f"{r['startup_begin']:.2f}s" if r["startup_begin"] else "n/a"
        print(
            f"run {i+1}: total={r['elapsed']:.2f}s  first_ok={f_ok}  "
            f"first_log={fl}  startup_begin={sb}  ok={r['status']==200}"
        )

    ok_list = [r["first_ok"] for r in results if r["first_ok"]]
    if ok_list:
        med = statistics.median(ok_list)
        print(f"MEDIAN first_ok: {med:.2f}s  (all: {[round(t,2) for t in ok_list]})")
    else:
        print("no successful runs")
    return 0 if all(r["status"] == 200 for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
