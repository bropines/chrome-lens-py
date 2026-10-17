"""Thin client: hand a ``lens_scan`` command line to a warm daemon.

A cold ``lens_scan`` spends most of its time importing Pillow, protobuf and
httpx and opening a fresh TLS connection to Google. A process that is already
running has done both. ShareX can only *execute a program* per screenshot, so
this module is what that program does first: if a daemon is up, forward the
command line to it and print its answer; otherwise do exactly what lens_scan
always did.

Two rules shape everything here.

* Standard library only, and nothing heavy imported at module level (see
  ``tests/test_client.py``, which checks sys.modules in a subprocess). The
  whole point is to be done before the heavy imports would have finished.
* Correctness never depends on the daemon. Any failure - no daemon, a stale
  file, a version mismatch, a refused or dropped connection, a garbled reply,
  a timeout - falls through to the ordinary in-process CLI, silently. OCR has
  no side effect except an overlay file, which running twice overwrites with
  the same bytes, so retrying locally after a daemon that died mid-request is
  safe.

Mode (``--daemon MODE`` > config ``daemon`` > ``LENS_DAEMON`` > ``auto``):

  auto  use the daemon if it is running; otherwise run in-process *and* start
        one in the background for next time.
  on    as auto, but wait (up to 5 s) for a daemon that is starting rather
        than run in-process.
  off   never touch the daemon.
"""

import os
import sys
import time

try:  # the primitive module; `socket` adds enum/selectors for features unused here
    import _socket as _sock
except ImportError:  # pragma: no cover
    import socket as _sock

from . import runtime
from .__about__ import __version__

CONNECT_TIMEOUT = 0.1
# What the daemon itself allows one request (server.REQUEST_TIMEOUT) plus slack.
READ_TIMEOUT = 330.0
CONTROL_TIMEOUT = 2.0
START_WAIT_SECONDS = 5.0
DEFAULT_IDLE_TIMEOUT = 600
MODES = ("auto", "on", "off")

# Long options the daemon never runs: they act on the machine (ShareX config,
# the config file, services), print version/help, or are the daemon itself.
LOCAL_ONLY_LONG = (
    "--serve",
    "--setup-sharex",
    "--update-config",
    "--version",
    "--help",
    "--install-service",
    "--uninstall-service",
)
LOCAL_ONLY_SHORT = ("-V", "-h")
MANAGE_FLAGS = ("--daemon-status", "--daemon-stop", "--daemon-start")


class _Unavailable(Exception):
    """The daemon could not be used; fall back. `refused` = nothing listens."""

    def __init__(self, reason: str, refused: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.refused = refused


# ------------------------------------------------------------- option reading


def _flag_value(argv, name):
    """Value of ``--name VALUE`` / ``--name=VALUE`` (last one wins), or None."""
    value = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == name and i + 1 < len(argv):
            value = argv[i + 1]
            i += 2
            continue
        if token.startswith(name + "="):
            value = token[len(name) + 1 :]
        i += 1
    return value


def _is_local_only(argv) -> bool:
    for token in argv:
        if token in LOCAL_ONLY_SHORT:
            return True
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            # argparse accepts unambiguous abbreviations; matching on a prefix
            # errs on the side of running locally, which is always correct.
            if len(name) >= 4 and any(f.startswith(name) for f in LOCAL_ONLY_LONG):
                return True
    return False


def _config_path(argv) -> str:
    explicit = _flag_value(argv, "--config-file")
    if explicit:
        return explicit
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "chrome-lens-py", "config.json")


