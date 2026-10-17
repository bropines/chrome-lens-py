"""Run the persistent daemon at every login: ``--install-service``.

ShareX's uploader mode posts screenshots to a daemon on a *fixed* port, so that
daemon has to be there without anyone having run a lens_scan command first.
What starts it is the platform's own per-user mechanism:

  Windows  a shortcut in the user's Startup folder (no admin rights, shows up
           in Settings > Apps > Startup, removed by deleting the file)
  macOS    a LaunchAgent in ~/Library/LaunchAgents (KeepAlive)
  Linux    a systemd --user unit

Every flavour runs ``lens_scan --serve --service``: fixed port and a token that
survive restarts (service.json), no idle exit. Only the file generation is
unit-tested here; the platform commands (launchctl, systemctl) are exercised by
hand on those systems.
"""

import logging
import os
import plistlib
import shlex
import subprocess
import sys
from typing import List, Optional

from rich.console import Console
from rich.markup import escape

from .. import client, runtime

console = Console()
logger = logging.getLogger(__name__)

SERVICE_NAME = "chrome-lens-py"
LAUNCH_AGENT_LABEL = "com.bropines.chrome-lens-py"
SHORTCUT_NAME = "Chrome Lens OCR daemon.lnk"


def service_command() -> List[str]:
    """What the login item runs.

    Windows gets the supervisor, which restarts a crashed daemon: a Startup
    shortcut, unlike launchd's KeepAlive or systemd's Restart=, does nothing
    after logon. Elsewhere the platform's own manager does that job.
    """
    if sys.platform == "win32":
        return runtime.daemon_command([runtime.SUPERVISE_FLAG])
    return runtime.daemon_command(runtime.SERVICE_DAEMON_ARGS)


# ------------------------------------------------------------------- Linux


def systemd_unit_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "systemd", "user", f"{SERVICE_NAME}.service")


def _systemd_quote(arg: str) -> str:
    # systemd expands %-specifiers and $-variables in ExecStart.
    return shlex.quote(arg.replace("%", "%%").replace("$", "$$")) if arg else "''"


def render_systemd_unit(command: List[str]) -> str:
    return (
        "[Unit]\n"
        "Description=chrome-lens-py daemon (Google Lens OCR for ShareX)\n"
        "\n"
        "[Service]\n"
        f"ExecStart={' '.join(_systemd_quote(a) for a in command)}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


# ------------------------------------------------------------------- macOS


def launch_agent_path() -> str:
    return os.path.join(
        os.path.expanduser("~"),
        "Library",
        "LaunchAgents",
        f"{LAUNCH_AGENT_LABEL}.plist",
    )


def render_launch_agent(command: List[str], log_path: str) -> bytes:
    return plistlib.dumps(
        {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": command,
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
        }
    )


# ----------------------------------------------------------------- Windows


def startup_folder() -> str:
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def shortcut_path() -> str:
    return os.path.join(startup_folder(), SHORTCUT_NAME)


def _conhost() -> str:
    return os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "System32", "conhost.exe"
    )


def windowless(command: List[str]) -> List[str]:
    """Run at logon without a console window.

    python.exe has a windowless twin, pythonw.exe. The compiled lens_scan.exe
    does not: it is a console program, and a minimised console still sits on
    the taskbar for as long as the daemon lives. `conhost.exe --headless`
    (Windows 10 1809 and later) hosts it with no window at all.
    """
    exe = command[0]
    name = os.path.basename(exe).lower()
    if name == "python.exe":
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(candidate):
            return [candidate, *command[1:]]
    if name.endswith(".exe") and name != "pythonw.exe":
        conhost = _conhost()
        if os.path.isfile(conhost):
            return [conhost, "--headless", *command]
    return command


def _powershell_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _create_shortcut(path: str, command: List[str]) -> None:
    arguments = subprocess.list2cmdline(command[1:])
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_powershell_quote(path)}); "
        f"$s.TargetPath = {_powershell_quote(command[0])}; "
        f"$s.Arguments = {_powershell_quote(arguments)}; "
        f"$s.WorkingDirectory = {_powershell_quote(os.path.expanduser('~'))}; "
        "$s.WindowStyle = 7; "  # minimized, for the console-subsystem exe
        "$s.Description = 'chrome-lens-py daemon (Google Lens OCR for ShareX)'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


