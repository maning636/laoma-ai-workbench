"""B-B A/B test: measure baseline (backup) vs current (optimized) startup."""
from __future__ import annotations
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\dim开发\Prism-Fusion")
BACKEND = ROOT / "prism_backend"
MAIN = BACKEND / "fastapi_app" / "main.py"
ROUTER = BACKEND / "fastapi_app" / "api" / "v1" / "router.py"
MAIN_BAK = MAIN.with_suffix(MAIN.suffix + ".bak-20261016")
ROUTER_BAK = ROUTER.with_suffix(ROUTER.suffix + ".bak-20261016")
BENCH = ROOT / "scripts" / "bench" / "startup_e2e_bench.py"
PY = ROOT / "prismenv" / "Scripts" / "python.exe"


def run_variant(label: str, repeat: int = 3) -> list[float]:
    times = []
    for i in range(repeat):
        log_path = ROOT / "logs" / "startup-bench" / f"{label}_run_{i+1}.log"
        r = subprocess.run(
            [
                str(PY), str(BENCH),
                "--port", "7123",
                "--repeat", "1",
                "--log-dir", str(ROOT / "logs" / "startup-bench"),
            ],
            capture_output=True, text=True, timeout=60,
        )
        stdout = r.stdout
        # Parse "MEDIAN first_ok: X.XXs"
        import re
        m = re.search(r"MEDIAN first_ok: ([\d.]+)s", stdout)
        if m:
            t = float(m.group(1))
            times.append(t)
            print(f"  {label} #{i+1}: {t:.2f}s")
        else:
            print(f"  {label} #{i+1}: PARSE FAIL")
            print(stdout[-500:])
    return times


def restore(src: Path, dst: Path):
    shutil.copy2(src, dst)


def main():
    print("=== BASELINE (backup) ===")
    restore(MAIN_BAK, MAIN)
    restore(ROUTER_BAK, ROUTER)
    base_times = run_variant("base")

    print("=== OPTIMIZED (current) ===")
    # We don't have a "new" copy anymore; we need to regenerate it.
    # Actually: current on disk is already the optimized version IF we've
    # restored from .new. Let me just re-apply the diff by reading from
    # the .new we saved.
    new_main = BACKEND / "fastapi_app" / "main.py.new"
    new_router = BACKEND / "fastapi_app" / "api" / "v1" / "router.py.new"
    if not new_main.exists():
        print("ERROR: .new files not found; cannot run optimized variant")
        return 1
    restore(new_main, MAIN)
    restore(new_router, ROUTER)
    opt_times = run_variant("opt")

    print()
    print(f"baseline median: {statistics.median(base_times):.2f}s  all={[round(t,2) for t in base_times]}")
    print(f"optimized median: {statistics.median(opt_times):.2f}s  all={[round(t,2) for t in opt_times]}")
    print(f"improvement: {statistics.median(base_times) - statistics.median(opt_times):.2f}s "
          f"({(1 - statistics.median(opt_times)/statistics.median(base_times))*100:.1f}%)")

    # Cleanup: leave the optimized version on disk
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
