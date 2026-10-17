# Installation

[Back to the README](../README.md)

## Contents

- [Which one to pick](#which-one-to-pick)
- [Homebrew](#homebrew)
- [uv](#uv)
- [Standalone build](#standalone-build)
- [Scoop](#scoop)
- [pip](#pip)
- [Docker](#docker)
- [Updating](#updating)
- [Verifying a download](#verifying-a-download)
- [Which copy is running](#which-copy-is-running)

## Which one to pick

| | Needs Python? | Install | Update with |
|---|---|---|---|
| [Homebrew](#homebrew) (macOS, Linux) | no | `brew install bropines/tap/lens-scan` | `lens_scan update` |
| [uv](#uv) | no, uv fetches one | `install-uv.ps1` / `install-uv.sh` | `lens_scan update` |
| [Standalone](#standalone-build) | no | `install.ps1` / `install.sh` | `lens_scan update` |
| [Scoop](#scoop) (Windows) | no | `scoop install lens-scan` | `lens_scan update` |
| [pip](#pip) | yes, your own (3.9+) | `pip install chrome-lens-py` | `lens_scan update` |
| [Docker](#docker) | no | `docker run ... ghcr.io/bropines/chrome-lens-py` | `docker pull`; `lens_scan update` says so |

`lens_scan update` works out which of these installed the copy you are running and runs that one's own upgrade; see [Updating](#updating).

Startup time and download size (Windows, `--help` only, median of six runs):

| | Startup | Download | Notes |
|---|---|---|---|
| `uv tool install` | 488 ms | 10-15 MB | No executable of ours, so nothing for antivirus heuristics to flag. |
| Standalone zip | **202 ms** | 25 MB | No Python needed. A folder, not a single file. Nuitka has compiled the imports away. |

With the [warm daemon](daemon.md) a call costs about 0.4 s whichever you pick.

## Homebrew

```bash
brew install bropines/tap/lens-scan
```

This is one command, not two: `brew` taps [bropines/homebrew-tap](https://github.com/bropines/homebrew-tap) on the way. It installs the prebuilt standalone folder, so your Python does not matter. The formula is bumped automatically on every release.

Builds exist for Apple Silicon and x86_64 Linux. On an Intel Mac or ARM Linux the formula stops and points you at uv.

## uv

One line. It installs uv if you do not have it, then installs `lens_scan` as a uv tool with the `[clipboard]` extra and puts it on PATH. uv brings its own Python.

```powershell
# Windows
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh | sh
```

With uv already installed you can skip the script:

```bash
uv tool install "chrome-lens-py[clipboard]"      # pipx install works too
lens_scan update                                  # runs: uv tool upgrade --reinstall chrome-lens-py
uv tool uninstall chrome-lens-py
```

## Standalone build

No Python needed. The installer downloads the latest release, verifies its SHA-256, unpacks it, puts `lens_scan` on your PATH and checks that it starts.

```powershell
# Windows
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | sh
```

| OS | Installed to |
|---|---|
| Windows | `%LOCALAPPDATA%\Programs\lens-scan`, added to the user PATH |
| Linux, macOS | `~/.local/share/lens-scan` (or `$XDG_DATA_HOME/lens-scan`), linked into `~/.local/bin` |

Re-running the installer replaces the existing install, and that is what `lens_scan update` does for this build. It unpacks into a staging folder first, so a download that fails verification leaves the old install untouched.

**Pin a version** with `LENS_SCAN_VERSION` (`3.6.0` or `v3.6.0`):

```powershell
$env:LENS_SCAN_VERSION = '3.6.0'; irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | LENS_SCAN_VERSION=3.6.0 sh
```

**Platforms.** Windows x64 (compiled, plus the portable build below), Linux x64 and arm64, macOS Apple Silicon and Intel. The Linux builds are made on Ubuntu 22.04 against glibc 2.35, so they run on Ubuntu 22.04, Debian 12 and newer. On anything else the installer says so and points you at uv.

### The portable build (Windows)

The default Windows build is a compiled `lens_scan.exe`. It starts fastest, but it is an unsigned executable, and some antivirus heuristics distrust those.

The **portable build** exists for that case. It contains no executable of ours: it is the official `python.exe` from python.org, signed by the Python Software Foundation, plus the package as plain files. It is started as `lens_scan.cmd` and starts more slowly.

The installer tries the compiled build first. It checks that the binary still runs a moment after unpacking, and if your antivirus quarantined it, it installs the portable build instead. To choose yourself:

```powershell
$env:LENS_SCAN_FLAVOR = 'portable'      # or 'nuitka' for the compiled one
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex
```

`uv tool install` avoids binaries entirely.

## Scoop

```powershell
scoop bucket add lens https://github.com/bropines/chrome-lens-py
scoop install lens-scan            # compiled build
scoop install lens-scan-portable   # the portable build above
```

## pip

```bash
pip install chrome-lens-py
pip install "chrome-lens-py[clipboard]"      # the --sharex flag
pip install git+https://github.com/bropines/chrome-lens-py.git   # latest from GitHub
```

Extras:

| Extra | Adds |
|---|---|
| `clipboard` | `pyperclip`, for `--sharex` |
| `rtl` | `python-bidi` and `arabic-reshaper`: shaping for Arabic, Hebrew and other right-to-left scripts in the [overlay](rendering.md#right-to-left-scripts-and-fonts) |
| `fonts` | `fontTools`: per-character font fallback in the overlay |
| `numpy` | NumPy, for passing arrays to the [API](api.md#image-sources) |

## Docker

The image runs the [HTTP server](daemon.md#http-api).

```bash
docker run -d -p 127.0.0.1:8765:8765 -e LENS_TOKEN=change-me ghcr.io/bropines/chrome-lens-py
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer change-me" -H "Content-Type: image/png" \
     --data-binary @shot.png "http://127.0.0.1:8765/v1/ocr/raw?translate_to=ru"
```

Tags: `latest`, the full version (`3.7.0`) and `major.minor` (`3.7`). The image is built for `linux/amd64` and `linux/arm64`.

- **`LENS_TOKEN` is required.** Inside the container the server listens beyond loopback, and `lens_scan` refuses to do that without a token. The container exits at start if it is missing.
- Publish the port on `127.0.0.1` unless you mean to expose it.
- Extra `docker run` arguments are appended to `lens_scan`, for example `--allow-origin https://yoursite.example`.
- The container runs as a non-root user and has a health check on `/health`.

## Updating

```bash
lens_scan update             # update this copy the way it was installed
lens_scan update --check     # only say whether a newer release exists
lens_scan update --dry-run   # print the command it would run, and stop
```

Every install method has its own idea of what an update is, and running the wrong one leaves two copies with the wrong one first on PATH: `pip install -U` over a Homebrew install, or an installer script over a uv tool. So `lens_scan update` first works out which install it belongs to and then runs that one's own command. The command is always printed before it runs.

| Installed with | `lens_scan update` runs |
|---|---|
| uv tool | `uv tool upgrade --reinstall chrome-lens-py`. `--reinstall` keeps the environment and replaces the packages inside it: the interpreter running `update` lives in that environment, and Windows will not let it be removed from inside. A tool installed pinned to a version is reinstalled without the pin instead, because `uv tool upgrade` honours a pin and would move nothing; on Windows that one runs in a console window of its own. |
| pipx | `pipx upgrade chrome-lens-py` |
| Homebrew | `brew upgrade bropines/tap/lens-scan` |
| Scoop | `scoop update <app>`, where `<app>` is `lens-scan` or `lens-scan-portable`, whichever you have |
| Standalone build from `install.ps1` / `install.sh` | the install script again. On Windows it opens in a new console window, because Windows will not let a program replace its own running `.exe`; the window stays open so you can read it. |
| pip | `pip install --upgrade chrome-lens-py`, with the `[clipboard]` extra only if `pyperclip` is already installed |

Three kinds of copy are not updated for you, because there is nothing safe to run. `lens_scan update` prints what to do instead: `git pull` for a git checkout, `docker pull ghcr.io/bropines/chrome-lens-py` and recreating the container for a Docker image, and downloading the archive from the [releases page](https://github.com/bropines/chrome-lens-py/releases/latest) and unzipping it over the folder for a standalone build you unpacked by hand.

`--check` compares the version you have with the newest release on PyPI and changes nothing. PyPI answers for every channel, since uv, pip, Homebrew, Scoop and the install scripts are all published from the same release. `--json` does the same and prints the result for a script (it never updates). Run without either, `lens_scan update` on a copy that is already current reinstalls it, and says so first.

A running [daemon](daemon.md) holds the files being replaced, so it is stopped before the update. If the [login service](daemon.md#running-it-as-a-login-service) owns it, the service is restarted afterwards; if it was just the on-demand daemon, it is started again. If the update command fails, the daemon is started again as it was.

## Verifying a download

Every release publishes a `.sha256` next to each archive, and the installers check it before unpacking. To check one by hand:

```bash
sha256sum -c lens_scan-linux-amd64.zip.sha256
```

This catches a corrupted or truncated download, and a CDN serving something other than what was uploaded. It is not a signature: anyone able to rewrite the release could rewrite the checksum with it.

For that, every archive also carries a signed build-provenance attestation. It proves the archive was built by this repository's release workflow from a given commit:

```bash
gh attestation verify lens_scan-linux-amd64.zip --repo bropines/chrome-lens-py
```

## Which copy is running

A pip install, a `uv tool` install, an editable checkout and a standalone build can all own the name `lens_scan`, and the one earlier on your PATH wins. The uv installers warn when they notice this. To be sure:

```bash
lens_scan status
lens_scan version
```

`status` is the first thing to run when something does not work. It fits on one screen: the version and how this copy was installed (uv tool, Homebrew, standalone build and so on), whether the [daemon](daemon.md) is running, whether the login service is installed, whether the ShareX hotkeys are set up, whether the clipboard extra is there, and which config file is in effect. `lens_scan status --json` gives the same for a script. It exits `1` when something is actually wrong, for example a login service with no daemon behind it; a machine with no daemon running is fine, because one starts on the next scan.

`version` prints the version, the kind of copy (installed package, source checkout or standalone build), the interpreter and package paths, and whether the clipboard extra is available. `lens_scan --version` prints the same.
