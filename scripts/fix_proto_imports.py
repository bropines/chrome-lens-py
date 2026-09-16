"""Rewrite the generated protobuf modules to import each other relatively.

protoc emits `import lens_overlay_geometry_pb2 as ...` - a bare top-level name
that only resolves if the generating directory is on sys.path. This package used
to arrange that by inserting the directory at import time, which works from a
source tree and fails in a frozen build, where there is no such directory to
point at.

Rewriting the imports to `from . import lens_overlay_geometry_pb2 as ...` makes
them resolve through the package itself, so the hack is unnecessary and the
binaries actually run. Run after regenerating.
"""

import pathlib
import re
import sys

PROTOBUFS = (
    pathlib.Path(__file__).resolve().parent.parent
    / "src"
    / "chrome_lens_py"
    / "utils"
    / "protobufs"
)

# `import x_pb2 as y` at the start of a line, and nothing dotted.
PATTERN = re.compile(r"^import (\w+_pb2) as (\w+)$", re.MULTILINE)


def main() -> int:
    if not PROTOBUFS.is_dir():
        print(f"No such directory: {PROTOBUFS}", file=sys.stderr)
        return 1

    changed = 0
    for path in sorted(PROTOBUFS.glob("*_pb2.py")):
        source = path.read_text(encoding="utf-8")
        rewritten, count = PATTERN.subn(r"from . import \1 as \2", source)
        if count:
            path.write_text(rewritten, encoding="utf-8")
            changed += 1
            print(f"  {path.name}: {count} import(s)")

    print(f"Rewrote {changed} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
