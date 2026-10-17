"""``lens_scan update``: update this copy the way it was installed.

Half a dozen things can own the name ``lens_scan`` - uv, pipx, pip, Homebrew,
Scoop, the install scripts, a git checkout - and each has its own idea of how
an update happens. Running the wrong one is worse than not running any: `pip
install -U` into a Homebrew install, or an installer script over a uv tool,
leaves two copies and the wrong one earlier on PATH.

So this module answers two questions and nothing else:

* ``detect()``  - which install is this, and what command updates it;
* ``latest()``  - what is the newest released version.

The command is always printed before it runs, and ``--dry-run`` prints it
without running. Standard library only: ``client.py`` must stay light, and
``lens_scan update --check`` should be as quick as ``lens_scan status``.
"""

import os
import re
import sys
from typing import List, NamedTuple, Optional, Sequence, Tuple

from .__about__ import __version__

PACKAGE = "chrome-lens-py"
FORMULA = "bropines/tap/lens-scan"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
RAW = f"https://raw.githubusercontent.com/bropines/{PACKAGE}/main/scripts"
CHECK_TIMEOUT = 6.0


class Install(NamedTuple):
    """How this copy got here and what updates it.

    ``command`` is None when there is nothing we can sensibly run - a git
    checkout, a Docker image, a copy someone unzipped by hand - and ``hint``
    then says what to do instead. ``fresh_shell`` marks a command that
    replaces the very files it is running from, which Windows will not allow
    while they are open: those are handed to a new console window.
    """

    kind: str
    label: str
    command: Optional[List[str]] = None
    hint: str = ""
    fresh_shell: bool = False


# --------------------------------------------------------------- detection


def _parts(path: str) -> List[str]:
    """Lower-cased path components, for matching an install layout."""
    if not path:
        return []
    return [p.lower() for p in os.path.abspath(path).replace("\\", "/").split("/") if p]


def _run_in(*names: str) -> List[str]:
    """``[tool, ...]`` with the tool resolved on PATH where possible.

    uv, brew and scoop are usually on PATH; when they are not (a uv install
    whose shell profile has not been sourced), the known location is tried, so
    `lens_scan update` works in the shell the user happens to be in.
    """
    import shutil

    tool = names[0]
    found = shutil.which(tool)
    if not found:
        for candidate in (
            os.path.join(os.path.expanduser("~"), ".local", "bin", tool),
            os.path.join(os.path.expanduser("~"), ".cargo", "bin", tool),
            f"/opt/homebrew/bin/{tool}",
            f"/home/linuxbrew/.linuxbrew/bin/{tool}",
            f"/usr/local/bin/{tool}",
        ):
            if os.path.isfile(candidate) or os.path.isfile(candidate + ".exe"):
                found = candidate
                break
    return [found or tool, *names[1:]]


def _installer_command() -> Install:
    """Re-run the install script that put a standalone build here."""
    if sys.platform == "win32":
        return Install(
            kind="installer",
            label="standalone build (install.ps1)",
            command=[
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                # The window is its own, so it must stay open long enough to
                # be read - including when the installer stops on an error.
                f"try {{ irm {RAW}/install.ps1 | iex }} "
                "finally { Read-Host 'Press Enter to close' }",
            ],
            fresh_shell=True,
        )
    return Install(
        kind="installer",
        label="standalone build (install.sh)",
        command=["sh", "-c", f"curl -fsSL {RAW}/install.sh | sh"],
    )


def _scoop_app(parts: Sequence[str]) -> str:
    """The Scoop app name, so `lens-scan-portable` is not updated as `lens-scan`."""
    try:
        return parts[parts.index("apps") + 1]
    except (ValueError, IndexError):
        return "lens-scan"


def detect() -> Install:
    """Which install this is. Never raises; falls back to a described guess."""
    from . import runtime

    exe = sys.executable or ""
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    everywhere = _parts(exe) + _parts(package) + _parts(argv0)
    joined = "/".join(everywhere)

    if os.path.exists("/.dockerenv"):
        return Install(
            kind="docker",
            label="Docker image",
            hint=f"docker pull ghcr.io/bropines/{PACKAGE} and recreate the container.",
        )

    if "cellar" in everywhere or "/homebrew/" in f"/{joined}/" or "linuxbrew" in joined:
        return Install(
            kind="brew",
            label="Homebrew",
            command=_run_in("brew", "upgrade", FORMULA),
        )

    if "scoop" in everywhere and "apps" in everywhere:
        return Install(
            kind="scoop",
            label="Scoop",
            command=_run_in("scoop", "update", _scoop_app(everywhere)),
        )

    if "uv" in everywhere and "tools" in everywhere:
        requirement, pinned = _uv_requirement()
        if pinned:
            # `uv tool upgrade` honours the version the tool was installed
            # with, so a copy installed as `==3.8.0` can never move. Installing
            # the requirement again without the pin is the only way up, and
            # that recreates the environment - which on Windows cannot be done
            # from inside it, because this process is its python.exe.
            return Install(
                kind="uv",
                label="uv tool (pinned to this version)",
                command=_run_in(
                    "uv", "tool", "install", "--force", "--refresh", requirement
                ),
                fresh_shell=sys.platform == "win32",
            )
        return Install(
            kind="uv",
            label="uv tool",
            # --reinstall rather than a plain upgrade: uv then keeps the
            # environment (and so the interpreter this process is running) and
            # replaces the packages inside it, which is the only variant that
            # works from inside the tool itself on Windows. It also makes
            # `update` repair an install that is merely damaged.
            command=_run_in("uv", "tool", "upgrade", "--reinstall", PACKAGE),
        )

    if "pipx" in everywhere:
        return Install(
            kind="pipx", label="pipx", command=_run_in("pipx", "upgrade", PACKAGE)
        )

    if runtime.is_compiled() or _is_portable(exe, package):
        if "lens-scan" in everywhere or "lens_scan" in everywhere:
            return _installer_command()
        return Install(
            kind="standalone",
            label="standalone build (unzipped by hand)",
            hint=(
                "Download the archive for your platform from "
                f"https://github.com/bropines/{PACKAGE}/releases/latest and "
                "unzip it over this folder."
            ),
        )

    if _git_checkout(package):
        return Install(
            kind="source",
            label="source checkout",
            hint=f"git -C {os.path.dirname(package)} pull",
        )

    requirement = PACKAGE + ("[clipboard]" if _has_clipboard() else "")
    return Install(
        kind="pip",
        label="pip" + (" (in a virtualenv)" if sys.prefix != sys.base_prefix else ""),
        command=[sys.executable, "-m", "pip", "install", "--upgrade", requirement],
    )


