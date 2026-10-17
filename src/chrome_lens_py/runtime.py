"""Where the warm daemon keeps its files, and how a process finds or starts it.

Standard library only, and deliberately light on imports: ``client.py`` loads
this before anything heavy, so every millisecond here is paid by every
``lens_scan`` run.

Layout (one per user)::

    <state dir>/daemon.json   who is listening, where, with which token
    <state dir>/daemon.sock   the socket, on POSIX
    <state dir>/daemon.lock   exists while one client is spawning the daemon
    <data dir>/daemon.log     the daemon's stdout/stderr
    <data dir>/service.json   port + token of the persistent (service) daemon

The state dir is Windows ``%LOCALAPPDATA%\\chrome-lens-py``, macOS
``~/Library/Caches/chrome-lens-py`` and Linux ``$XDG_RUNTIME_DIR/chrome-lens-py``
(else ``~/.cache/chrome-lens-py``). On Linux the runtime dir disappears at
logout, so what has to survive (the service token, the log) lives in
``~/.cache`` instead. ``LENS_STATE_DIR`` overrides both, which is what the
tests use.
"""

import os
import sys
import time

APP_DIR_NAME = "chrome-lens-py"
DAEMON_FILE = "daemon.json"
SOCKET_FILE = "daemon.sock"
LOCK_FILE = "daemon.lock"
LOG_FILE = "daemon.log"
SERVICE_FILE = "service.json"

STATE_DIR_ENV = "LENS_STATE_DIR"
# A lock older than this is a leftover from a spawn that never finished.
LOCK_STALE_SECONDS = 30.0
# AF_UNIX paths are limited to ~104 (macOS) / 108 (Linux) bytes.
MAX_UNIX_PATH = 100
MAX_LOG_BYTES = 1024 * 1024

_IS_WINDOWS = sys.platform == "win32"

# Environment the client forwards to the daemon: settings (LENS_*) and a few
# harmless knobs that change how output is rendered or where the config lives.
# Proxy variables are *not* forwarded - see docs/daemon.md.
ENV_PREFIX = "LENS_"
FORWARDED_ENV = ("NO_COLOR", "FORCE_COLOR", "COLORTERM", "TERM", "XDG_CONFIG_HOME")


def forwarded_env(environ) -> dict:
    """The part of `environ` that may cross to the daemon (both ends apply this).

    LENS_STATE_DIR says where the daemon lives, not how to run a request.
    """
    return {
        k: v
        for k, v in environ.items()
        if isinstance(v, str)
        and ((k.startswith(ENV_PREFIX) and k != STATE_DIR_ENV) or k in FORWARDED_ENV)
    }


# ------------------------------------------------------------------ locations


def _home() -> str:
    return os.path.expanduser("~")


def state_dir(create: bool = False) -> str:
    """Per-user directory for the discovery file, the socket and the lock."""
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        path = override
    elif _IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            _home(), "AppData", "Local"
        )
        path = os.path.join(base, APP_DIR_NAME)
    elif sys.platform == "darwin":
        path = os.path.join(_home(), "Library", "Caches", APP_DIR_NAME)
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime and os.path.isdir(runtime):
            path = os.path.join(runtime, APP_DIR_NAME)
        else:
            path = os.path.join(_home(), ".cache", APP_DIR_NAME)
    if create:
        ensure_private_dir(path)
    return path


def data_dir(create: bool = False) -> str:
    """Per-user directory for what must outlive a login (log, service token)."""
    override = os.environ.get(STATE_DIR_ENV)
    if override or _IS_WINDOWS or sys.platform == "darwin":
        return state_dir(create)
    path = os.path.join(_home(), ".cache", APP_DIR_NAME)
    if create:
        ensure_private_dir(path)
    return path


def daemon_file() -> str:
    return os.path.join(state_dir(), DAEMON_FILE)


def ensure_private_dir(path: str) -> None:
    """Create `path` (and parents) readable by this user only, where that exists.

    POSIX gets 0700 explicitly: ``makedirs(mode=...)`` is filtered by the umask
    and applies to the leaf only. On Windows the directory sits under
    ``%LOCALAPPDATA%``, whose ACL already limits it to the user (plus SYSTEM
    and Administrators), so there is nothing to set.
    """
    os.makedirs(path, exist_ok=True)
    if not _IS_WINDOWS:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


# ----------------------------------------------------------------- JSON files


