"""Zip a directory the way the installers expect, on any OS.

    python scripts/make_zip.py dist/lens_scan-linux-amd64 [dist/lens_scan-linux-amd64.zip]

Writes <dir>.zip (unless a second path is given) containing the directory as
its single top-level folder, and <zip>.sha256 in sha256sum's own format so
`sha256sum -c` verifies it by hand.

Why not 7z or zip: neither is on every runner image (macos-15-intel has no
7z), and Python's own zipfile is. Unix permission bits are kept so the
extracted binary is still executable, and symlinks are stored as symlinks
rather than followed, which keeps macOS framework layouts intact.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import zipfile
from pathlib import Path


def add(archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
    info = os.lstat(path)
    zinfo = zipfile.ZipInfo.from_file(path, arcname)
    # from_file follows nothing: it uses stat() of the target. Rebuild the mode
    # from lstat so links keep their type.
    zinfo.external_attr = (info.st_mode & 0xFFFF) << 16
    if stat.S_ISLNK(info.st_mode):
        zinfo.compress_type = zipfile.ZIP_STORED
        archive.writestr(zinfo, os.readlink(path))
    elif stat.S_ISDIR(info.st_mode):
        archive.writestr(zinfo, b"")
    else:
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        with open(path, "rb") as f:
            archive.writestr(zinfo, f.read(), compresslevel=9)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    if not source.is_dir():
        print(f"Not a directory: {source}", file=sys.stderr)
        return 1
    target = Path(sys.argv[2]) if len(sys.argv) == 3 else source.with_name(source.name + ".zip")

    with zipfile.ZipFile(target, "w") as archive:
        add(archive, source, source.name + "/")
        for dirpath, dirnames, filenames in os.walk(source):
            dirnames.sort()
            for name in sorted(dirnames) + sorted(filenames):
                path = Path(dirpath) / name
                if path.is_dir() and not path.is_symlink():
                    add(archive, path, f"{source.name}/{path.relative_to(source).as_posix()}/")
                else:
                    add(archive, path, f"{source.name}/{path.relative_to(source).as_posix()}")

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sum_file = target.with_name(target.name + ".sha256")
    sum_file.write_text(f"{digest}  {target.name}\n", encoding="ascii", newline="\n")
    print(f"{target} ({target.stat().st_size / 1e6:.1f} MB)\n{digest}  {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