# --------------------------------------------------------------- public API


def _run(cmd: List[str]) -> bool:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        console.print(f"[red]Could not run {escape(cmd[0])}:[/red] {escape(str(e))}")
        return False
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        console.print(
            f"[red]{escape(' '.join(cmd[:3]))} failed:[/red] {escape(detail)}"
        )
        return False
    return True


def _start_supervised_now() -> None:
    """Replace whatever daemon runs with the supervised service one, now."""
    info = client.live_daemon()
    if info is not None:
        client.shutdown(info)
    if not runtime.spawn_detached([runtime.SUPERVISE_FLAG]):
        console.print(
            "[yellow]Could not start it now; it starts at next login.[/yellow]"
        )
        return
    if client.wait_for_daemon() is None:
        console.print(
            "[yellow]The daemon did not answer yet; see "
            f"{escape(os.path.join(runtime.data_dir(), runtime.LOG_FILE))}.[/yellow]"
        )


def install_service(port: Optional[int] = None) -> bool:
    from ..daemon import ensure_service_config

    config = ensure_service_config(port)
    command = service_command()
    console.print(
        f"Daemon command: [cyan]{escape(' '.join(command))}[/cyan]\n"
        f"Port: [cyan]{config['port']}[/cyan] (token in "
        f"[cyan]{escape(os.path.join(runtime.data_dir(), runtime.SERVICE_FILE))}[/cyan])"
    )

    if sys.platform == "win32":
        path = shortcut_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _create_shortcut(path, windowless(command))
        except (OSError, subprocess.CalledProcessError) as e:
            console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
            return False
        console.print(f"Startup shortcut created: [cyan]{escape(path)}[/cyan]")
        _start_supervised_now()
    elif sys.platform == "darwin":
        path = launch_agent_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        log = os.path.join(runtime.data_dir(create=True), runtime.LOG_FILE)
        with open(path, "wb") as f:
            f.write(render_launch_agent(command, log))
        console.print(f"LaunchAgent written: [cyan]{escape(path)}[/cyan]")
        domain = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", domain, path])  # fine if not loaded yet
        if not _run(["launchctl", "bootstrap", domain, path]):
            return False
    else:
        path = systemd_unit_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_systemd_unit(command))
        console.print(f"systemd unit written: [cyan]{escape(path)}[/cyan]")
        if not (
            _run(["systemctl", "--user", "daemon-reload"])
            and _run(
                ["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"]
            )
        ):
            return False

    console.print(
        "[bold green]Done.[/bold green] The daemon starts at every login"
        + (" and is restarted if it crashes." if sys.platform == "win32" else ".")
    )
    return True


def uninstall_service() -> bool:
    ok = True
    if sys.platform == "win32":
        path = shortcut_path()
        removed = _remove(path)
    elif sys.platform == "darwin":
        path = launch_agent_path()
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", path])
        removed = _remove(path)
    else:
        path = systemd_unit_path()
        _run(["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"])
        removed = _remove(path)
        if removed:
            _run(["systemctl", "--user", "daemon-reload"])

    info = client.live_daemon()
    if info is not None:
        ok = client.shutdown(info) and ok
    # Forget the uploader token too: while service.json exists, a daemon the
    # client starts on demand is the persistent, fixed-port kind. The ShareX
    # uploader needs re-importing after the next --setup-sharex --mode uploader.
    if _remove(os.path.join(runtime.data_dir(), runtime.SERVICE_FILE)):
        console.print("Forgot the uploader token (service.json).")
    if removed:
        console.print(f"Removed [cyan]{escape(path)}[/cyan].")
    else:
        console.print("No service was installed.")
    return ok


def _remove(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        console.print(f"[red]Could not remove {escape(path)}:[/red] {escape(str(e))}")
        return False
