"""The managed daemon: what ``lens_scan --serve --auto`` / ``--service`` runs.

``server.py`` is the HTTP half. This module is everything around it that makes
it a daemon a *client* can find and trust:

* a discovery file (``daemon.json``) written once the socket is listening and
  removed on the way out, atomically and readable by this user only;
* a private transport - an AF_UNIX socket inside a 0700 directory on POSIX,
  loopback TCP on an ephemeral port on Windows - plus a random bearer token;
* one LensAPI per distinct set of construction settings, kept alive between
  requests so the HTTP/2 + TLS connection to Google stays warm;
* an idle timeout, so a daemon nobody uses goes away by itself.

``--service`` is the same daemon with a fixed port and a token that survives
restarts (ShareX's uploader config contains it), and no idle timeout.
"""

import asyncio
import collections
import logging
import os
import secrets
import sys
import time
from functools import partial
from typing import Any, Dict, Mapping, Optional, Tuple

from . import client, runtime
from .__about__ import __version__
from .exceptions import LensConfigError
from .utils.config_manager import Settings, get_default_config_dir, resolve_settings

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 5.0
# How long an evicted LensAPI stays open for any request still using it.
EVICT_GRACE_SECONDS = 120.0
MAX_CACHED_APIS = 4
_NOISY_LOGGERS = ("PIL", "httpx", "httpcore", "hpack", "h2", "asyncio")


# ---------------------------------------------------------------- API sharing


class ApiCache:
    """LensAPI instances shared between requests, keyed by how they are built."""

    def __init__(self, max_size: int = MAX_CACHED_APIS):
        self.max_size = max_size
        self._items: "collections.OrderedDict[Tuple[Any, ...], Any]" = (
            collections.OrderedDict()
        )
        self._closers: set = set()

    async def acquire(self, settings: Settings, env: Mapping[str, str]) -> Any:
        from .cli import main as cli
        from .constants import DEFAULT_ENDPOINTS

        key = cli.api_cache_key(settings, env)
        api = self._items.get(key)
        if api is not None:
            self._items.move_to_end(key)
            return api
        kwargs = cli._api_kwargs(settings)
        # Spelled out, so a LENS_ENDPOINT in the daemon's *own* environment
        # (inherited from whoever started it) can never leak into a request.
        raw = (env.get("LENS_ENDPOINT") or "").strip()
        kwargs["endpoints"] = raw.split(",") if raw else list(DEFAULT_ENDPOINTS)
        api = cli.LensAPI(**kwargs)
        self._items[key] = api
        while len(self._items) > self.max_size:
            _, old = self._items.popitem(last=False)
            self._retire(old)
        return api

    def _retire(self, api: Any) -> None:
        async def later() -> None:
            await asyncio.sleep(EVICT_GRACE_SECONDS)
            await api.aclose()

        task = asyncio.ensure_future(later())
        self._closers.add(task)
        task.add_done_callback(self._closers.discard)

    async def aclose(self) -> None:
        for task in list(self._closers):
            task.cancel()
        apis, self._items = list(self._items.values()), collections.OrderedDict()
        for api in apis:
            try:
                await api.aclose()
            except Exception:
                logger.debug("closing a LensAPI failed", exc_info=True)


class DynamicApi:
    """The `api` the plain routes (/v1/ocr, /v1/ocr/raw) use.

    It looks the settings up per call - config file and environment as the
    daemon sees them now - so editing config.json takes effect without a
    restart, and shares the same cache (and so the same warm connection) as the
    forwarded CLI runs.
    """

    def __init__(self, cache: ApiCache, config_path: str, env: Mapping[str, str]):
        self.cache = cache
        self.config_path = config_path
        self.env = env

    async def _api(self) -> Any:
        settings = resolve_settings({}, self.config_path, env=self.env)
        return await self.cache.acquire(settings, self.env)

    async def process_image(self, *args: Any, **kwargs: Any) -> Any:
        return await (await self._api()).process_image(*args, **kwargs)

    async def process_region(self, *args: Any, **kwargs: Any) -> Any:
        return await (await self._api()).process_region(*args, **kwargs)


# -------------------------------------------------------------------- logging


