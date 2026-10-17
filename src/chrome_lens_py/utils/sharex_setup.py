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
from typing import Any, Dict, List, Optional

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
            "HotkeyInfo": {"Hotkey": PROGRAM_HOTKEY, "Win": False},
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


# ------------------------------------------------------------ uploader mode

UPLOADER_VERSION = "15.0.0"


def build_uploader_config(
    port: int, token: str, target_lang: Optional[str] = None
) -> Dict[str, Any]:
    """A ShareX custom uploader (.sxcu) that posts the capture to the daemon.

    ImageUploader with a binary body: ShareX sends the picture's bytes with its
    own Content-Type (image/png...), which is what POST /v1/ocr/raw requires.
    The daemon answers with the recognised text as text/plain, and ``{response}``
    makes ShareX treat that whole body as the "URL" of the upload - so the
    ordinary after-upload task "Copy URL to clipboard" puts the text on the
    clipboard. ``ErrorMessage`` surfaces the daemon's JSON error to the user.
    """
    if target_lang is not None and not _LANG_RE.match(target_lang):
        raise ValueError(f"Invalid language code: {target_lang!r}")
    config: Dict[str, Any] = {
        "Version": UPLOADER_VERSION,
        "Name": UPLOADER_NAME,
        "DestinationType": "ImageUploader",
        "RequestMethod": "POST",
        "RequestURL": f"http://127.0.0.1:{port}/v1/ocr/raw",
    }
    if target_lang:
        config["Parameters"] = {"translate_to": target_lang}
    config["Headers"] = {"Authorization": f"Bearer {token}"}
    config["Body"] = "Binary"
    config["URL"] = "{response}"
    config["ErrorMessage"] = "{json:error}"
    return config


PROGRAM_HOTKEY = "O, Control"
UPLOADER_HOTKEY = "O, Shift, Control"
UPLOADER_NAME = "Google Lens OCR (chrome-lens-py)"
UPLOADER_HOTKEY_DESCRIPTION = "Google Lens OCR via the daemon (chrome-lens-py)"
MODES = ("program", "uploader", "both")


def register_uploader(uploaders: Dict[str, Any], item: Dict[str, Any]) -> int:
    """Put our custom uploader into an UploadersConfig dict; return its index.

    Matched by name, so re-running setup refreshes the port and token in place
    instead of piling up copies. ShareX's selected custom image uploader is
    left alone: our hotkey points at this entry by index, so nothing else the
    user uploads is redirected to the OCR daemon.
    """
    items = uploaders.get("CustomUploadersList")
    if not isinstance(items, list):
        items = []
    for index, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("Name") == item["Name"]:
            items[index] = item
            uploaders["CustomUploadersList"] = items
            return index
    items.append(item)
    uploaders["CustomUploadersList"] = items
    return len(items) - 1


def uploader_hotkey(index: int) -> Dict[str, Any]:
    """A hotkey that captures a region and sends it to our uploader only."""
    return {
        "HotkeyInfo": {"Hotkey": UPLOADER_HOTKEY, "Win": False},
        "TaskSettings": {
            "Description": UPLOADER_HOTKEY_DESCRIPTION,
            "Job": "RectangleLight",
            "UseDefaultAfterCaptureJob": False,
            "AfterCaptureJob": "UploadImageToHost",
            "UseDefaultAfterUploadJob": False,
            # The daemon's reply (the text) is what ShareX calls the URL.
            "AfterUploadJob": "CopyURLToClipboard",
            "UseDefaultDestinations": False,
            "ImageDestination": "CustomImageUploader",
            # Per-hotkey choice of custom uploader: the global "image
            # destination" stays whatever the user had.
            "OverrideCustomUploader": True,
            "CustomUploaderIndex": index,
        },
    }


def apply_uploader_hotkey(config: Dict[str, Any], index: int) -> bool:
    """Add or refresh our uploader hotkey. True if one was updated."""
    hotkeys = config.get("Hotkeys")
    if not isinstance(hotkeys, list):
        hotkeys = []
    fresh = uploader_hotkey(index)
    for i, hk in enumerate(hotkeys):
        task = hk.get("TaskSettings", {}) if isinstance(hk, dict) else {}
        if task.get("Description") == UPLOADER_HOTKEY_DESCRIPTION:
            hotkeys[i] = fresh
            config["Hotkeys"] = hotkeys
            return True
    hotkeys.append(fresh)
    config["Hotkeys"] = hotkeys
    return False


def hotkey_conflicts(config: Dict[str, Any], hotkey: str, own: str) -> List[str]:
    """Descriptions of other hotkeys already bound to `hotkey`."""
    taken = []
    for hk in config.get("Hotkeys") or []:
        if not isinstance(hk, dict):
            continue
        info = hk.get("HotkeyInfo") or {}
        task = hk.get("TaskSettings") or {}
        if info.get("Hotkey") != hotkey or task.get("Description") == own:
            continue
        if any(
            isinstance(p, dict) and p.get("Name") == "lens"
            for p in task.get("ExternalPrograms") or []
        ):
            continue  # our own program-mode hotkey
        taken.append(task.get("Description") or task.get("Job") or "unnamed")
    return taken


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} does not contain a JSON object.")
    return data


