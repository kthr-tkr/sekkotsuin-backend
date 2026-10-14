"""AI ジョブのワーカー。

uv run python -m app.worker
"""

import asyncio
import contextlib
import logging
import signal

from app.services.ai.jobs import run_one

log = logging.getLogger("app.worker")
POLL_INTERVAL_SEC = 2.0


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("ai worker started")
    while not stop.is_set():
        try:
            worked = await run_one()
        except Exception:
            log.exception("worker loop error")
            worked = False
        if not worked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SEC)
    log.info("ai worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