class _RequestLogHandler(logging.Handler):
    """Send a forwarded request's log records back to *its* client's stderr.

    In an ordinary run `-l DEBUG` prints to the terminal. In the daemon the
    same records, emitted while that request's CliContext is active, are
    written into the request's captured stderr instead. Records with no active
    request (the server's own access log) are left to the daemon's log file.
    """

    _plain = logging.Formatter("%(message)s")
    _debug = logging.Formatter(
        "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )

    def emit(self, record: logging.LogRecord) -> None:
        from .cli.main import current_context

        ctx = current_context()
        if ctx is None or record.levelno < ctx.log_level:
            return
        # Libraries are quiet unless something is wrong, as in the CLI.
        if not record.name.startswith("chrome_lens_py") and (
            record.levelno < logging.WARNING
        ):
            return
        formatter = self._debug if ctx.log_level <= logging.DEBUG else self._plain
        try:
            ctx.err.write(formatter.format(record) + "\n")
        except Exception:
            self.handleError(record)


class _DaemonOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from .cli.main import current_context

        return current_context() is None


def install_daemon_logging(level: int = logging.INFO) -> None:
    """Daemon log -> stderr (which the spawner points at daemon.log)."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    # Root at DEBUG so a request that asks for -l DEBUG can get it; each
    # handler then applies its own threshold.
    root.setLevel(logging.DEBUG)
    base = logging.StreamHandler(sys.stderr)
    base.setLevel(level)
    base.addFilter(_DaemonOnly())
    base.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(base)
    root.addHandler(_RequestLogHandler())
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


# ------------------------------------------------------------------- the daemon


def service_config_path() -> str:
    return os.path.join(runtime.data_dir(), runtime.SERVICE_FILE)


def read_service_config() -> Optional[Dict[str, Any]]:
    data = runtime.read_json(service_config_path())
    if (
        data
        and isinstance(data.get("token"), str)
        and isinstance(data.get("port"), int)
    ):
        return data
    return None


def ensure_service_config(port: Optional[int]) -> Dict[str, Any]:
    """The persistent daemon's port and token, created on first use.

    The token is generated once and reused, because the ShareX uploader file
    carries a copy of it: rotating it on every start would break the uploader
    after each login.
    """
    current = read_service_config()
    if current is not None and (port is None or port == current["port"]):
        return current
    data = {
        "port": port if port is not None else (current or {}).get("port", 8765),
        "token": (current or {}).get("token") or secrets.token_urlsafe(32),
    }
    runtime.write_private_json(service_config_path(), data)
    return data


async def run_managed_daemon(
    settings: Settings,
    *,
    service: bool = False,
    port_override: Optional[int] = None,
) -> int:
    from .cli import main as cli
    from .server import LensServer

    install_daemon_logging()
    runtime.state_dir(create=True)

    existing = runtime.read_daemon()
    if existing is not None and existing["pid"] != os.getpid():
        if client._responsive(existing):
            if existing["version"] == __version__:
                logger.info("A daemon is already running (pid %s).", existing["pid"])
                runtime.release_spawn_lock()
                return 0
            logger.info(
                "Replacing daemon %s (pid %s).", existing["version"], existing["pid"]
            )
            await asyncio.to_thread(client.shutdown, existing)
        else:
            runtime.remove_daemon_file(existing["token"])

    unix_path: Optional[str] = None
    host, port = "127.0.0.1", 0
    if service:
        config = read_service_config()
        if config is None:
            runtime.release_spawn_lock()
            raise LensConfigError(
                "No service configuration. Run `lens_scan service install` "
                "(or `lens_scan sharex --mode uploader`) first."
            )
        token, port = config["token"], port_override or config["port"]
    else:
        token = secrets.token_urlsafe(32)
        if os.name == "posix":
            candidate = os.path.join(runtime.state_dir(), runtime.SOCKET_FILE)
            if len(os.fsencode(candidate)) <= runtime.MAX_UNIX_PATH:
                unix_path = candidate
                try:
                    os.unlink(candidate)  # a leftover from a daemon that crashed
                except OSError:
                    pass
        if port_override is not None:
            port = port_override

    cache = ApiCache()
    config_path = os.path.join(
        get_default_config_dir(environ=os.environ), "config.json"
    )
    idle = 0 if service else settings.daemon_idle_timeout
    server = LensServer(
        DynamicApi(cache, config_path, os.environ),
        host=host,
        port=port,
        token=token,
        unix_path=unix_path,
        cli_handler=partial(cli.run_cli_request, api_provider=cache.acquire),
        idle_timeout=idle,
    )

    def describe() -> Dict[str, Any]:
        return {
            "version": __version__,
            "pid": os.getpid(),
            "transport": "unix" if unix_path else "tcp",
            "address": unix_path or f"{host}:{server.port}",
            "token": token,
            "started_at": server.started_at,
            "managed": "service" if service else "auto",
        }

    ready = False
    heartbeat: Optional["asyncio.Task[None]"] = None
    prewarm: Optional["asyncio.Task[None]"] = None

    async def beat() -> None:
        """Keep daemon.json true, and notice being replaced."""
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            current = runtime.read_daemon()
            if current is None:
                runtime.write_private_json(runtime.daemon_file(), describe())
            elif current["token"] != token:
                logger.info("Another daemon took over; exiting.")
                server.request_stop()
                return

    async def warm() -> None:
        # Import-heavy first-request work, done before anyone is waiting: the
        # font lookup reads system font files.
        try:
            api = await cache.acquire(
                resolve_settings({}, config_path, env=os.environ), os.environ
            )
            resolve = getattr(api, "_get_font_path", None)
            if resolve is not None:
                await asyncio.to_thread(resolve)
            # Open the TLS (and HTTP/2) connection to Lens now, so the first
            # real request finds it ready. The reply (a 404/405 for a bare GET,
            # no API key attached) is thrown away; only the pooled connection
            # matters.
            handler = getattr(api, "request_handler", None)
            if handler is not None:
                http = await handler.get_client()
                await http.get(handler.endpoints[0], timeout=8)
        except Exception:
            logger.debug("warm-up skipped", exc_info=True)

    async def started() -> None:
        nonlocal heartbeat, prewarm, ready
        ready = True
        runtime.write_private_json(runtime.daemon_file(), describe())
        runtime.release_spawn_lock()
        heartbeat = asyncio.ensure_future(beat())
        prewarm = asyncio.ensure_future(warm())
        logger.info(
            "chrome-lens-py %s daemon (%s) ready on %s %s, idle timeout %s",
            __version__,
            "service" if service else "auto",
            "unix" if unix_path else "tcp",
            unix_path or f"{host}:{server.port}",
            f"{idle}s" if idle else "none",
        )

    try:
        await server.serve_forever(on_started=started)
    except OSError as e:
        logger.error("Could not start the daemon: %s", e)
        raise
    finally:
        for task in (heartbeat, prewarm):
            if task is not None:
                task.cancel()
        runtime.remove_daemon_file(token)
        if not ready:  # died before it could hand the lock over
            runtime.release_spawn_lock()
        await cache.aclose()
        logger.info("Daemon stopped after %.0fs.", time.time() - server.started_at)
    return 0
