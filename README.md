# Chrome Lens API for Python

**English** | [Русский](/README_RU.md)

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

Google Lens from the command line and from Python: recognise text in an image (OCR), translate it, draw the translation back onto the image, get the word coordinates. It talks to the same Protobuf endpoint as Chrome's Lens overlay.

## 📦 Install

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex
```

**macOS / Linux**

```bash
brew install bropines/tap/lens-scan
```

**You already have Python 3.9+**

```bash
pip install "chrome-lens-py[clipboard]"
```

None of these needs a Python you have to install yourself, except the last. Then:

```bash
lens_scan status     # is it working? which copy is this? what is running?
lens_scan update     # update it later, the way it was installed
```

Other ways in - uv without the script, Scoop, a standalone build with no Python at all, Docker, pinning a version, checksums and build provenance: **[docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md)**.

## 🚀 Use it

```bash
lens_scan shot.png                               # OCR, language auto-detected
lens_scan shot.png -t en                         # OCR + translate into English
lens_scan shot.png ja -t ru -sx                  # Japanese in, Russian on the clipboard
lens_scan shot.png -t en -to out.png             # translation drawn onto the image
lens_scan page.png ja -t en -to out.png --manga  # manga page: vertical text, bubbles
lens_scan scans/ --format jsonl > out.jsonl      # a folder, one JSON object per image
lens_scan sharex --mode both -t ru               # ShareX: Ctrl+O and Ctrl+Shift+O (Windows)
```

`lens_scan -h` lists the options people actually use; `lens_scan help options` is the full reference.

The result goes to stdout and everything else to stderr, so `lens_scan img.png > out.txt` holds only the text. Exit codes: `0` everything worked, `1` it failed, `2` some images of several failed, `64` the command line was wrong.

### Commands

| Command | |
|---|---|
| `lens_scan status` | version, install method, daemon, login service, ShareX, clipboard - one screen |
| `lens_scan update` | update this copy the way it was installed (uv, brew, Scoop, pip, installer) |
| `lens_scan daemon status\|start\|stop\|restart\|logs` | the warm background process that makes a scan take ~0.4 s instead of ~3 s |
| `lens_scan service install\|uninstall\|status\|logs` | keep that daemon running from login (what ShareX's fast hotkey needs) |
| `lens_scan sharex [--mode both] [-t LANG]` | set up the ShareX hotkeys (Windows) |
| `lens_scan config show` | every setting, its value, and which layer set it |
| `lens_scan serve` | run the HTTP API in this terminal |

Add `--json` to anything that reports, and `lens_scan help <command>` explains one.

## 🐍 From Python

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    async with LensAPI() as api:
        result = await api.process_image(
            "image.png", ocr_language="ja", target_translation_language="en"
        )
        print(result["ocr_text"])
        print(result["translated_text"])

asyncio.run(main())
```

## ✨ What it does

- **OCR** from a file, URL, bytes, PIL image or NumPy array. Plain text, blocks (paragraphs, speech bubbles), lines, or words with geometry. Output as text, JSON, JSONL, hOCR or TSV.
- **Translation** into any language Lens supports.
- **Translation drawn onto the image**, like Chrome's Lens overlay: the source text is erased and the translation repainted in the original colours, angle and line box. Right-to-left scripts, vertical Japanese, and a manga mode for comic pages.
- **Warm daemon.** `lens_scan` hands each command to a background process that is already running, so an image takes about 0.4 s instead of 3 s. It starts by itself.
- **ShareX integration**: one command sets up two hotkeys, a fast one and one that always works.
- **Python API** with retries, backoff, fallback keys and endpoints, and a concurrency limit.
- **Region queries**: re-read a small area at native resolution.
- **Proxy support** (HTTP, HTTPS, SOCKS) and **builds for Windows, Linux and macOS**.

## 📚 Documentation

| Page | What is in it |
|---|---|
| [docs/cli.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/cli.md) | Every option and command, output formats, exit codes, config file, `LENS_*` variables and their precedence. |
| [docs/api.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/api.md) | `LensAPI`: constructor, `process_image`, `process_region`, result fields, exceptions, examples. |
| [docs/rendering.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/rendering.md) | Drawing the translation onto the image: vertical text, erase modes, outline, manga mode, fonts. |
| [docs/daemon.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/daemon.md) | Fast mode and the warm daemon, the login service, the HTTP API, the security model. |
| [docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md) | All install methods, updating, checksums and provenance, pinning a version, Docker. |
| [docs/sharex.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/sharex.md) | ShareX setup: the two hotkeys, uploader mode, manual setup, troubleshooting. |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release. |

## ❤️ Support & Acknowledgments

-   **OWOCR**: Greatly inspired by and based on [OWOCR](https://github.com/AuroraWright/owocr). Thank you to them for their research into Protobuf and OCR implementation.
-   **Chrome Lens OCR**: For the original implementation and ideas that formed the basis of this library. The update with SHAREX support was originally tested and added by me to [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr), thanks for the initial implementation and ideas.
-   **AI Collaboration**: A significant portion of the v3.0 code, including the architectural refactor, asynchronous implementation, and Protobuf integration, was developed in collaboration with an advanced AI assistant.
-   **GOOGLE**: For the convenient and high-quality Lens technology.
-   **Support the Author**: If you find this library useful, you can support the author - **[Boosty](https://boosty.to/pinus)**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bropines/chrome-lens-py&type=Date)](https://www.star-history.com/#bropines/chrome-lens-py&Date)

### Disclaimer

This project is intended for educational and experimental purposes only. Use of Google's services must comply with their Terms of Service. The author is not responsible for any misuse of this software.