def _uv_requirement() -> Tuple[str, bool]:
    """``("chrome-lens-py[clipboard]", pinned)`` from uv's receipt for this tool.

    uv writes ``uv-receipt.toml`` beside the tool's environment, recording what
    the tool was asked for: its extras, and any version it was pinned to. Both
    matter here - the extras must survive an update, and a pin means `uv tool
    upgrade` will cheerfully do nothing at all.
    """
    try:
        with open(os.path.join(sys.prefix, "uv-receipt.toml"), encoding="utf-8") as f:
            receipt = f.read()
    except OSError:
        return PACKAGE + ("[clipboard]" if _has_clipboard() else ""), False

    entry = ""
    for candidate in re.findall(r"\{[^}]*\}", receipt):
        if PACKAGE in candidate.replace("_", "-"):
            entry = candidate
            break
    extras = re.search(r"extras\s*=\s*\[([^\]]*)\]", entry)
    names = re.findall(r'"([^"]+)"', extras.group(1)) if extras else []
    if not names and _has_clipboard():
        names = ["clipboard"]
    requirement = PACKAGE + (f"[{','.join(names)}]" if names else "")
    pinned = bool(re.search(r'specifier\s*=\s*"\s*[=~<>!]', entry))
    return requirement, pinned


def _is_portable(exe: str, package: str) -> bool:
    """The portable Windows build: python.org's interpreter beside the package."""
    if sys.platform != "win32" or not exe:
        return False
    folder = os.path.dirname(exe)
    return os.path.isfile(os.path.join(folder, "lens_scan.cmd")) or os.path.isfile(
        os.path.join(os.path.dirname(package), "lens_scan.cmd")
    )


def _git_checkout(package: str) -> bool:
    if any(part == "site-packages" for part in _parts(package)):
        return False
    return os.path.isdir(os.path.join(os.path.dirname(package), ".git"))


def _has_clipboard() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("pyperclip") is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------------ versions


def parse_version(text: str) -> Tuple[int, ...]:
    """``"3.7.1"`` -> ``(3, 7, 1)``. Anything unparsable sorts lowest.

    Only release numbers are compared: PyPI's ``info.version`` is the latest
    *stable* release, and that is the only thing this is asked about.
    """
    numbers = re.findall(r"\d+", (text or "").strip())
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, than: str) -> bool:
    return parse_version(candidate) > parse_version(than)


def latest(timeout: float = CHECK_TIMEOUT) -> Optional[str]:
    """The newest released version, from PyPI. None if it could not be asked.

    PyPI rather than the GitHub API: every channel (brew, Scoop, the install
    scripts, uv, pip) is published from the same release workflow in the same
    run, so one number describes them all - and PyPI needs no token and has no
    rate limit worth worrying about.
    """
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        PYPI_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{PACKAGE}/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    version = (data.get("info") or {}).get("version")
    return version if isinstance(version, str) and version else None


# ------------------------------------------------------------------- running


def quote(command: Sequence[str]) -> str:
    """The command as the user would type it, for printing."""
    if sys.platform == "win32":
        import subprocess

        return subprocess.list2cmdline(list(command))
    import shlex

    return " ".join(shlex.quote(part) for part in command)


def run(command: Sequence[str]) -> int:
    """Run an update command with its output on our own streams."""
    import subprocess

    try:
        return subprocess.call(list(command))
    except OSError as e:
        print(f"could not run {command[0]}: {e}", file=sys.stderr)
        return 1


def run_detached(command: Sequence[str]) -> bool:
    """Hand the command to a new console window and leave.

    Windows will not let an installer replace the executable of a process that
    is still running - and `lens_scan update` *is* that process for a
    standalone build. The installer therefore gets a console of its own, which
    stays open so its output can be read, and we exit immediately.
    """
    import subprocess

    try:
        subprocess.Popen(
            list(command),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            close_fds=True,
            cwd=os.path.expanduser("~"),
        )
        return True
    except (OSError, ValueError) as e:
        print(f"could not start the installer: {e}", file=sys.stderr)
        return False
