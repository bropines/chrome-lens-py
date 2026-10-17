"""Write the GitHub release body for a tag.

    python scripts/release_notes.py v3.7.0 [CHANGELOG.md] > RELEASE_NOTES.md

Layout, most-read first:

1. Install - one line per platform, because that is what most visitors want.
2. What's new - the CHANGELOG section for the version. A "Highlights" part is
   shown as is and the full list folds away under it; a short section is shown
   whole; a long one without highlights shows its first part and folds the rest.
3. Which file do I need - the assets explained, and how to verify them,
   folded.

Exits 1 if the CHANGELOG has no section for the version, so the workflow can
fall back to generated notes.
"""

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO = "bropines/chrome-lens-py"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/scripts"
SHORT_SECTION_LINES = 30

INSTALL = f"""## Install

**Windows** (PowerShell) - falls back to a build with no compiled executable if
your antivirus quarantines the default one:
```powershell
irm {RAW}/install.ps1 | iex
```

**macOS / Linux**
```bash
brew install bropines/tap/lens-scan
# or, without Homebrew:
curl -fsSL {RAW}/install.sh | sh
```

**With Python** (any OS): `uv tool install "chrome-lens-py[clipboard]"` or
`pip install chrome-lens-py`. **Daemon in Docker**:
`docker run -d -p 127.0.0.1:8765:8765 -e LENS_TOKEN=change-me ghcr.io/{REPO}:@VERSION@`.

Already installed? **`lens_scan update`** - it updates the copy you have the
way it was installed. `lens_scan status` shows what you have.
"""

ASSETS = f"""## Which file do I need?

The installers above pick the right one for you. To download by hand:

| You have | File |
|---|---|
| Windows x64 | `lens_scan-windows-amd64.zip` |
| Windows x64, and your antivirus removes `lens_scan.exe` | `lens_scan-windows-amd64-portable.zip` - runs on python.org's signed `python.exe`, no executable of ours inside |
| Linux x64 (glibc 2.35+: Ubuntu 22.04, Debian 12 and newer) | `lens_scan-linux-amd64.zip` |
| Linux ARM64 | `lens_scan-linux-arm64.zip` |
| macOS, Apple Silicon | `lens_scan-macos-arm64.zip` |
| macOS, Intel | `lens_scan-macos-x86_64.zip` |

Unzip anywhere and run `lens_scan` from the folder (`lens_scan.cmd` in the
portable build). The `.sha256` files are checksums for the archives.

<details>
<summary>Verify a download</summary>

```bash
sha256sum -c lens_scan-linux-amd64.zip.sha256
gh attestation verify lens_scan-linux-amd64.zip --repo {REPO}
```

The second command proves the archive was built by this repository's release
workflow from the tagged commit.
</details>
"""


def version_section(changelog: str, version: str) -> Optional[str]:
    """The body of `## [version]`, without its heading, or None."""
    head = f"## [{version}]"
    lines = changelog.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(head):
            body: List[str] = []
            for rest in lines[i + 1 :]:
                if rest.startswith("## [") or re.match(r"^\[[^\]]+\]: http", rest):
                    break
                body.append(rest)
            text = "\n".join(body).strip()
            return text or None
    return None


def split_subsections(section: str) -> List[Tuple[str, str]]:
    """[(title, body)] for each `### title`; text before the first is ('', ...)."""
    parts: List[Tuple[str, str]] = []
    title, buf = "", []
    for line in section.splitlines():
        if line.startswith("### "):
            if title or "\n".join(buf).strip():
                parts.append((title, "\n".join(buf).strip()))
            title, buf = line[4:].strip(), []
        else:
            buf.append(line)
    if title or "\n".join(buf).strip():
        parts.append((title, "\n".join(buf).strip()))
    return parts


def _render(parts: List[Tuple[str, str]]) -> str:
    return "\n\n".join(
        (f"### {title}\n\n{body}" if title else body) for title, body in parts
    )


def whats_new(section: str) -> str:
    parts = split_subsections(section)
    highlights = [p for p in parts if p[0].lower() == "highlights"]
    rest = [p for p in parts if p[0].lower() != "highlights"]
    if highlights:
        shown, folded = highlights, rest
    elif len(section.splitlines()) <= SHORT_SECTION_LINES or len(parts) <= 1:
        shown, folded = parts, []
    else:
        shown, folded = parts[:1], parts[1:]

    out = _render([(t if t.lower() != "highlights" else "", b) for t, b in shown])
    if folded:
        out += (
            "\n\n<details>\n<summary>All changes</summary>\n\n"
            + _render(folded)
            + "\n\n</details>"
        )
    return out


def build(version: str, changelog: str) -> Optional[str]:
    section = version_section(changelog, version)
    if section is None:
        return None
    body = "\n\n".join(
        [
            INSTALL.strip(),
            f"## What's new in {version}\n\n" + whats_new(section),
            ASSETS.strip(),
            f"Full changelog: [CHANGELOG.md](https://github.com/{REPO}/blob/v{version}/CHANGELOG.md)",
        ]
    )
    return body.replace("@VERSION@", version) + "\n"


def main(argv: List[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    path = Path(argv[2] if len(argv) == 3 else "CHANGELOG.md")
    notes = build(version, path.read_text(encoding="utf-8"))
    if notes is None:
        print(f"No CHANGELOG section for {version}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