def write_private_json(path: str, data: dict) -> None:
    """Atomically write `data`, readable by this user only (POSIX 0600)."""
    import json

    ensure_private_dir(os.path.dirname(path))
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        # Windows refuses to replace a file another process has open for an
        # instant; a reader polling daemon.json is exactly that.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 19 or not _IS_WINDOWS:
                    raise
                time.sleep(0.01)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str):
    """The JSON object in `path`, or None if absent, unreadable or not an object."""
    import json

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_daemon():
    """daemon.json if present and well-formed, else None."""
    data = read_json(daemon_file())
    if not data:
        return None
    if (
        data.get("transport") not in ("unix", "tcp")
        or not isinstance(data.get("address"), str)
        or not isinstance(data.get("token"), str)
        or not isinstance(data.get("pid"), int)
        or not isinstance(data.get("version"), str)
    ):
        return None
    return data


def remove_daemon_file(token=None) -> None:
    """Delete daemon.json - only if it still describes `token`, when one is given.

    A dying daemon must not delete the file of the daemon that replaced it.
    """
    path = daemon_file()
    if token is not None:
        current = read_json(path)
        if current is not None and current.get("token") != token:
            return
    try:
        os.unlink(path)
    except OSError:
        pass


# ------------------------------------------------------------------ processes


def pid_alive(pid: int) -> bool:
    """Is a process with this id running? Never signals it.

    ``os.kill(pid, 0)`` is the POSIX idiom, but on Windows ``os.kill`` with any
    signal other than the two console events calls TerminateProcess - it would
    kill the daemon it was meant to check on.
    """
    if pid <= 0:
        return False
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


# ------------------------------------------------------------------ spawn lock


def acquire_spawn_lock(stale_after: float = LOCK_STALE_SECONDS) -> bool:
    """Become the one process that spawns the daemon. True = you hold the lock.

    O_EXCL creation is atomic on every platform we run on, so two clients that
    both find no daemon cannot both win. The daemon deletes the lock once it is
    listening; one that never gets that far leaves a lock that goes stale.
    """
    path = os.path.join(state_dir(create=True), LOCK_FILE)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - os.stat(path).st_mtime
            except OSError:
                continue  # vanished between the two calls: try again
            # A file written a moment ago can carry an mtime a hair *ahead* of
            # time.time() on Windows (different clock sources and resolution),
            # making the age negative; that must not count as "fresher than
            # zero". stale_after <= 0 means any existing lock is stale.
            if stale_after > 0 and age < stale_after:
                return False
            try:
                os.unlink(path)
            except OSError:
                return False
            continue
        except OSError:
            return False
        try:
            os.write(fd, f"{os.getpid()} {time.time():.0f}\n".encode())
        finally:
            os.close(fd)
        return True
    return False


def release_spawn_lock() -> None:
    try:
        os.unlink(os.path.join(state_dir(), LOCK_FILE))
    except OSError:
        pass


# ----------------------------------------------------------------------- spawn


