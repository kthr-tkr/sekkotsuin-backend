"""バックグラウンドのワーカー（AI ジョブ・通知の送信・予約のリマインド）。

uv run python -m app.worker
"""

import asyncio
import contextlib
import logging
import signal

from app.core.db import SessionLocal
from app.services.ai.jobs import run_one
from app.services.notify.queue import schedule_reminders, send_one

log = logging.getLogger("app.worker")
POLL_INTERVAL_SEC = 2.0
REMINDER_INTERVAL_SEC = 60.0


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker started")
    last_reminder = 0.0
    while not stop.is_set():
        worked = False
        try:
            if loop.time() - last_reminder >= REMINDER_INTERVAL_SEC:
                last_reminder = loop.time()
                async with SessionLocal() as db:
                    if n := await schedule_reminders(db):
                        log.info("scheduled %s reminders", n)
            # 通知は AI ジョブ（時間がかかる）より先に送る
            worked = await send_one() or await run_one()
        except Exception:
            log.exception("worker loop error")
        if not worked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SEC)
    log.info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
