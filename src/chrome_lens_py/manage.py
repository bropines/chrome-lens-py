"""The ``lens_scan`` commands: status, daemon, service, sharex, update, config.

``lens_scan`` is two programs behind one name. One recognises text in an image
- that is ``lens_scan shot.png``, and everything in ``lens_scan help options``
is about it. The other manages the machinery that makes the first one fast: a
warm daemon, a login service, ShareX hotkeys. That second half used to be a
row of flags (``--daemon-status``, ``--install-service``, ``--setup-sharex``),
which look like options but behave like commands: they ignore the image, they
ignore each other, and ``--help`` buried them among sixty other lines.

So the machinery has verbs now - ``lens_scan status``, ``lens_scan daemon
restart``, ``lens_scan service install``, ``lens_scan update`` - and ``-h``
shows those first. Every old flag still works, because ShareX configurations,
Startup shortcuts and systemd units on people's machines contain them; they
are simply no longer what the help is about.

Two rules, the same as ``client.py``'s:

* standard library only, nothing heavy at module level. ``client.py`` reads
  this on every run, including the scan that is racing a warm daemon, so these
  commands answer in milliseconds and a scan pays nothing for them.
* anything that reports takes ``--json``, so none of it has to be screen-scraped.
"""

import json
import os
import sys

from . import runtime
from .__about__ import __version__

EXIT_OK = 0
EXIT_FAIL = 1
# sysexits.h's EX_USAGE. Not 2: that is "some images failed" for a scan, and a
# caller that cannot tell a typo from a half-finished batch learns nothing.
EXIT_USAGE = 64

DOCS = "https://github.com/bropines/chrome-lens-py"


class Usage(Exception):
    """The command line was wrong. ``topic`` is the help to point at."""

    def __init__(self, message: str, topic: str = ""):
        super().__init__(message)
        self.message = message
        self.topic = topic


# ----------------------------------------------------------------- small tools


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    # Flushed, not left to the buffer: `update` hands the terminal to uv or
    # brew next, and a redirected stdout would otherwise print our lines after
    # the output of the command they introduce.
    sys.stdout.flush()


def _row(label: str, value: str, width: int = 10) -> None:
    _out(f"  {label.ljust(width)} {value}")


def _print_json(data) -> None:
    _out(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False))


def duration(seconds) -> str:
    """``125`` -> ``2m 05s``; the one place this is spelled out."""
    try:
        seconds = int(max(0, float(seconds)))
    except (TypeError, ValueError):
        return "unknown"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def parse(rest, *, flags=(), values=(), topic=""):
    """(positionals, options) for a command's own little command line.

    Deliberately not argparse: this runs before the heavy imports, and a
    hand-written loop also lets an unknown option point at the right help
    instead of dumping sixty lines of scan options.
    """
    positional, options = [], {}
    index = 0
    while index < len(rest):
        token = rest[index]
        name = token.split("=", 1)[0]
        if token in flags:
            options[token.lstrip("-").replace("-", "_")] = True
        elif token in values or (name in values and "=" in token):
            if "=" in token:
                value = token.split("=", 1)[1]
            elif index + 1 < len(rest):
                value = rest[index + 1]
                index += 1
            else:
                raise Usage(f"{name} needs a value", topic)
            options[name.lstrip("-").replace("-", "_")] = value
        elif token.startswith("-") and token != "-":
            raise Usage(f"unknown option {token}", topic)
        else:
            positional.append(token)
        index += 1
    return positional, options


def _subcommand(positional, allowed, topic, default=None):
    if not positional:
        if default is not None:
            return default
        raise Usage(f"{topic} needs a subcommand: {' | '.join(allowed)}", topic)
    name = positional[0]
    if name not in allowed:
        raise Usage(f"unknown subcommand {name!r} for '{topic}'", topic)
    if len(positional) > 1:
        raise Usage(f"unexpected argument {positional[1]!r}", topic)
    return name


def _int(options, name, default=None):
    if name not in options:
        return default
    try:
        return int(options[name])
    except (TypeError, ValueError):
        raise Usage(f"--{name.replace('_', '-')} takes a number")


# --------------------------------------------------------------------- status


