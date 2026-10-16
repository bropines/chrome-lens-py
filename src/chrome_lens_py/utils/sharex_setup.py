import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console
from rich.markup import escape

from .config_manager import atomic_write_text

console = Console()
logger = logging.getLogger(__name__)


def is_sharex_running() -> bool:
    """Checks if ShareX.exe is currently running."""
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq ShareX.exe", "/NH"]
        ).decode("utf-8", errors="ignore")
        return "ShareX.exe" in output
    except Exception:
        return False


def terminate_sharex() -> bool:
    """Close ShareX so it cannot overwrite the config on its way out.

    Asks politely first: a normal close lets ShareX write its own state to
    disk, and only then do we edit the file. A forced kill is the fallback
    when it has not gone after a few seconds. Returns True if it was running.
    """
    if not is_sharex_running():
        return False

    console.print("[yellow]ShareX is running. Closing it to apply changes...[/yellow]")
    try:
        subprocess.run(["taskkill", "/IM", "ShareX.exe"], capture_output=True)
        for _ in range(10):
            time.sleep(0.5)
            if not is_sharex_running():
                break
        else:
            subprocess.run(["taskkill", "/F", "/IM", "ShareX.exe"], capture_output=True)
        # Give it a moment to release file handles
        time.sleep(1)
    except Exception as e:
        console.print(f"[bold red]Error closing ShareX:[/bold red] {escape(str(e))}")
    return True


def get_sharex_executable_path() -> Optional[Path]:
    """Attempts to find the ShareX.exe location via registry."""
    try:
        import winreg

        key_path = r"Software\ShareX"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            val, _ = winreg.QueryValueEx(key, "InstallLocation")
            path = Path(val) / "ShareX.exe"
            if path.exists():
                return path
    except Exception:
        pass

    # Common installation paths
    common_paths = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "ShareX"
        / "ShareX.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "ShareX"
        / "ShareX.exe",
        Path(os.environ.get("LocalAppData", "")) / "ShareX" / "ShareX.exe",
    ]
    for p in common_paths:
        if p.exists():
            return p
    return None


def get_documents_path() -> Path:
    """Finds the actual Documents folder path on Windows, handling relocations."""
    if sys.platform != "win32":
        return Path(os.path.expanduser("~/Documents"))

    try:
        import winreg

        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            # 'Personal' is the standard name for the Documents folder in the registry
            val, _ = winreg.QueryValueEx(key, "Personal")
            # The registry might contain environment variables like %USERPROFILE%
            expanded_val = os.path.expandvars(val)
            return Path(expanded_val)
    except Exception as e:
        logger.debug(f"Failed to find Documents folder via registry: {e}")
        # Fallback to standard expanduser
        return Path(os.path.expanduser("~/Documents"))


_LANG_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def build_action_args(target_lang: Optional[str] = None) -> str:
    """Arguments ShareX passes to lens_scan; `-t <lang>` makes the hotkey translate."""
    if target_lang:
        if not _LANG_RE.match(target_lang):
            raise ValueError(f"Invalid language code: {target_lang!r}")
        return f'-t {target_lang} --sharex "$input"'
    return '--sharex "$input"'


