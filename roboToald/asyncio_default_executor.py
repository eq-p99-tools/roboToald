"""Install a larger asyncio default ThreadPoolExecutor for ``asyncio.to_thread`` / ``run_in_executor``.

Python's default is ``min(32, (os.cpu_count() or 1) + 4)``, which can queue work during reconnect storms.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from roboToald import config

logger = logging.getLogger(__name__)

_loops_configured: set[int] = set()


def install_enlarged_default_executor(loop: asyncio.AbstractEventLoop, *, thread_name_prefix: str) -> None:
    """Replace the loop's default executor once per loop with ``config.ASYNCIO_DEFAULT_THREAD_POOL_MAX_WORKERS``."""
    lid = id(loop)
    if lid in _loops_configured:
        return
    n = config.ASYNCIO_DEFAULT_THREAD_POOL_MAX_WORKERS
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=n, thread_name_prefix=thread_name_prefix)
    loop.set_default_executor(executor)
    _loops_configured.add(lid)
    logger.info("Default asyncio thread pool: max_workers=%s prefix=%s", n, thread_name_prefix)