def install_info() -> dict:
    """Which copy of lens_scan this is, and how it was installed.

    Four things can own the name (pip, uv, a standalone build, a checkout) and
    "which one did I just run?" is the question behind most odd behaviour, so
    both the flavour and the paths are reported.
    """
    from . import update

    detected = update.detect()
    if runtime.is_compiled():
        flavour = "standalone build"
    elif any(
        part == "site-packages" for part in os.path.abspath(__file__).split(os.sep)
    ):
        flavour = "installed package"
    else:
        flavour = "source checkout"
    return {
        "version": __version__,
        "method": detected.kind,
        "method_label": detected.label,
        "flavour": flavour,
        "executable": sys.executable,
        "package": os.path.dirname(os.path.abspath(__file__)),
        "python": sys.version.split()[0],
        "clipboard": _clipboard_available(),
    }


def _clipboard_available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("pyperclip") is not None
    except (ImportError, ValueError):
        return False


def service_info() -> dict:
    """Is the daemon set up to start at login, and where is that written."""
    path = runtime.login_item_path()
    config = runtime.read_service()
    return {
        "installed": os.path.isfile(path),
        "mechanism": runtime.login_item_kind(),
        "path": path,
        "port": (config or {}).get("port"),
        "token_file": runtime.service_file() if config else None,
    }


def sharex_info() -> dict:
    if sys.platform != "win32":
        return {"supported": False}
    try:
        from .utils.sharex_setup import describe

        return describe()
    except Exception as e:  # a broken ShareX config must not break `status`
        return {"supported": True, "error": f"{type(e).__name__}: {e}"}


def status_report(*, sharex: bool = True) -> dict:
    from . import client

    config = client.config_path()
    report = {
        "install": install_info(),
        "config": {"path": config, "exists": os.path.isfile(config)},
        "state_dir": runtime.state_dir(),
        "log": runtime.log_file(),
        "daemon": client.daemon_report(),
        "service": service_info(),
    }
    if sharex:
        report["sharex"] = sharex_info()
    return report


def _daemon_line(daemon: dict) -> str:
    state = daemon.get("state")
    if state == "stopped":
        return "not running (one starts by itself on the next scan)"
    if state == "unresponsive":
        return f"recorded as pid {daemon.get('pid')} but not answering: {daemon.get('error')}"
    managed = "login service" if daemon.get("managed") == "service" else "on demand"
    stale = (
        f"  <- version {daemon.get('version')}, replaced on the next scan"
        if daemon.get("stale")
        else ""
    )
    return (
        f"running   pid {daemon.get('pid')}  up {duration(daemon.get('uptime'))}  "
        f"{daemon.get('requests', 0)} requests  ({managed}){stale}"
    )


def print_status(report: dict) -> None:
    install = report["install"]
    _out(
        f"lens_scan {install['version']}  -  {install['method_label']}, "
        f"Python {install['python']}"
    )
    _out()
    _row("daemon", _daemon_line(report["daemon"]))
    service = report["service"]
    if service["installed"]:
        port = service["port"]
        _row(
            "service",
            f"installed  starts at login on port {port}  ({service['mechanism']})",
        )
    else:
        _row(
            "service",
            f"not installed  ({service['mechanism']}; `lens_scan service install`)",
        )
    sharex = report.get("sharex")
    if sharex is not None and sharex.get("supported"):
        if sharex.get("error"):
            _row("sharex", f"could not be read: {sharex['error']}")
        elif sharex.get("configured"):
            bound = [
                f"{key} ({what})"
                for what, key in (
                    ("program", sharex.get("program_hotkey")),
                    ("uploader", sharex.get("uploader_hotkey")),
                )
                if key
            ]
            _row("sharex", "configured  " + ", ".join(bound))
        else:
            _row("sharex", "not configured  (`lens_scan sharex --mode both`)")
    _row(
        "clipboard",
        (
            "available"
            if install["clipboard"]
            else "missing  (install the 'clipboard' extra for -sx)"
        ),
    )
    config = report["config"]
    _row("config", config["path"] + ("" if config["exists"] else "  (no file yet)"))
    _row("files", report["state_dir"])
    _out()
    _out("  `lens_scan update --check` looks for a new version.")


def cmd_status(rest) -> int:
    positional, options = parse(rest, flags=("--json",), topic="status")
    if positional:
        raise Usage(f"status takes no arguments (got {positional[0]!r})", "status")
    report = status_report()
    if options.get("json"):
        _print_json(report)
    else:
        print_status(report)
    # Exit 0 unless something is actually wrong. A machine with no daemon
    # running is healthy - one starts on the next scan - but a login service
    # that is installed and has no daemon, or a daemon that stopped answering,
    # is a problem a script should be able to notice.
    daemon, service = report["daemon"], report["service"]
    if daemon["state"] == "unresponsive":
        return EXIT_FAIL
    if service["installed"] and daemon["state"] != "running":
        return EXIT_FAIL
    return EXIT_OK


