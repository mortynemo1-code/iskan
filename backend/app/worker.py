"""Dedicated background worker process used by Docker Compose."""

import asyncio
import signal

from .database import connect_database, disconnect_database
from .discipline import discipline_worker
from .report_jobs import report_schedule_worker
from .retention_jobs import retention_worker
from .stream_policy_jobs import stream_policy_worker
from .stream_index_jobs import stream_index_worker
from .reclassification_jobs import reclassification_worker


async def run() -> None:
    await connect_database()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    tasks = [
        asyncio.create_task(discipline_worker(), name="discipline"),
        asyncio.create_task(report_schedule_worker(), name="reports"),
        asyncio.create_task(retention_worker(), name="retention"),
        asyncio.create_task(reclassification_worker(), name="reclassification"),
        asyncio.create_task(stream_policy_worker(), name="stream-policy"),
        asyncio.create_task(stream_index_worker(), name="stream-index"),
    ]
    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await disconnect_database()


if __name__ == "__main__":
    asyncio.run(run())
