"""Regenerate the checked-in protobuf modules from Chromium's Lens protos.

    python scripts/update_protos.py [--ref main]

What it does, in order:

1. Pins the Chromium ref to one commit, so every file comes from the same tree.
2. Downloads third_party/lens_server_proto/*.proto from that commit.
3. Checks that every import of every file being compiled resolves to a file
   that is also being compiled (or to a well-known google/protobuf proto).
4. Compiles with the protoc bundled in grpcio-tools. The distro protoc (3.21)
   cannot parse `edition = "2023"`/`"2024"` files, which is most of them now;
   a silent skip of those is how the checked-in modules went stale before.
5. Rewrites the bare `import x_pb2` lines to package-relative ones
   (fix_proto_imports.py), prunes modules for protos that no longer exist, and
   formats the output.

It exits non-zero on ANY problem. Nothing is skipped quietly: a file that
cannot be compiled, an import that cannot be resolved, or a bare import left
behind is a failure, because the alternative is a half-updated package that
passes review and breaks at import time.

Needs: grpcio-tools (pinned in scripts/requirements-protos.txt), black, isort.
Set GITHUB_TOKEN to avoid the unauthenticated API rate limit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "src" / "chrome_lens_py" / "utils" / "protobufs"

CHROMIUM = "chromium/chromium"
PROTO_DIR = "third_party/lens_server_proto"

# Files deliberately not compiled. Each entry needs a reason that is printed on
# every run, so an exclusion can never go unnoticed.
EXCLUDED = {
    "aim_communication.proto": (
        "imports tool_mode.proto, model_mode.proto (third_party/omnibox_proto) "
        "and actions_data.proto -> common_quality_data.proto "
        "(components/optimization_guide), none of which belong to this "
        "package; compiling it would mean vendoring unrelated Chromium "
        "protos under their full import paths. The client never uses it."
    ),
}

# Imports that protoc resolves from its own bundled include directory.
WELL_KNOWN_PREFIX = "google/protobuf/"

IMPORT_RE = re.compile(r'^import\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;', re.MULTILINE)


class Failure(Exception):
    pass


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "chrome-lens-py-update-protos"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise Failure(f"GET {url} failed: {exc}") from exc


def resolve_commit(ref: str) -> str:
    data = json.loads(http_get(f"https://api.github.com/repos/{CHROMIUM}/commits/{ref}"))
    return data["sha"]


def list_protos(commit: str) -> list[str]:
    url = f"https://api.github.com/repos/{CHROMIUM}/contents/{PROTO_DIR}?ref={commit}"
    entries = json.loads(http_get(url))
    names = sorted(e["name"] for e in entries if e["type"] == "file" and e["name"].endswith(".proto"))
    if not names:
        raise Failure(f"No .proto files listed under {PROTO_DIR} at {commit}")
    return names


def download(commit: str, names: list[str], dest: Path) -> None:
    base = f"https://raw.githubusercontent.com/{CHROMIUM}/{commit}/{PROTO_DIR}"
    for name in names:
        (dest / name).write_bytes(http_get(f"{base}/{name}"))
    print(f"Downloaded {len(names)} proto file(s).")


def check_imports(stage: Path, names: list[str]) -> None:
    problems = []
    available = set(names)
    for name in names:
        text = (stage / name).read_text(encoding="utf-8")
        for imported in IMPORT_RE.findall(text):
            if imported.startswith(WELL_KNOWN_PREFIX):
                continue
            if imported not in available:
                problems.append(f"{name} imports {imported!r}, which is not being compiled")
    if problems:
        raise Failure(
            "Unresolvable imports (add the file's source to this script or "
            "exclude the importer, with a reason, in EXCLUDED):\n  " + "\n  ".join(problems)
        )


def compile_protos(stage: Path, names: list[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={stage}",
        f"--python_out={out}",
        *names,
    ]
    version = subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc", "--version"],
        capture_output=True,
        text=True,
    )
    print(f"Compiling {len(names)} file(s) with {version.stdout.strip() or 'grpc_tools.protoc'}...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise Failure(f"protoc failed (exit {result.returncode}):\n{result.stderr.strip()}")
    if result.stderr.strip():
        print(result.stderr.strip())


def prune_stale(expected: set[str]) -> None:
    for path in sorted(OUTPUT_DIR.glob("*_pb2.py")):
        if path.name not in expected:
            print(f"  removing stale module {path.name}")
            path.unlink()


def run_tool(*args: str) -> None:
    result = subprocess.run([sys.executable, "-m", *args], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise Failure(f"`python -m {' '.join(args)}` failed (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ref", default="main", help="Chromium branch, tag or commit (default: main)")
    args = parser.parse_args()

    try:
        commit = resolve_commit(args.ref)
        print(f"Chromium {args.ref} = {commit}")

        listed = list_protos(commit)
        for name, reason in EXCLUDED.items():
            if name in listed:
                print(f"EXCLUDED {name}: {reason}")
        names = [n for n in listed if n not in EXCLUDED]
        unknown = [n for n in EXCLUDED if n not in listed]
        if unknown:
            print(f"note: excluded file(s) no longer upstream, remove from EXCLUDED: {', '.join(unknown)}")

        with tempfile.TemporaryDirectory(prefix="lens-protos-") as tmp:
            stage = Path(tmp) / "proto"
            gen = Path(tmp) / "gen"
            stage.mkdir()
            download(commit, names, stage)
            check_imports(stage, names)
            compile_protos(stage, names, gen)

            expected = {n[: -len(".proto")] + "_pb2.py" for n in names}
            produced = {p.name for p in gen.glob("*_pb2.py")}
            if produced != expected:
                raise Failure(
                    f"protoc output mismatch: missing {sorted(expected - produced)}, "
                    f"unexpected {sorted(produced - expected)}"
                )

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            prune_stale(expected)
            for name in sorted(produced):
                shutil.copyfile(gen / name, OUTPUT_DIR / name)
        (OUTPUT_DIR / "__init__.py").touch(exist_ok=True)

        print("Rewriting imports to package-relative form...")
        run_tool_script = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "fix_proto_imports.py")])
        if run_tool_script.returncode != 0:
            raise Failure("fix_proto_imports.py failed")

        print("Formatting generated files...")
        run_tool("black", "--quiet", "--target-version", "py39", str(OUTPUT_DIR))
        run_tool("isort", "--quiet", str(OUTPUT_DIR))
    except Failure as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Updated {len(expected)} protobuf module(s) from chromium@{commit[:12]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
