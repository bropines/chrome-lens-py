"""Point the Scoop manifests in bucket/ at a newly published release.

    python scripts/bump_scoop_manifest.py v3.5.4

Run by the release workflow after the release is public. For every manifest it
rewrites the version, the download URL and the hash, reading the hash from the
release's own .sha256 asset (never recomputed). A manifest whose asset does not
exist in this release is an error: a bucket entry that cannot be installed is
worse than a stale one.

Text is edited in place with regexes rather than re-serialised, so the
manifests keep their formatting and diffs stay to the three lines that moved.
"""

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

from bump_tap_formula import REPO, published_sha256

BUCKET = pathlib.Path(__file__).resolve().parent.parent / "bucket"


def bump(path: pathlib.Path, tag: str) -> bool:
    base = f"https://github.com/{REPO}/releases/download/{tag}"
    version = tag.lstrip("v")
    text = path.read_text(encoding="utf-8")

    manifest = json.loads(text)
    url = manifest["architecture"]["64bit"]["url"]
    asset = url.rsplit("/", 1)[1]
    try:
        digest = published_sha256(base, asset.removeprefix("lens_scan-").removesuffix(".zip"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{path.name}: {asset} is not part of {tag} ({exc})")
    print(f"{path.name}: {asset} -> {digest}")

    updated = re.sub(r'("version": ")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1)
    updated, n_url = re.subn(
        r'("url": ")https://github\.com/[^"]*/releases/download/[^"/]+/' + re.escape(asset) + '(")',
        rf"\g<1>{base}/{asset}\g<2>",
        updated,
        count=1,
    )
    updated, n_hash = re.subn(r'("hash": ")[0-9a-f]{64}(")', rf"\g<1>{digest}\g<2>", updated, count=1)
    if n_url != 1 or n_hash != 1:
        raise SystemExit(f"{path.name}: could not find the url/hash lines to rewrite")
    json.loads(updated)  # still valid JSON
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    tag = sys.argv[1]
    changed = [bump(p, tag) for p in sorted(BUCKET.glob("*.json"))]
    print("Updated." if any(changed) else "Manifests already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