def setup_sharex(
    mode: str = "program",
    target_lang: Optional[str] = None,
    port: Optional[int] = None,
) -> bool:
    """Configure ShareX. Returns True on success.

    program   Ctrl+O runs lens_scan on the capture. Needs nothing running, and
              uses the warm daemon whenever there is one.
    uploader  Ctrl+Shift+O posts the capture straight to the always-on daemon:
              no process per capture, the fastest path. Installs that daemon as
              a login service (on Windows under a supervisor that restarts it).
    both      Both hotkeys - the fast one, and the one that always works.

    Every file is backed up before it is touched and written atomically, with
    ShareX closed so it cannot overwrite the edit on its way out.
    """
    if sys.platform != "win32":
        console.print(
            "[bold red]Error:[/bold red] ShareX setup is only supported on Windows."
        )
        return False
    if mode not in MODES:
        console.print(f"[bold red]Error:[/bold red] unknown mode {escape(mode)!r}.")
        return False
    want_program = mode in ("program", "both")
    want_uploader = mode in ("uploader", "both")

    try:
        action_args = build_action_args(target_lang)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
        return False

    sharex_dir = get_documents_path() / "ShareX"
    hotkeys_path = sharex_dir / "HotkeysConfig.json"
    uploaders_path = sharex_dir / "UploadersConfig.json"
    needed = [hotkeys_path] + ([uploaders_path] if want_uploader else [])
    missing = [p for p in needed if not p.exists()]
    if missing:
        console.print(
            "[bold red]Error:[/bold red] ShareX configuration not found at: "
            f"[cyan]{escape(str(missing[0]))}[/cyan]\n"
            "Make sure ShareX is installed and has been run at least once."
        )
        return False

    executable_path = None
    if want_program:
        executable_path = _find_lens_scan()
        if not executable_path:
            console.print(
                "[bold red]Error:[/bold red] Could not locate the "
                "[cyan]lens_scan[/cyan] executable.\nMake sure the package is "
                "installed and that its Scripts directory is on PATH."
            )
            return False
        console.print(f"lens_scan: [cyan]{escape(executable_path)}[/cyan]")

    uploader_item = None
    if want_uploader:
        from ..daemon import ensure_service_config
        from .service import install_service

        try:
            service = ensure_service_config(port)
            uploader_item = build_uploader_config(
                service["port"], service["token"], target_lang
            )
        except (ValueError, OSError) as e:
            console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
            return False
        # The uploader is only as good as the daemon behind it: make it a
        # login service, supervised so a crash is restarted.
        if not install_service(port):
            console.print(
                "[bold red]Error:[/bold red] could not install the daemon service."
            )
            return False

    if target_lang:
        console.print(
            f"Hotkeys will translate into: [cyan]{escape(target_lang)}[/cyan]"
        )

    was_running = terminate_sharex()
    saved = False
    try:
        hotkeys = _load_json(hotkeys_path)
        uploaders = _load_json(uploaders_path) if want_uploader else None

        if want_program:
            updated = apply_lens_hotkey(hotkeys, executable_path, action_args)
            console.print(
                ("Updated" if updated else "Added")
                + " [bold green]Ctrl + O[/bold green]: run lens_scan on the capture."
            )
        if want_uploader:
            assert uploaders is not None and uploader_item is not None
            index = register_uploader(uploaders, uploader_item)
            clash = hotkey_conflicts(
                hotkeys, UPLOADER_HOTKEY, UPLOADER_HOTKEY_DESCRIPTION
            )
            updated = apply_uploader_hotkey(hotkeys, index)
            console.print(
                ("Updated" if updated else "Added")
                + " [bold green]Ctrl + Shift + O[/bold green]: send the capture "
                "to the daemon."
            )
            if clash:
                console.print(
                    "[yellow]Ctrl + Shift + O is also bound to: "
                    f"{escape(', '.join(clash))}. Change one of them in ShareX."
                    "[/yellow]"
                )

        for path in needed:
            backup = backup_hotkeys_config(path)
            console.print(f"Backup: [cyan]{escape(str(backup))}[/cyan]")
        atomic_write_text(str(hotkeys_path), json.dumps(hotkeys, indent=2))
        if want_uploader:
            atomic_write_text(str(uploaders_path), json.dumps(uploaders, indent=2))
        saved = True
        console.print("\n[bold green]Success![/bold green] ShareX configured.")
        if mode == "both":
            console.print(
                "Ctrl + Shift + O is the fast one; Ctrl + O keeps working even if "
                "the daemon is down."
            )
    except Exception as e:
        console.print(
            f"[bold red]Error updating ShareX config:[/bold red] {escape(str(e))}"
        )

    if saved or was_running:
        _restart_sharex(interactive=saved)
    return saved


def setup_sharex_config(target_lang: Optional[str] = None) -> bool:
    """Program mode only; kept for callers of the previous API."""
    return setup_sharex("program", target_lang)


def setup_sharex_uploader(
    target_lang: Optional[str] = None, port: Optional[int] = None
) -> bool:
    """Uploader mode only; kept for callers of the previous API."""
    return setup_sharex("uploader", target_lang, port)
