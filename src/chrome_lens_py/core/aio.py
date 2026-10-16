"""asyncio helpers that keep objects usable across event loops."""

import asyncio
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class LoopLocal(Generic[T]):
    """An asyncio primitive created lazily, once per running event loop.

    On Python 3.9 a Lock or Semaphore binds to the event loop current at
    construction. LensAPI is routinely built outside any loop - at module
    level, or before ``asyncio.run`` - and the primitive then belongs to a loop
    that is never run, so the first ``async with`` fails with "attached to a
    different loop" (or, with no current loop at all, "There is no current
    event loop"). Creating it on first use inside the running loop avoids both,
    and a second ``asyncio.run`` with the same object gets a fresh primitive
    instead of a dead one.
    """

    __slots__ = ("_factory", "_loop", "_value")

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._value: Optional[T] = None

    def get(self) -> T:
        loop = asyncio.get_running_loop()
        if self._value is None or self._loop is not loop:
            self._value = self._factory()
            self._loop = loop
        return self._value