def backup_hotkeys_config(config_path: Path) -> Path:
    """Copy the file to HotkeysConfig.json.bak-<timestamp> next to it."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = config_path.with_name(f"{config_path.name}.bak-{stamp}")
    shutil.copy2(config_path, backup_path)
    return backup_path


def apply_lens_hotkey(
    config: Dict[str, Any], executable_path: str, action_args: str
) -> bool:
    """Add or update the 'lens' action in a HotkeysConfig dict.

    Returns True if an existing action was updated, False if one was added.
    """
    hotkeys = config.get("Hotkeys")
    if not isinstance(hotkeys, list):
        hotkeys = []

    for hk in hotkeys:
        task = hk.get("TaskSettings", {}) if isinstance(hk, dict) else {}
        for prog in task.get("ExternalPrograms") or []:
            if isinstance(prog, dict) and prog.get("Name") == "lens":
                prog["Path"] = executable_path
                prog["Args"] = action_args
                prog["IsActive"] = True
                config["Hotkeys"] = hotkeys
                return True

    hotkeys.append(
        {
            "HotkeyInfo": {"Hotkey": "O, Control", "Win": False},
            "TaskSettings": {
                "Description": "Google Lens OCR (chrome-lens-py)",
                "Job": "RectangleLight",
                "UseDefaultAfterCaptureJob": False,
                "AfterCaptureJob": "SaveImageToFile, PerformActions",
                "UseDefaultActions": False,
                "ExternalPrograms": [
                    {
                        "IsActive": True,
                        "Name": "lens",
                        "Path": executable_path,
                        "Args": action_args,
                        "OutputExtension": "",
                        "Extensions": "",
                        "HiddenWindow": True,
                        "DeleteInputFile": False,
                    }
                ],
            },
        }
    )
    config["Hotkeys"] = hotkeys
    return False


def _find_lens_scan() -> Optional[str]:
    # ShareX requires a full absolute path - it cannot resolve bare command names.
    # Priority:
    #   a) shutil.which("lens_scan") - resolves via PATH (covers pip-installed
    #      shims, pyenv, venv, etc.)
    #   b) If sys.executable is NOT python itself (i.e. a compiled binary), use
    #      it directly.
    found_via_which = shutil.which("lens_scan")
    if found_via_which:
        return str(Path(found_via_which).resolve())
    se = sys.executable
    if not se.lower().endswith(("python.exe", "pythonw.exe", "python", "pythonw")):
        return se
    return None


def _restart_sharex(interactive: bool) -> None:
    sharex_exe = get_sharex_executable_path()
    if not sharex_exe and interactive:
        console.print(
            "[yellow]ShareX executable not found in standard locations.[/yellow]"
        )
        user_path = console.input(
            "Please enter the full path to [bold]ShareX.exe[/bold] "
            "(or press Enter to skip restart): "
        ).strip()
        if user_path:
            p = Path(user_path.strip('"'))
            if p.exists() and p.is_file():
                sharex_exe = p
            else:
                console.print(f"[red]Invalid path: {escape(user_path)}[/red]")

    if sharex_exe:
        console.print(
            f"[yellow]Restarting ShareX from: {escape(str(sharex_exe))}[/yellow]"
        )
        subprocess.Popen([str(sharex_exe)], start_new_session=True)
    else:
        console.print(
            "[yellow]Skipping ShareX restart. Please start it manually.[/yellow]"
        )


def setup_sharex_config(target_lang: Optional[str] = None) -> bool:
    """
    Automatically configures ShareX to use chrome-lens-py for OCR/Translation.
    Injects a custom hotkey into HotkeysConfig.json, translating into
    `target_lang` when one is given. Returns True on success.

    The existing file is copied to HotkeysConfig.json.bak-<timestamp> before it
    is touched, and the new content is written atomically.
    """
    if sys.platform != "win32":
        console.print(
            "[bold red]Error:[/bold red] ShareX setup is only supported on Windows."
        )
        return False

    try:
        action_args = build_action_args(target_lang)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
        return False

    # 1. Locate HotkeysConfig.json
    config_path = get_documents_path() / "ShareX" / "HotkeysConfig.json"
    if not config_path.exists():
        console.print(
            "[bold red]Error:[/bold red] ShareX configuration file not found at: "
            f"[cyan]{escape(str(config_path))}[/cyan]"
        )
        console.print("Make sure ShareX is installed and has been run at least once.")
        return False

    # 2. Determine the path to the lens_scan executable/script.
    executable_path = _find_lens_scan()
    if not executable_path:
        console.print(
            "[bold red]Error:[/bold red] Could not locate the [cyan]lens_scan[/cyan] "
            "executable.\nMake sure the package is installed "
            "(e.g. [bold]pip install chrome-lens-py[/bold]) "
            "and that the Scripts directory is in your PATH."
        )
        return False
    console.print(f"Detected executable path: [cyan]{escape(executable_path)}[/cyan]")
    if target_lang:
        console.print(
            f"The hotkey will translate into: [cyan]{escape(target_lang)}[/cyan]"
        )

    # 3. Close ShareX first, so that what we read is what it saved on exit
    #    and nothing overwrites our edit afterwards.
    was_running = terminate_sharex()

    saved = False
    try:
        # ShareX uses UTF-8 with BOM sometimes
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError("HotkeysConfig.json does not contain a JSON object.")

        if apply_lens_hotkey(config, executable_path, action_args):
            console.print(
                "Found existing 'lens' task in ShareX. [yellow]Updating it...[/yellow]"
            )
        else:
            console.print(
                "Adding new [bold green]Ctrl + O[/bold green] hotkey for Google Lens OCR."
            )

        backup_path = backup_hotkeys_config(config_path)
        console.print(
            f"Backup of the previous config: [cyan]{escape(str(backup_path))}[/cyan]"
        )
        atomic_write_text(str(config_path), json.dumps(config, indent=2))
        saved = True
        console.print(
            "\n[bold green]Success![/bold green] ShareX configuration updated."
        )
        console.print(
            "\nDefault hotkey: [bold cyan]Ctrl + O[/bold cyan] "
            "(Region capture -> Lens OCR)"
        )
    except Exception as e:
        console.print(
            f"[bold red]Error updating ShareX config:[/bold red] {escape(str(e))}"
        )

    # 4. Bring ShareX back (also after a failure, if we were the ones to close it).
    if saved or was_running:
        _restart_sharex(interactive=saved)
    return saved
