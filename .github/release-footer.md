
## Install

| Platform | Asset |
| --- | --- |
| Windows x64 | `lens_scan-windows-amd64.zip` (compiled) or `lens_scan-windows-amd64-portable.zip` (official signed Python, no compiled executable of ours) |
| Linux x64 / arm64 | `lens_scan-linux-amd64.zip` / `lens_scan-linux-arm64.zip` (built on Ubuntu 22.04) |
| macOS Apple Silicon / Intel | `lens_scan-macos-arm64.zip` / `lens_scan-macos-x86_64.zip` |

Every archive has a `.sha256` next to it and a GitHub build-provenance attestation
(`gh attestation verify <file> --repo bropines/chrome-lens-py`).

Other routes: `uv tool install --python 3.12 "chrome-lens-py[clipboard]"`, `pip install chrome-lens-py`,
Homebrew (`brew install bropines/tap/lens-scan`), Scoop
(`scoop bucket add lens https://github.com/bropines/chrome-lens-py`), or
`docker pull ghcr.io/bropines/chrome-lens-py:@VERSION@`.
