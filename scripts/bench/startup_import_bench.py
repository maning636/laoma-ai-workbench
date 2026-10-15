"""Measure how long it takes to `import fastapi_app.main` in a cold process.

Usage:
    python scripts/bench/startup_import_bench.py
    python scripts/bench/startup_import_bench.py --importtime

Writes a summary line like:
    TOTAL_IMPORTS_S=1.82  TOP_5=[('fastapi_app.main', 0.42), ...]

This is deliberately a pure import-time bench: it does NOT start uvicorn
or touch /health, so it can be run while production 7000 is live.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import tracemalloc


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--importtime", action="store_true",
                   help="also run `python -X importtime -c 'import fastapi_app.main'`")
    args = p.parse_args()

    # Warm cache: import sys/os first (they're always in prelude anyway).
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "prism_backend")))
    # Ensure prism_backend is first so fastapi_app resolves correctly
    os.environ.setdefault("LAOMA_DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data")))
    os.environ.setdefault("PLAYWRIGHT_AUTO_INSTALL", "0")

    t0 = time.perf_counter()
    import fastapi_app.main  # noqa: F401
    elapsed = time.perf_counter() - t0

    print(f"TOTAL_IMPORT_S={elapsed:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