# --------------------------------------------------------------------- daemon


def _tail(path: str, lines: int) -> list:
    """The last `lines` lines of a log file (they are capped at 1 MiB)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()[-lines:]


def print_logs(paths, lines: int) -> int:
    shown = False
    for path in paths:
        if not os.path.isfile(path):
            continue
        tail = _tail(path, lines)
        if shown:
            _out()
        _out(f"--- {path} ---")
        for line in tail:
            _out(line)
        if not tail:
            _out("(empty)")
        shown = True
    if not shown:
        _out("No log files yet. They appear once a daemon has run:")
        for path in paths:
            _out(f"  {path}")
    return EXIT_OK


def cmd_daemon(rest) -> int:
    from . import client

    positional, options = parse(
        rest,
        flags=("--json",),
        values=("--lines", "--idle-timeout"),
        topic="daemon",
    )
    action = _subcommand(
        positional, ("status", "start", "stop", "restart", "logs"), "daemon"
    )

    if action == "status":
        report = client.daemon_report()
        if options.get("json"):
            _print_json(report)
        else:
            print_daemon(report)
        return EXIT_OK if report["state"] == "running" else EXIT_FAIL
    if action == "logs":
        return print_logs([runtime.log_file()], _int(options, "lines", 40))

    idle = _int(options, "idle_timeout")
    if idle is None:
        _, idle = client.resolve_mode([])
    if action == "start":
        return client.daemon_start(idle)
    if action == "stop":
        return client.daemon_stop()
    code = client.daemon_stop()
    return code if code else client.daemon_start(idle)


def print_daemon(report: dict) -> None:
    state = report["state"]
    if state == "stopped":
        _out("lens_scan daemon: not running")
        return
    if state == "unresponsive":
        _out(
            f"lens_scan daemon: recorded (pid {report.get('pid')}) but not "
            f"answering: {report.get('error')}"
        )
        return
    _out("lens_scan daemon: running")
    _row("pid", str(report.get("pid")))
    _row(
        "version",
        str(report.get("version"))
        + (
            f"  (this lens_scan is {__version__}; the next scan replaces the daemon)"
            if report.get("stale")
            else ""
        ),
    )
    _row("transport", f"{report.get('transport')} {report.get('address')}")
    _row("uptime", duration(report.get("uptime")))
    _row("requests", str(report.get("requests", 0)))
    idle_timeout = report.get("idle_timeout") or 0
    idle_left = report.get("idle_remaining")
    if idle_timeout and idle_left is not None:
        _row("idle", f"exits in {duration(idle_left)} (timeout {idle_timeout}s)")
    else:
        _row("idle", "never exits on its own")


# -------------------------------------------------------------------- service


def cmd_service(rest) -> int:
    positional, options = parse(
        rest,
        flags=("--json",),
        values=("--port", "--lines"),
        topic="service",
    )
    action = _subcommand(
        positional,
        ("status", "install", "uninstall", "start", "stop", "restart", "logs"),
        "service",
    )

    if action == "status":
        from . import client

        info = service_info()
        daemon = client.daemon_report()
        if options.get("json"):
            _print_json({"service": info, "daemon": daemon})
            return (
                EXIT_OK
                if info["installed"] and daemon["state"] == "running"
                else EXIT_FAIL
            )
        if info["installed"]:
            _out("lens_scan service: installed")
            _row("starts", f"at every login ({info['mechanism']})")
            _row("file", info["path"])
            _row("port", str(info["port"]))
            _row("daemon", _daemon_line(daemon))
        else:
            _out("lens_scan service: not installed")
            _row("would be", f"{info['path']} ({info['mechanism']})")
            _row("daemon", _daemon_line(daemon))
            _out()
            _out("  `lens_scan service install` starts the daemon at every login.")
        return (
            EXIT_OK if info["installed"] and daemon["state"] == "running" else EXIT_FAIL
        )

    if action == "logs":
        paths = [runtime.log_file()]
        if sys.platform == "win32":
            paths.insert(0, runtime.supervisor_log_file())
        return print_logs(paths, _int(options, "lines", 40))

    from .utils import service  # rich and the platform commands live here

    if action == "install":
        return EXIT_OK if service.install_service(_int(options, "port")) else EXIT_FAIL
    if action == "uninstall":
        return EXIT_OK if service.uninstall_service() else EXIT_FAIL
    return EXIT_OK if service.control(action) else EXIT_FAIL


# --------------------------------------------------------------------- update


def cmd_update(rest) -> int:
    from . import client, update

    positional, options = parse(
        rest, flags=("--json", "--check", "--dry-run"), topic="update"
    )
    if positional:
        raise Usage(f"update takes no arguments (got {positional[0]!r})", "update")

    install = update.detect()
    newest = update.latest()
    available = bool(newest and update.is_newer(newest, __version__))
    command = update.quote(install.command) if install.command else None

    # --json reports and stops. Something that parses the answer wants to
    # decide for itself whether to update, and an update's own output is not
    # JSON anyway - it belongs to uv, brew or pip.
    if options.get("json"):
        _print_json(
            {
                "version": __version__,
                "latest": newest,
                "update_available": available,
                "method": install.kind,
                "method_label": install.label,
                "command": command,
                "hint": install.hint or None,
            }
        )
        return EXIT_OK if newest is not None else EXIT_FAIL

    _out(f"Installed  {__version__}  ({install.label})")
    if newest is None:
        _out("Latest     could not be checked (no answer from pypi.org)")
    elif available:
        _out(f"Latest     {newest}  <- update available")
    else:
        _out(f"Latest     {newest}  (up to date)")

    if options.get("check"):
        if available:
            _out()
            _out("  Run `lens_scan update` to install it.")
        return EXIT_OK if newest is not None else EXIT_FAIL

    if install.command is None:
        _out()
        _out(f"This install updates itself differently: {install.hint}")
        return EXIT_OK

    if options.get("dry_run"):
        _out()
        _out(f"Would run: {command}")
        return EXIT_OK

    # Up to date and asked to update anyway: the command is still run, because
    # a release can be re-tagged, a file can go missing, and "reinstall" is a
    # reasonable thing to want. It just says so first.
    if not available and newest is not None:
        _out()
        _out("Already the newest release; reinstalling it.")

    _out()
    _out(f"Running: {command}")

    # The daemon holds the files that are about to be replaced, and an old one
    # left running would keep answering with the old behaviour until something
    # noticed the version change. Stop it, update, then put back whatever was
    # running: the login service if there is one, nothing otherwise.
    report = client.daemon_report()
    was_running = report["state"] == "running"
    was_service = report.get("managed") == "service"
    if was_service:
        # Imported *before* the update replaces the file it would be read from:
        # an installer swapping site-packages under a running interpreter would
        # otherwise leave this process importing the new version of one module
        # into the old version of the rest.
        from .utils import service
    if was_running:
        client.daemon_stop()

    if install.fresh_shell:
        _out("The installer runs in a window of its own: Windows cannot replace")
        _out("a running program from inside itself.")
        return EXIT_OK if update.run_detached(install.command) else EXIT_FAIL

    code = update.run(install.command)
    if code != 0:
        _out(f"The update command failed ({code}).")
        if was_running:
            client.daemon_start()
        return EXIT_FAIL
    if was_service:
        service.control("restart")
    elif was_running:
        client.daemon_start()
    _out()
    _out("Updated. `lens_scan version` shows what is running now.")
    return EXIT_OK


# --------------------------------------------------------------------- config


def cmd_config(rest):
    positional, options = parse(
        rest, flags=("--json",), values=("--config-file",), topic="config"
    )
    action = _subcommand(positional, ("show", "path"), "config", default="show")
    override = options.get("config_file")
    if action == "path":
        from . import client

        path = override or client.config_path()
        if options.get("json"):
            _print_json({"path": path, "exists": os.path.isfile(path)})
        else:
            _out(path)
        return "exit", EXIT_OK
    argv = ["--show-config"]
    if override:
        argv += ["--config-file", override]
    if options.get("json"):
        argv.append("--json")
    return "argv", argv


# ----------------------------------------------------------------------- help


def short_help() -> str:
    """What ``lens_scan`` and ``lens_scan -h`` print.

    Hand-written, unlike ``help options``, which argparse generates from the
    real parser. Sixty options are a reference; this is the part somebody
    reads once.
    """
    return f"""lens_scan {__version__} - Google Lens OCR from the command line