def is_compiled() -> bool:
    """True for a Nuitka / frozen build, where sys.executable is not a Python."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _isolated() -> bool:
    return bool(sys.flags.isolated)


def daemon_command(extra_args) -> list:
    """The command line that starts ``lens_scan <extra_args>`` in a new process.

    Three kinds of install can own the name ``lens_scan``:

    * a source checkout or pip install: ``python -m chrome_lens_py``;
    * the portable Windows build: the same, with ``-I`` (isolated mode) kept,
      because its python.exe must not pick up the user's site-packages;
    * a Nuitka binary, which *is* the program: run argv[0], not sys.executable.
      For a onefile build sys.executable lives in a temp directory that is
      deleted when the launching process exits, so argv[0] (the file the user
      actually has) is the only safe thing to start.
    """
    args = list(extra_args)
    if is_compiled():
        candidate = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
        if candidate and not os.path.splitext(candidate)[1] and _IS_WINDOWS:
            candidate += ".exe"
        exe = candidate if candidate and os.path.isfile(candidate) else sys.executable
        return [exe, *args]
    cmd = [sys.executable]
    if _isolated():
        cmd.append("-I")
    return cmd + ["-m", "chrome_lens_py", *args]


def daemon_env() -> dict:
    """The environment for the spawned daemon.

    The daemon starts in the home directory, not the caller's, so anything
    that made the package importable *relative to the caller's cwd* - a
    relative PYTHONPATH entry, or running from a source checkout - would leave
    the child with "No module named chrome_lens_py" and the daemon silently
    never comes up. So relative PYTHONPATH entries are made absolute, and the
    directory this package was actually imported from goes first.
    """
    env = dict(os.environ)
    if is_compiled():
        return env
    entries = [
        os.path.abspath(p) for p in env.get("PYTHONPATH", "").split(os.pathsep) if p
    ]
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if package_root not in entries:
        entries.insert(0, package_root)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _open_log():
    path = os.path.join(data_dir(create=True), LOG_FILE)
    try:
        if os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    return os.fdopen(fd, "ab")


def spawn_detached(extra_args) -> bool:
    """Start the daemon in the background and return at once. True if it started.

    Nothing of ours may stay attached to the caller. ShareX reads lens_scan's
    stdout until EOF, so a daemon that inherited that pipe would keep it open
    and ShareX would wait for the daemon to exit; hence stdin/stdout/stderr are
    replaced outright, and (with close_fds) nothing else is inherited.
    """
    import subprocess

    try:
        log = _open_log()
    except OSError:
        log = None
    out = log if log is not None else subprocess.DEVNULL
    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=out,
        close_fds=True,
        cwd=_home(),
        env=daemon_env(),
    )
    cmd = daemon_command(extra_args)
    try:
        if _IS_WINDOWS:
            flags = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
            try:
                # Leave the caller's job object if it allows it, so the daemon
                # outlives a launcher that kills its job on exit.
                subprocess.Popen(
                    cmd,
                    creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                    **kwargs,
                )
            except OSError:
                subprocess.Popen(cmd, creationflags=flags, **kwargs)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kwargs)
        return True
    except (OSError, ValueError):
        return False
    finally:
        if log is not None:
            log.close()


# --------------------------------------------------------------- supervisor

SUPERVISE_FLAG = "--daemon-supervise"
SERVICE_DAEMON_ARGS = ["--serve", "--service"]


SUPERVISOR_LOG_FILE = "supervisor.log"


def _log_line(message: str) -> None:
    """Append to supervisor.log; the supervisor may run with no console at all.

    A file of its own, not daemon.log: on Windows the daemon writes through an
    inherited handle that does not keep append semantics, so it writes from
    its own offset and would overwrite whatever the supervisor added there.
    """
    try:
        path = os.path.join(data_dir(create=True), SUPERVISOR_LOG_FILE)
        try:
            if os.path.getsize(path) > MAX_LOG_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "ab") as log:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log.write(f"{stamp} supervisor: {message}\n".encode("utf-8", "replace"))
    except OSError:
        pass


def _spawn_child(cmd):
    import subprocess

    log = _open_log()
    try:
        kwargs = dict(
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            cwd=_home(),
            env=daemon_env(),
        )
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(cmd, **kwargs)
    finally:
        log.close()


def supervise(
    child_args=None,
    *,
    max_backoff: float = 60.0,
    healthy_after: float = 60.0,
    spawn=None,
    sleep=time.sleep,
    clock=time.monotonic,
) -> int:
    """Keep the service daemon alive: run it as a child, restart it if it dies.

    This is the Windows half of "always on". macOS (launchd KeepAlive) and
    Linux (systemd Restart=on-failure) restart a crashed daemon themselves; a
    Startup-folder shortcut only starts it at logon, so a crash used to leave
    ShareX's uploader talking to nothing until the next login.

    The rule is the exit code. 0 is a deliberate stop - `--daemon-stop`,
    `--uninstall-service`, a shutdown request - and ends the supervisor too.
    Anything else is a crash and is restarted, after 1 s, doubling to
    `max_backoff`; a child that stayed up `healthy_after` seconds resets the
    delay, so a crash loop backs off while a rare crash recovers at once.
    """
    child_args = list(SERVICE_DAEMON_ARGS if child_args is None else child_args)
    spawn = spawn or _spawn_child
    delay = 1.0
    while True:
        started = clock()
        try:
            proc = spawn(daemon_command(child_args))
        except OSError as e:
            _log_line(f"could not start the daemon ({e}); retrying in {delay:g}s")
            sleep(delay)
            delay = min(delay * 2, max_backoff)
            continue
        _log_line(f"daemon started (pid {proc.pid})")
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            return 130
        if code == 0:
            _log_line("daemon stopped on request; supervisor exiting")
            return 0
        if clock() - started >= healthy_after:
            delay = 1.0
        _log_line(f"daemon exited with code {code}; restarting in {delay:g}s")
        sleep(delay)
        delay = min(delay * 2, max_backoff)
