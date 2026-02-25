import asyncio
import logging
import signal
from typing import Iterable, Callable

from core.logging import setup_logging
from core.orchestrator import Orchestrator


def _register_signals(
    loop: asyncio.AbstractEventLoop,
    handlers: Iterable[int],
    on_signal: Callable[[int], None],
) -> None:
    for sig in handlers:
        loop.add_signal_handler(sig, lambda s=sig: on_signal(s))


async def main() -> None:
    setup_logging()
    stop_event = asyncio.Event()

    def _on_signal(sig: int) -> None:
        logging.getLogger("Signal").info("Received signal %s, shutting down.", sig)
        stop_event.set()

    orchestrator = Orchestrator()

    loop = asyncio.get_running_loop()
    _register_signals(loop, [signal.SIGINT, signal.SIGTERM], _on_signal)

    await orchestrator.start()
    await asyncio.wait(
        [
            asyncio.create_task(orchestrator.run()),
            asyncio.create_task(stop_event.wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