Usage:
  lens_scan <image|url|folder> [ocr_lang] [options]   recognise text in an image
  lens_scan <command> [options]                       manage the machinery

Scanning:
  lens_scan shot.png                  recognise text, language auto-detected
  lens_scan shot.png -t en            ... and translate it into English
  lens_scan shot.png -sx              ... and copy the result to the clipboard
  lens_scan shot.png ja -t en -to out.png --manga     a manga page, translated
  lens_scan scans/ --format jsonl     a whole folder, one JSON object per image

Commands:
  status      one screen: version, daemon, login service, ShareX, clipboard
  daemon      the warm background process: status | start | stop | restart | logs
  service     keep it running from login: install | uninstall | status | logs
  sharex      set up the ShareX hotkeys (Windows)
  update      update lens_scan the way it was installed
  config      the settings in effect and where each one came from
  serve       run the HTTP API in this terminal
  version     version, install flavour and paths
  help        this text; `lens_scan help <command>` for one command

Most-used options:
  -t, --translate LANG      translate the recognised text into LANG
  -to, --translate-out F    save the image with the translation drawn on it
  -sx, --sharex             copy the result to the clipboard
  -b | -ol                  output blocks (speech bubbles) | one line per line
  --format FMT              text (default), json, jsonl, hocr or tsv
  -q, --quiet               result data only, nothing decorative
  -h, --help / -V, --version

  Every option:  lens_scan help options          Documentation:  {DOCS}#readme

