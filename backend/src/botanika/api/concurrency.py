"""Small event-loop bridge for bounded synchronous Pi work."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable


# Keep synchronous camera/audio/model work bounded on a small Pi. The voice
# coordinator's own owner lock still serializes microphone/speaker ownership.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="botanika-api")


async def run_blocking(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous operation in the loop's executor.

    The bounded standard executor keeps short and long operations from
    occupying the FastAPI event-loop thread, while ``partial`` preserves
    keyword arguments. Polling the concurrent future avoids relying on a
    cross-thread event-loop callback (which is unreliable in the Python/ASGI
    harness used by the Pi image) and still propagates worker exceptions.
    """

    future = _EXECUTOR.submit(partial(function, *args, **kwargs))
    try:
        while not future.done():
            await asyncio.sleep(0.005)
        return future.result()
    except asyncio.CancelledError:
        future.cancel()
        raise


__all__ = ["run_blocking"]
