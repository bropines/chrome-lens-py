"""Build the "portable" Windows distribution: no executable of ours in it.

    python scripts/build_portable.py --out dist

The Nuitka build is a compiled .exe nobody has ever signed, and antivirus
heuristics dislike exactly that. This variant ships the official Windows
embeddable Python - python.exe, pythonw.exe and the DLLs are Authenticode-signed
by the Python Software Foundation - plus our package and its dependencies as
plain files under Lib\\site-packages. Nothing in it needs a verdict from a
reputation engine that has not seen it before.

Layout of the result (and of the zip):

    lens_scan-windows-amd64-portable/
        python.exe, pythonw.exe, python3XX.dll, ...   (signed, from python.org)
        python3XX._pth                                 (isolated sys.path)
        Lib/site-packages/                             (chrome_lens_py + deps, precompiled)
        lens_scan.cmd                                  (the entry point; put the folder on PATH)

Run on a Windows host: it executes the embedded interpreter to precompile and
to smoke-test. Needs `uv` on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The last 3.12 with a binary embeddable build is 3.12.10 (April 2025) and its
# bundled OpenSSL is old; 3.13 still gets binary releases. The digest pins the
# download: a different file under the same URL is a build failure, not a
# silent change of interpreter.
PYTHON_VERSION = "3.13.15"
PYTHON_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"

# Only these executables may exist in the result, and both must be signed.
ALLOWED_EXE = {"python.exe", "pythonw.exe"}

# `-c`, not `-m chrome_lens_py`: it works whether or not the package has a
# __main__ module. -I ignores PYTHON* variables and the user site, so a stray
# environment cannot change which code runs.
SHIM = '@"%~dp0python.exe" -I -c "from chrome_lens_py.cli.main import run; run()" %*\r\n'


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def download(url: str, dest: Path, sha256: str) -> None:
    log(f"Downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "chrome-lens-py-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"SHA-256 mismatch for {url}\n  expected {sha256}\n  got      {digest}")
    dest.write_bytes(data)


def authenticode(paths: list[Path]) -> dict[Path, str]:
    """Status per file, e.g. 'Valid' or 'NotSigned'. Windows only."""
    listing = "@(" + ",".join("'" + str(p).replace("'", "''") + "'" for p in paths) + ")"
    script = (
        f"{listing} | ForEach-Object {{ $s = Get-AuthenticodeSignature -LiteralPath $_; "
        "'{0}|{1}|{2}' -f $_, $s.Status, $s.SignerCertificate.Subject }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
    )
    statuses = {}
    for line in result.stdout.splitlines():
        if "|" in line:
            path, status, subject = line.split("|", 2)
            statuses[Path(path)] = f"{status} ({subject})"
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="dist", help="directory to build in (default: dist)")
    parser.add_argument("--name", default="lens_scan-windows-amd64-portable")
    parser.add_argument("--extra", default="clipboard", help="extra to install (default: clipboard)")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("build_portable.py runs the embedded python.exe; run it on Windows.")
    if not shutil.which("uv"):
        raise SystemExit("uv is required on PATH (pip install uv).")

    out = (Path(args.out) if Path(args.out).is_absolute() else Path.cwd() / args.out).resolve()
    root = out / args.name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    major, minor, _ = PYTHON_VERSION.split(".")
    tag = f"{major}{minor}"  # 313

    archive = out / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(EMBED_URL.format(v=PYTHON_VERSION), archive, PYTHON_SHA256)
    with zipfile.ZipFile(archive) as z:
        z.extractall(root)
    archive.unlink()

    # Replace the stock ._pth. "import site" is what makes .pth files and the
    # site-packages directory work; the blank line is intentional and harmless.
    pth = root / f"python{tag}._pth"
    if not pth.is_file():
        raise SystemExit(f"{pth.name} not found in the embeddable package")
    pth.write_text(f"python{tag}.zip\n.\nLib\\site-packages\n\nimport site\n", encoding="ascii")

    site_packages = root / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)

    log("Installing chrome-lens-py and its dependencies")
    subprocess.run(
        [
            "uv", "pip", "install",
            "--python-platform", "x86_64-pc-windows-msvc",
            "--python-version", f"{major}.{minor}",
            "--target", str(site_packages),
            f"{REPO_ROOT}[{args.extra}]" if args.extra else str(REPO_ROOT),
        ],
        check=True,
    )

    # pip/uv console-script launchers: unsigned executables, which is exactly
    # what this build exists to avoid. The shim below replaces them.
    for stray in list(site_packages.rglob("*.exe")):
        log(f"Removing launcher {stray.relative_to(root)}")
        stray.unlink()
    bin_dir = site_packages / "bin"
    if bin_dir.is_dir():
        shutil.rmtree(bin_dir)

    log("Precompiling")
    subprocess.run(
        [str(root / "python.exe"), "-I", "-m", "compileall", "-q", "-j", "0", str(site_packages)],
        check=True,
    )

    (root / "lens_scan.cmd").write_bytes(SHIM.encode("ascii"))

    log("Checking what is in the folder")
    executables = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".exe")
    unexpected = [p for p in executables if p.name.lower() not in ALLOWED_EXE or p.parent != root]
    if unexpected:
        raise SystemExit("Unexpected executables: " + ", ".join(str(p.relative_to(root)) for p in unexpected))

    # Everything we did not build ourselves must carry the PSF signature:
    # the interpreter and the DLLs beside it. The .pyd/.dll files that came
    # from wheels are the package authors' and are not signed; they are only
    # listed so a reviewer can see them.
    signed_set = sorted(p for p in root.iterdir() if p.suffix.lower() in {".exe", ".dll", ".pyd"})
    bad = []
    for path, status in authenticode(signed_set).items():
        print(f"  {path.name}: {status}")
        if not status.startswith("Valid"):
            bad.append(f"{path.name}: {status}")
    if bad:
        raise SystemExit("Unsigned or invalid files in the portable root:\n  " + "\n  ".join(bad))
    wheel_binaries = sorted(p for p in site_packages.rglob("*") if p.suffix.lower() in {".pyd", ".dll"})
    log(f"{len(wheel_binaries)} binary module(s) came from wheels (not Authenticode-signed by design)")

    log("Smoke test")
    result = subprocess.run(
        ["cmd", "/c", str(root / "lens_scan.cmd"), "--version"], capture_output=True, text=True
    )
    print(result.stdout + result.stderr)
    if result.returncode != 0:
        raise SystemExit(f"lens_scan.cmd --version exited {result.returncode}")
    import re

    if not re.search(r"Clipboard.*available", result.stdout + result.stderr):
        raise SystemExit("pyperclip is missing from the build; --sharex would do nothing.")
    help_run = subprocess.run(["cmd", "/c", str(root / "lens_scan.cmd"), "--help"], capture_output=True)
    if help_run.returncode != 0:
        raise SystemExit("lens_scan.cmd --help failed")

    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) / 1e6
    log(f"Built {root} ({size:.0f} MB unpacked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
