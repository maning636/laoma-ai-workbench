"""Non-production diagnostic tasks.

These tasks exist so operators can verify the Celery broker/worker
pipeline without triggering any real side effects (no outbound HTTP,
no writes to platforms, no database mutation).

Only add new debug tasks here when they follow the same "no side
effects" rule. The task names are prefixed with ``debug.`` so that
accidental use in production paths is obvious from the queue logs.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from fastapi_app.tasks.celery_app import celery_app


@celery_app.task(name="debug.echo")
def debug_echo(payload: Any) -> dict[str, Any]:
    """Return ``payload`` unchanged after logging it.

    Designed as a "can this worker actually consume a task?" probe:
      * no network, no file writes, no DB, no platform API calls
      * always returns immediately
      * argument is optional and may be any JSON-serialisable value

    The result dict carries ``received`` (the echoed argument),
    ``worker_received_at`` (monotonic-free timestamp) so that a
    sender can compare wall-clock times if it wants to measure the
    broker round-trip.
    """
    worker_started = time.time()
    logger.info("[debug.echo] task received, payload_type={}", type(payload).__name__)
    try:
        # loguru handles dicts/lists fine; fall back to repr for exotic objects
        logger.info("[debug.echo] payload={}", payload)
    except Exception:  # pragma: no cover - defensive only
        logger.info("[debug.echo] payload=<unloggable: {}>", repr(payload))
    logger.info("[debug.echo] about to return")
    return {
        "ok": True,
        "received": payload,
        "worker_received_at": worker_started,
    }
