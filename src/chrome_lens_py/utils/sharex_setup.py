import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def is_sharex_running() -> bool:
    """Checks if ShareX.exe is currently running."""
    try:
        output = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq ShareX.exe" /NH', shell=True
        ).decode("utf-8", errors="ignore")
        return "ShareX.exe" in output
    except Exception:
        return False


def terminate_sharex():
    """Closes ShareX to prevent it from overwriting the config on exit."""
    if is_sharex_running():
        console.print("[yellow]ShareX is running. Closing it to apply changes...[/yellow]")
        try:
            subprocess.run(["taskkill", "/F", "/IM", "ShareX.exe"], capture_output=True)
            # Give it a moment to release file handles
            time.sleep(1)
        except Exception as e:
            console.print(f"[bold red]Error closing ShareX:[/bold red] {e}")


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
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ShareX" / "ShareX.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "ShareX" / "ShareX.exe",
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


def setup_sharex_config():
    """
    Automatically configures ShareX to use chrome-lens-py for OCR/Translation.
    Injects a custom hotkey into HotkeysConfig.json.
    """
    if sys.platform != "win32":
        console.print(
            "[bold red]Error:[/bold red] ShareX setup is only supported on Windows."
        )
        return

    # 1. Locate HotkeysConfig.json
    documents_dir = get_documents_path()
    sharex_dir = documents_dir / "ShareX"
    config_path = sharex_dir / "HotkeysConfig.json"

    if not config_path.exists():
        console.print(
            f"[bold red]Error:[/bold red] ShareX configuration file not found at: [cyan]{config_path}[/cyan]"
        )
        console.print("Make sure ShareX is installed and has been run at least once.")
        return

    # 2. Determine the path to the lens_scan executable/script
    # If we are running as a Nuitka/PyInstaller binary, sys.executable is the .exe
    # If running via pip, we might be a .exe shim in the Scripts folder.
    executable_path = sys.executable
    is_python = executable_path.lower().endswith(("python.exe", "pythonw.exe"))

    if is_python:
        # If running via python, try to find 'lens_scan.bat' or 'lens_scan.exe' in the same directory (Scripts)
        scripts_dir = Path(executable_path).parent
        potential_shims = ["lens_scan.bat", "lens_scan.exe", "lens_scan"]
        found_path = None
        for shim in potential_shims:
            p = scripts_dir / shim
            if p.exists():
                found_path = str(p)
                break

        if found_path:
            executable_path = found_path
        else:
            # Fallback: assume 'lens_scan' is in PATH
            executable_path = "lens_scan"

    console.print(f"Detected executable path: [cyan]{executable_path}[/cyan]")

    # 3. Load and modify the config
    try:
        # ShareX uses UTF-8 with BOM sometimes
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
    except Exception as e:
        console.print(f"[bold red]Error reading ShareX config:[/bold red] {e}")
        return

    hotkeys = config.get("Hotkeys", [])

    # Check if 'lens' action already exists to avoid exact duplicates
    exists = False
    for hk in hotkeys:
        task = hk.get("TaskSettings", {})
        programs = task.get("ExternalPrograms") or []
        for prog in programs:
            if prog.get("Name") == "lens":
                # Update existing one
                prog["Path"] = executable_path
                prog["Args"] = '--sharex "$input"'
                prog["IsActive"] = True
                exists = True
                console.print(
                    "Found existing 'lens' task in ShareX. [yellow]Updating path...[/yellow]"
                )
                break
        if exists:
            break

    if not exists:
        # Create a new hotkey entry
        new_entry = {
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
                        "Args": '--sharex "$input"',
                        "OutputExtension": "",
                        "Extensions": "",
                        "HiddenWindow": True,
                        "DeleteInputFile": False,
                    }
                ],
            },
        }
        hotkeys.append(new_entry)
        console.print(
            "Adding new [bold green]Ctrl + O[/bold green] hotkey for Google Lens OCR."
        )

    config["Hotkeys"] = hotkeys

    # 4. Terminate ShareX before saving to prevent overwrite
    terminate_sharex()

    # 5. Save the config
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        console.print("\n[bold green]Success![/bold green] ShareX configuration updated.")

        # 6. Restart ShareX
        sharex_exe = get_sharex_executable_path()
        if not sharex_exe:
            console.print(
                "[yellow]ShareX executable not found in standard locations.[/yellow]"
            )
            user_path = console.input(
                "Please enter the full path to [bold]ShareX.exe[/bold] (or press Enter to skip restart): "
            ).strip()
            if user_path:
                p = Path(user_path.strip('"'))
                if p.exists() and p.is_file():
                    sharex_exe = p
                else:
                    console.print(f"[red]Invalid path: {user_path}[/red]")

        if sharex_exe:
            console.print(f"[yellow]Restarting ShareX from: {sharex_exe}[/yellow]")
            subprocess.Popen([str(sharex_exe)], shell=True, start_new_session=True)
        else:
            console.print(
                "[yellow]Skipping ShareX restart. Please start it manually.[/yellow]"
            )

        console.print(
            "\nDefault hotkey: [bold cyan]Ctrl + O[/bold cyan] (Region capture -> Lens OCR)"
        )
    except Exception as e:
        console.print(f"[bold red]Error saving ShareX config:[/bold red] {e}")