Exit codes:
  0 everything worked   1 it failed   2 some images of several failed
  64 the command line was wrong   130 interrupted
"""


HELP = {
    "status": """lens_scan status [--json]

One screen for "is this working": the version and how it was installed, the
warm daemon, the login service, the ShareX hotkeys, whether the clipboard
extra is there, and which config file is in effect.

It asks nothing of the network. Exits 0 when nothing is wrong, 1 when the
login service is installed but no daemon is running, or when a daemon is
recorded and no longer answers.
""",
    "daemon": """lens_scan daemon <subcommand>

  status [--json]          running? since when? how many requests?
  start [--idle-timeout S] start one now
  stop                     stop it
  restart                  stop it, then start it again
  logs [--lines N]         the end of the daemon log (default 40 lines)

The daemon keeps Python, Pillow and the TLS connection to Google warm, which
turns about 3 s per image into about 0.4 s. You do not have to start it:
`lens_scan` uses one if it is there and starts one in the background for next
time. It exits after 10 minutes idle (`--daemon-idle-timeout`, 0 = never),
unless the login service owns it, in which case it stays.

`status` exits 0 if a daemon is running and 1 if not, like `systemctl
is-active`.
""",
    "service": """lens_scan service <subcommand>

  status [--json]      installed? running? on which port?
  install [--port N]   start the daemon at every login, on a fixed port
  uninstall            remove that, and stop the daemon
  start | stop | restart
  logs [--lines N]     the end of the supervisor and daemon logs

What "install" writes is the platform's own per-user mechanism - a Startup
shortcut on Windows, a LaunchAgent on macOS, a systemd --user unit on Linux -
and needs no administrator rights. On Windows the login item runs a small
supervisor that restarts the daemon if it ever crashes; launchd and systemd do
that themselves.

This is what ShareX's uploader hotkey needs: it posts the capture straight to
a daemon that is already listening on a known port, so nothing has to start
per screenshot. `lens_scan sharex --mode uploader` installs it for you.
""",
    "sharex": """lens_scan sharex [--mode program|uploader|both] [-t LANG] [--port N]

Sets up ShareX (Windows) to run Lens OCR on a region capture.

  program   Ctrl+O runs lens_scan on the capture. Works with nothing running,
            and uses the warm daemon whenever there is one. The default.
  uploader  Ctrl+Shift+O posts the capture straight to an always-on daemon:
            no process per capture, the fastest path. Installs the login
            service too.
  both      both hotkeys - the fast one, and the one that always works.

  -t LANG   make the hotkey translate into LANG as well as recognise.

Every file is backed up next to itself before it is touched, and ShareX is
closed first so it cannot overwrite the edit on its way out.
""",
    "update": """lens_scan update [--check] [--dry-run] [--json]

Updates this copy the way it was installed: `uv tool upgrade`, `pipx upgrade`,
`brew upgrade`, `scoop update`, `pip install -U`, or re-running the install
script that put a standalone build here. The command is always printed before
it runs.

  --check     only compare this version with the newest release
  --dry-run   print the command that would run, without running it
  --json      report what it found and stop (never updates)

A running daemon is stopped first - it holds the files being replaced - and
the login service is started again afterwards. For a git checkout or a Docker
image, `update` says what to do instead of guessing.
""",
    "config": """lens_scan config [show|path] [--config-file FILE] [--json]

  show   every setting, its value, and where that value came from
         (command line > config file > LENS_* environment > default)
  path   the config file's location, whether or not it exists yet

