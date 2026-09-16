"""Point the Homebrew formula at a newly published release.

Called by the release workflow once every platform has uploaded, so the formula
never names an asset that failed to build.

    python scripts/bump_tap_formula.py v3.5.2 Formula/lens-scan.rb

Checksums are read from the release's own .sha256 assets rather than
recomputed. If the two ever disagreed, the formula would be the wrong one, and
users would be the ones to find out.
"""

import re
import sys
import urllib.request

REPO = "bropines/chrome-lens-py"
ASSETS = ("macos-arm64", "linux-amd64")


def published_sha256(base: str, asset: str) -> str:
    url = f"{base}/lens_scan-{asset}.zip.sha256"
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
    # By shape, not by field position: GNU sha256sum prefixes the line with a
    # backslash when the filename contains one.
    match = re.search(r"[0-9a-fA-F]{64}", body)
    if not match:
        raise SystemExit(f"No SHA-256 in {url}: {body!r}")
    return match.group(0).lower()


def bump(text: str, tag: str, base: str) -> str:
    version = tag.lstrip("v")

    for asset in ASSETS:
        zip_name = f"lens_scan-{asset}.zip"
        digest = published_sha256(base, asset)
        print(f"{zip_name} -> {digest}")

        # The sha256 belonging to this asset is the one on the line after its
        # url, so the two are rewritten together rather than by position.
        pattern = re.compile(
            r'(url ")[^"]*' + re.escape(zip_name) + r'("\s*\n\s*sha256 ")[0-9a-f]{64}(")'
        )
        text, count = pattern.subn(
            lambda m: f"{m.group(1)}{base}/{zip_name}{m.group(2)}{digest}{m.group(3)}",
            text,
        )
        if count != 1:
            raise SystemExit(f"Expected one url+sha256 pair for {zip_name}, found {count}")

    text, count = re.subn(r'(\n  version ")[^"]*(")', rf"\g<1>{version}\g<2>", text)
    if count > 1:
        raise SystemExit("More than one version line; refusing to guess")
    return text


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    tag, path = sys.argv[1], sys.argv[2]
    base = f"https://github.com/{REPO}/releases/download/{tag}"

    with open(path, encoding="utf-8") as f:
        original = f.read()

    updated = bump(original, tag, base)
    if updated == original:
        print("Formula already current.")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"Updated {path} to {tag}")


if __name__ == "__main__":
    main()