def _normalise_mode(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in MODES:
            return lowered
    return None


def resolve_mode(argv, environ=None):
    """(mode, idle_timeout) from flag > config file > LENS_* env > defaults.

    An unusable value gives ``"off"``: the in-process CLI will then reject it
    with its normal configuration error, which is better than guessing here.
    """
    environ = os.environ if environ is None else environ
    config = {}
    path = _config_path(argv)
    if os.path.isfile(path):
        try:
            import json

            with open(path, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                config = loaded
        except (OSError, ValueError):
            config = {}

    raw_mode = _flag_value(argv, "--daemon")
    if raw_mode is None:
        raw_mode = config.get("daemon")
    if raw_mode is None:
        raw_mode = environ.get("LENS_DAEMON") or None
    mode = "auto" if raw_mode is None else _normalise_mode(raw_mode)

    raw_idle = _flag_value(argv, "--daemon-idle-timeout")
    if raw_idle is None:
        raw_idle = config.get("daemon_idle_timeout")
    if raw_idle is None:
        raw_idle = environ.get("LENS_DAEMON_IDLE_TIMEOUT") or None
    try:
        idle = DEFAULT_IDLE_TIMEOUT if raw_idle is None else int(raw_idle)
        if idle < 0:
            raise ValueError
    except (TypeError, ValueError):
        return "off", DEFAULT_IDLE_TIMEOUT
    return (mode or "off"), idle


# ------------------------------------------------------------------ transport


def _connect(info, timeout):
    if info["transport"] == "unix":
        sock = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
        target = info["address"]
    else:
        host, _, port = info["address"].rpartition(":")
        sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        target = (host, int(port))
    try:
        sock.settimeout(timeout)
        sock.connect(target)
        if info["transport"] != "unix":
            sock.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_NODELAY, 1)
    except ConnectionRefusedError:
        sock.close()
        raise _Unavailable("connection refused", refused=True)
    except FileNotFoundError:
        sock.close()
        raise _Unavailable("socket is gone", refused=True)
    except (OSError, ValueError) as e:
        sock.close()
        raise _Unavailable(f"cannot connect: {e}")
    return sock


def call(info, method, path, body=None, connect_timeout=CONNECT_TIMEOUT, timeout=None):
    """One HTTP/1.1 request to the daemon. Returns (status, parsed JSON or None).

    Hand-rolled over a raw socket: http.client would import email, ssl-adjacent
    machinery and parsers this path does not need.
    """
    import json

    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    head = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
        f"Authorization: Bearer {info['token']}\r\n"
        "Connection: close\r\n"
    )
    if body is not None:
        head += f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
    sock = _connect(info, connect_timeout)
    try:
        sock.settimeout(READ_TIMEOUT if timeout is None else timeout)
        sock.sendall(head.encode("latin-1") + b"\r\n" + payload)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as e:
        raise _Unavailable(f"connection lost: {e}")
    finally:
        sock.close()

    data = b"".join(chunks)
    head_bytes, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        raise _Unavailable("malformed reply")
    try:
        status = int(head_bytes.split(b" ", 2)[1])
    except (IndexError, ValueError):
        raise _Unavailable("malformed status line")
    length = None
    for line in head_bytes.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            try:
                length = int(value.strip())
            except ValueError:
                raise _Unavailable("malformed content-length")
    if length is not None and len(rest) < length:
        raise _Unavailable("reply cut short")
    if length is not None:
        rest = rest[:length]
    try:
        return status, json.loads(rest) if rest else None
    except ValueError:
        raise _Unavailable("reply is not JSON")


# --------------------------------------------------------------- daemon lookup


def live_daemon():
    """daemon.json for a daemon that may be running, else None.

    Cleans up after a daemon that is demonstrably gone. On POSIX that is a dead
    pid; on Windows the pid check needs ctypes (milliseconds), so it is left to
    the connection attempt, where a stale port simply refuses.
    """
    info = runtime.read_daemon()
    if info is None:
        return None
    if sys.platform != "win32" and not runtime.pid_alive(info["pid"]):
        runtime.remove_daemon_file(info["token"])
        return None
    return info


def shutdown(info, wait: float = 3.0) -> bool:
    """Ask a daemon to exit and wait until it has. True once it is gone."""
    try:
        call(info, "POST", "/v1/shutdown", {}, timeout=CONTROL_TIMEOUT)
    except _Unavailable:
        pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        current = runtime.read_daemon()
        if current is None or current["token"] != info["token"]:
            return True
        try:
            probe = _connect(info, CONNECT_TIMEOUT)
        except _Unavailable as e:
            if e.refused:
                runtime.remove_daemon_file(info["token"])
                return True
        else:
            probe.close()
        time.sleep(0.05)
    return False


def _responsive(info) -> bool:
    try:
        _connect(info, CONNECT_TIMEOUT).close()
        return True
    except _Unavailable:
        return False