Write settings with `--update-config`: run the command line you want once
with it, and those options become the defaults. For example
`lens_scan --daemon on --concurrency 8 --update-config`.
""",
    "serve": """lens_scan serve [--host ADDR] [--port N] [--token T] [--allow-origin O]

Runs the HTTP API in this terminal: POST /v1/ocr, /v1/region, /v1/ocr/raw and
GET /health. This is the server for other programs to use; the warm daemon
that speeds up your own `lens_scan` runs is a different thing and starts
itself (see `lens_scan help daemon`).

It binds 127.0.0.1 by default. A non-loopback --host demands --token, and no
browser origin is allowed unless you name it with --allow-origin: anyone who
can reach the port can spend your API quota on Google requests. It is an OCR
service, not a proxy to Google.
""",
    "version": """lens_scan version [--json]

The version, which copy of it is running (standalone build, installed package
or source checkout), the executable and package paths, the Python version and
whether the clipboard extra is installed.
""",
}


def cmd_help(rest):
    positional, _ = parse(rest, topic="help")
    if not positional:
        _out(short_help())
        return "exit", EXIT_OK
    topic = positional[0]
    if topic in ("options", "all", "--help", "-h"):
        return "argv", ["--help"]
    if topic in HELP:
        _out(HELP[topic])
        return "exit", EXIT_OK
    if topic in COMMANDS:
        _out(f"`lens_scan {topic}` has no help of its own yet.")
        return "exit", EXIT_OK
    raise Usage(f"no help for {topic!r}", "")


# ------------------------------------------------------------------- dispatch


def cmd_version(rest):
    positional, options = parse(rest, flags=("--json",), topic="version")
    if positional:
        raise Usage(f"version takes no arguments (got {positional[0]!r})", "version")
    if options.get("json"):
        _print_json(install_info())
        return "exit", EXIT_OK
    return "argv", ["--version"]  # the full CLI prints it as a table


def cmd_sharex(rest):
    positional, options = parse(
        rest,
        values=("--mode", "-t", "--translate", "--port"),
        topic="sharex",
    )
    if positional:
        raise Usage(f"unexpected argument {positional[0]!r}", "sharex")
    mode = options.get("mode", "program")
    if mode not in ("program", "uploader", "both"):
        raise Usage(f"--mode must be program, uploader or both, not {mode!r}", "sharex")
    lang = options.get("t") or options.get("translate")
    from .utils.sharex_setup import setup_sharex

    ok = setup_sharex(mode, lang, _int(options, "port"))
    return "exit", EXIT_OK if ok else EXIT_FAIL


def _serve(rest):
    return "argv", ["--serve", *rest]


# verb -> handler. A handler returns an exit code, or ("argv", argv) for a
# command the full CLI implements and whose command line is rewritten to the
# flags it already understands.
COMMANDS = {
    "status": cmd_status,
    "daemon": cmd_daemon,
    "service": cmd_service,
    "sharex": cmd_sharex,
    "update": cmd_update,
    "config": cmd_config,
    "serve": _serve,
    "version": cmd_version,
    "help": cmd_help,
}


def route(argv):
    """What to do with this command line.

    ``("exit", code)``  a command ran, or a usage error was reported;
    ``("argv", argv)``  a command the full CLI implements, rewritten to flags;
    ``None``            not a command - scan an image, as always.

    A first argument that is a verb is a command, even if a file of that name
    exists; ``lens_scan ./status`` scans the file. That is the same rule git,
    docker and cargo use, and it keeps `lens_scan status` from depending on
    the directory it runs in.
    """
    if not argv:
        return None
    verb, rest = argv[0], list(argv[1:])
    if verb in ("-h", "--help") and not rest:
        _out(short_help())
        return "exit", EXIT_OK
    handler = COMMANDS.get(verb)
    if handler is None:
        return None
    if rest and rest[0] in ("-h", "--help") and verb != "help":
        return route(["help", verb])
    try:
        outcome = handler(rest)
    except Usage as e:
        print(f"lens_scan: {e.message}", file=sys.stderr)
        hint = f"lens_scan help {e.topic}" if e.topic else "lens_scan help"
        print(f"Try `{hint}`.", file=sys.stderr)
        return "exit", EXIT_USAGE
    except KeyboardInterrupt:
        return "exit", 130
    if isinstance(outcome, tuple):
        return outcome
    return "exit", outcome
