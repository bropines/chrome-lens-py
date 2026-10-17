# Chrome Lens API for Python

**English** | [Русский](/README_RU.md)

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

An asynchronous Python library and a command-line tool (`lens_scan`) for Google Lens. It recognises text in images (OCR), translates it, and gives you the word coordinates. It talks to the same Protobuf endpoint as Chrome's Lens overlay.

## ✨ Features

- **OCR** from a file, URL, bytes, PIL image or NumPy array. Plain text, blocks (paragraphs, speech bubbles), lines, or words with geometry. Output as text, JSON, JSONL, hOCR or TSV.
- **Translation** into any language Lens supports.
- **Translation drawn onto the image**, like Chrome's Lens overlay: the source text is erased and the translation repainted in the original colours, angle and line box. Handles right-to-left scripts and vertical Japanese, with a manga mode for comic pages.
- **Warm daemon.** `lens_scan` hands each command to a background process that is already running, so an image takes about 0.4 s instead of 3 s. It starts by itself.
- **ShareX integration**: one command sets up two hotkeys, a fast one and one that always works.
- **Python API** with retries, backoff, fallback keys and endpoints, and a concurrency limit.
- **Region queries**: re-read a small area at native resolution.
- **Proxy support** (HTTP, HTTPS, SOCKS) and **builds for Windows, Linux and macOS**.

## 📦 Install

| Method | Command | Notes |
|---|---|---|
| **Homebrew** (macOS, Linux) | `brew install bropines/tap/lens-scan` | No Python needed. Apple Silicon and x86_64 Linux. |
| **uv**, Windows | `irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 \| iex` | No Python needed: uv brings its own. No executable of ours, so nothing for antivirus to flag. |
| **uv**, Linux / macOS | `curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh \| sh` | Same. |
| **Standalone**, Windows | `irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 \| iex` | No Python needed. Fastest start (~0.2 s). If your antivirus quarantines the compiled `lens_scan.exe`, the installer switches to the **portable build**, which runs through python.org's signed `python.exe`. Force it with `$env:LENS_SCAN_FLAVOR = 'portable'`. |
| **Standalone**, Linux / macOS | `curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh \| sh` | No Python needed. Verifies the SHA-256 of the download. |
| **Scoop** (Windows) | `scoop bucket add lens https://github.com/bropines/chrome-lens-py` then `scoop install lens-scan` | Or `lens-scan-portable`. |
| **pip** | `pip install "chrome-lens-py[clipboard]"` | Your own Python, 3.9 or newer. The extra enables `--sharex`. |
| **Docker** | `docker run -d -p 127.0.0.1:8765:8765 -e LENS_TOKEN=change-me ghcr.io/bropines/chrome-lens-py` | Runs the HTTP server. `LENS_TOKEN` is required. |

Check it with `lens_scan --version`: it prints which copy runs. Checksums, attestations, version pinning and more: [docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md).

## 🚀 Quick start

```bash
lens_scan image.png                              # OCR, language auto-detected
lens_scan image.png -t en                        # OCR + translate to English
lens_scan image.png ja -t ru -sx                 # recognise Japanese, translate, copy to the clipboard
lens_scan image.png -t en -to out.png            # also save the image with the translation drawn on it
lens_scan page.png ja -t en -to out.png --manga  # manga page: vertical Japanese, bubbles
lens_scan scans/ --format jsonl > out.jsonl      # a whole folder, one JSON object per image
lens_scan --setup-sharex --mode both -t ru       # ShareX: Ctrl+O and Ctrl+Shift+O (Windows)
```

From Python (every call is `async`):

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

Result data goes to stdout and everything else to stderr, so `lens_scan img.png > out.txt` holds only the text. Exit code: `0` all images succeeded, `1` all failed, `2` some failed.

## 📚 Documentation

| Page | What is in it |
|---|---|
| [docs/cli.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/cli.md) | Every option, output formats, exit codes, config file, `LENS_*` variables and their precedence. |
| [docs/api.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/api.md) | `LensAPI`: constructor, `process_image`, `process_region`, result fields, exceptions, examples. |
| [docs/rendering.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/rendering.md) | Drawing the translation onto the image: vertical text, erase modes, outline, manga mode, fonts. |
| [docs/daemon.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/daemon.md) | Fast mode and the warm daemon, the login service, the HTTP API, the security model. |
| [docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md) | All install methods, checksums and provenance, pinning a version, the portable build, Docker. |
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