def start_daemon(idle_timeout: int = DEFAULT_IDLE_TIMEOUT) -> bool:
    """Spawn a daemon unless another process is already doing so. True if spawned."""
    if not runtime.acquire_spawn_lock():
        return False
    if os.path.isfile(os.path.join(runtime.data_dir(), runtime.SERVICE_FILE)):
        # The user installed uploader mode: keep the daemon on its fixed port,
        # and on Windows under the supervisor, as the login item would.
        if sys.platform == "win32":
            args = [runtime.SUPERVISE_FLAG]
        else:
            args = list(runtime.SERVICE_DAEMON_ARGS)
    else:
        args = ["--serve", "--auto", "--daemon-idle-timeout", str(idle_timeout)]
    if runtime.spawn_detached(args):
        return True
    runtime.release_spawn_lock()
    return False


def wait_for_daemon(timeout: float = START_WAIT_SECONDS):
    """Poll until a freshly spawned daemon accepts connections, else None."""
    deadline = time.monotonic() + timeout
    while True:
        info = runtime.read_daemon()
        if info is not None and info["version"] == __version__:
            try:
                _connect(info, CONNECT_TIMEOUT).close()
                return info
            except _Unavailable:
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.02)


# ---------------------------------------------------------------- the request


def _build_request(argv) -> dict:
    def tty(stream):
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError):
            return False

    # The first of these that is a terminal, in the order rich asks.
    columns = None
    order = (1, 2) if sys.platform == "win32" else (0, 1, 2)
    for fd in order:
        try:
            columns = os.get_terminal_size(fd).columns or None
        except (OSError, ValueError):
            continue
        break
    env = runtime.forwarded_env(os.environ)
    return {
        "argv": list(argv),
        "cwd": os.getcwd(),
        "env": env,
        "stdin_is_tty": tty(sys.stdin),
        "stdout_is_tty": tty(sys.stdout),
        "stderr_is_tty": tty(sys.stderr),
        "columns": columns,
    }


def _write_stream(stream, text: str) -> None:
    """Write through the text layer, as the in-process CLI would.

    Going via sys.stdout (not .buffer) keeps newline translation identical to a
    local run; the stream is switched to UTF-8 first, as force_utf8_streams does.
    """
    if not text or stream is None:
        return
    try:
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        stream.buffer.write(text.encode("utf-8", "replace"))
        stream.flush()


def _forward(info, argv):
    """Send the command to the daemon. Returns the exit code, or None to run locally."""
    status, reply = call(info, "POST", "/v1/cli", _build_request(argv))
    if status != 200 or not isinstance(reply, dict):
        raise _Unavailable(f"daemon answered {status}")
    if reply.get("run_locally"):
        return None
    code, out, err = reply.get("exit_code"), reply.get("stdout"), reply.get("stderr")
    if (
        isinstance(code, bool)
        or not isinstance(code, int)
        or not isinstance(out, str)
        or not isinstance(err, str)
    ):
        raise _Unavailable("reply has the wrong shape")
    events = reply.get("events")
    if events is not None and not (
        isinstance(events, list)
        and all(
            isinstance(e, list)
            and len(e) == 2
            and e[0] in ("out", "err")
            and isinstance(e[1], str)
            for e in events
        )
    ):
        raise _Unavailable("reply has the wrong shape")
    # Only now, with a reply we trust, is anything written.
    if events:
        for tag, text in events:
            _write_stream(sys.stdout if tag == "out" else sys.stderr, text)
    else:
        _write_stream(sys.stdout, out)
        _write_stream(sys.stderr, err)
    return code


def try_remote(argv):
    """Run `argv` through the daemon. Returns its exit code, or None = run locally.

    Never raises (except KeyboardInterrupt, which means the user gave up).
    """
    try:
        if _is_local_only(argv):
            return None
        mode, idle = resolve_mode(argv)
        if mode == "off":
            return None

        info = live_daemon()
        if info is not None and info["version"] != __version__:
            # An older daemon would answer with older behaviour. Retire it.
            shutdown(info)
            info = None

        if info is None and mode == "on":
            start_daemon(idle)
            info = wait_for_daemon()

        if info is not None:
            try:
                return _forward(info, argv)
            except _Unavailable as e:
                if e.refused or not runtime.pid_alive(info["pid"]):
                    # Nothing listens, or the process is gone (on Windows a
                    # closed loopback port can take longer than our connect
                    # timeout to say so, hence the pid check as well).
                    runtime.remove_daemon_file(info["token"])
                elif _responsive(info):
                    # A daemon that is up but declined this request (an error
                    # reply, a timeout) is not a reason to start another.
                    return None
                # otherwise it died: run locally, and (auto) replace it

        if mode == "auto":
            start_daemon(idle)
        return None
    except KeyboardInterrupt:
        raise
    except BaseException:
        return None


