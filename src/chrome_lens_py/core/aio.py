"""asyncio helpers that keep objects usable across event loops."""

import asyncio
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class LoopLocal(Generic[T]):
    """An asyncio primitive created lazily, once per running event loop.

    A Lock or Semaphore binds itself to one event loop the first time it has to
    make a caller wait, and raises "is bound to a different event loop" if it
    is awaited from another one afterwards. LensAPI is routinely built outside
    any loop - at module level, or before ``asyncio.run`` - and a second
    ``asyncio.run`` with the same object would then hit a primitive belonging
    to a loop that has already closed. Creating it on first use inside the
    running loop gives each loop a live primitive of its own.
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
