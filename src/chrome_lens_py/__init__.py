"""chrome-lens-py: Google Lens OCR and translation.

The public names are resolved lazily (PEP 562). Importing the package costs
almost nothing, so ``chrome_lens_py.client`` - the thin client that lets
``lens_scan`` hand a request to a warm daemon - can run before Pillow, protobuf
and httpx are loaded. ``from chrome_lens_py import LensAPI`` still works; it just
pays the import at that moment instead of at ``import chrome_lens_py``.

``__version__`` stays an eager import on purpose: ``__about__`` has no imports,
so making it lazy would save nothing.
"""

from .__about__ import __version__

# `typing` costs several milliseconds to import, and this package is imported
# on the hot path of every lens_scan run.
TYPE_CHECKING = False

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDEs only
    from typing import Any, List  # noqa: F401

    from .api import LensAPI  # noqa: F401
    from .exceptions import (  # noqa: F401
        LensAPIError,
        LensException,
        LensImageError,
        LensProtobufError,
    )

_LAZY = {
    "LensAPI": ".api",
    "LensException": ".exceptions",
    "LensAPIError": ".exceptions",
    "LensImageError": ".exceptions",
    "LensProtobufError": ".exceptions",
}

__all__ = ["__version__", *_LAZY]


def __getattr__(name):  # type: (str) -> Any
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value  # later lookups skip __getattr__
    return value


def __dir__():  # type: () -> List[str]
    return sorted([*globals(), *_LAZY])