# ------------------------------------------------------------------ management


def _duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def daemon_status() -> int:
    """Print what the daemon is doing. Exit 0 if running, 1 if not."""
    info = live_daemon()
    if info is None:
        print("lens_scan daemon: not running")
        return 1
    try:
        status, reply = call(info, "GET", "/v1/status", timeout=CONTROL_TIMEOUT)
    except _Unavailable as e:
        print(f"lens_scan daemon: recorded (pid {info['pid']}) but not answering: {e}")
        return 1
    if status != 200 or not isinstance(reply, dict):
        print(f"lens_scan daemon: unexpected reply ({status})")
        return 1
    idle_timeout = reply.get("idle_timeout") or 0
    idle_left = reply.get("idle_remaining")
    print("lens_scan daemon: running")
    print(f"  pid        {reply.get('pid', info['pid'])}")
    print(f"  version    {reply.get('version', info['version'])}")
    print(f"  transport  {info['transport']} {info['address']}")
    print(f"  uptime     {_duration(reply.get('uptime', 0))}")
    print(f"  requests   {reply.get('requests', 0)}")
    if idle_timeout and idle_left is not None:
        print(f"  idle       exits in {_duration(idle_left)} (timeout {idle_timeout}s)")
    else:
        print("  idle       never exits on its own")
    return 0


def daemon_stop() -> int:
    info = live_daemon()
    if info is None:
        print("lens_scan daemon: not running")
        return 0
    if shutdown(info):
        print("lens_scan daemon: stopped")
        return 0
    print("lens_scan daemon: did not stop in time", file=sys.stderr)
    return 1


def daemon_start(idle_timeout: int = DEFAULT_IDLE_TIMEOUT) -> int:
    info = live_daemon()
    if info is not None and info["version"] == __version__:
        try:
            _connect(info, CONNECT_TIMEOUT).close()
            print(f"lens_scan daemon: already running (pid {info['pid']})")
            return 0
        except _Unavailable:
            pass
    if info is not None:
        shutdown(info)
    start_daemon(idle_timeout)
    info = wait_for_daemon()
    if info is None:
        log = os.path.join(runtime.data_dir(), runtime.LOG_FILE)
        print(f"lens_scan daemon: did not start; see {log}", file=sys.stderr)
        return 1
    print(f"lens_scan daemon: started (pid {info['pid']})")
    return 0


def manage(argv):
    """Handle --daemon-status/-stop/-start. Returns an exit code, or None if absent."""
    chosen = [f for f in MANAGE_FLAGS if f in argv]
    if not chosen:
        return None
    if len(chosen) > 1:
        print(f"{' and '.join(chosen)} cannot be used together.", file=sys.stderr)
        return 1
    if chosen[0] == "--daemon-status":
        return daemon_status()
    if chosen[0] == "--daemon-stop":
        return daemon_stop()
    _, idle = resolve_mode(argv)
    return daemon_start(idle)


# ----------------------------------------------------------------- entry point


def entry(argv=None) -> None:
    """The console script. Try the daemon, otherwise run the CLI as ever."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == [runtime.SUPERVISE_FLAG]:
        # The always-on service on Windows: stdlib only, no CLI at all.
        if runtime.should_respawn_direct():
            sys.exit(0 if runtime.spawn_detached([runtime.SUPERVISE_FLAG]) else 1)
        sys.exit(runtime.supervise())
    try:
        managed = manage(argv)
        if managed is not None:
            sys.exit(managed)
        code = try_remote(argv)
    except KeyboardInterrupt:
        sys.exit(130)
    if code is not None:
        sys.exit(code)
    from .cli.main import run  # the heavy imports start here

    run()
