# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/). Future entries are generated from
conventional commits with [git-cliff](https://git-cliff.org) (see `cliff.toml`).

## [Unreleased]

### Features

- `python -m chrome_lens_py` works.
- json, jsonl, hOCR and tesseract-style TSV output formats.
- Typed settings, more robust config file I/O, and a safer `--setup-sharex`.
- Prebuilt standalone binaries for Linux arm64 and macOS Intel
  (`lens_scan-linux-arm64.zip`, `lens_scan-macos-x86_64.zip`); the Linux
  binaries are built on Ubuntu 22.04 so they run on older glibc.
- A portable Windows build with no executable of ours in it
  (`lens_scan-windows-amd64-portable.zip`): the official, signed embeddable
  Python plus the package as plain files.
- Docker image on `ghcr.io/bropines/chrome-lens-py`, and a Scoop bucket in this
  repository.

### Bug Fixes

- CLI exit codes, plain result output and logging.
- Renderer: hull erase in reflowed paragraphs no longer paints the patches back;
  fonts are cached and face-aware, with per-run fallback.
- The protobuf modules are compiled with a protoc that understands protobuf
  editions; before, most of them were silently skipped and had gone stale.
  They are regenerated, and the runtime requirement is now `protobuf>=6.33.5`.
- The weekly protobuf update can no longer reintroduce bare `import x_pb2`
  lines: it rewrites imports, runs the tests, and opens a pull request.

### Build

- Installers read the release download URLs instead of the rate-limited API,
  require a checksum for releases from 3.5.1, install into a staging directory
  and roll back on failure; `LENS_SCAN_VERSION` pins a release.
- `install.ps1` falls back to the portable build when antivirus removes the
  compiled one.
- One release pipeline: tag/version check, test matrix on Python 3.9-3.14,
  binaries uploaded as artifacts, a draft release, PyPI publish, then publish.
- Pillow requirement raised to 10.1 (`ImageFont.load_default(size)`).

## [3.5.3] - 2026-09-17

### Bug Fixes

- `--sharex` copied nothing in every standalone build ever shipped (pyperclip
  was not bundled).

### Build

- Bump the Homebrew formula automatically on release, as a reusable workflow
  that can also be run by hand.

## [3.5.2] - 2026-09-17

### Bug Fixes

- Non-ASCII output crashed anywhere `LANG` was unset.

## [3.5.1] - 2026-09-17

### Features

- `--version`, and say which copy of it is running.
- One-line install through uv.

### Bug Fixes

- The daemon was usable by any page you happened to visit (browser origins must
  now be allowed explicitly with `--allow-origin`).

### Build

- Publish a SHA-256 for every release asset, and check it in the installers.

### Documentation

- Bring both READMEs back in line with the CLI and the API.

## [3.5.0] - 2026-09-16

### Features

- Chromium-accurate rendering, region queries and a local daemon (`--serve`).
- Port the renderer work back from the userscript.
- One-line installers for the standalone build.

### Bug Fixes

- The released binaries never started (relative imports in the frozen build).
- `--region` was declared but never used.
- Four transport bugs.

### Build

- Ship a standalone folder instead of a onefile binary (faster start, no
  self-extraction for antivirus heuristics to react to).
- Regenerate protobufs from Chromium.
- Gate CI on the offline suite; keep the live-API tests informative.
- Update all actions to Node.js 24 compatible versions.

### Documentation

- Measure the install options and recommend uv first.
- Record what the frozen binary actually costs.

[Unreleased]: https://github.com/bropines/chrome-lens-py/compare/v3.5.3...HEAD
[3.5.3]: https://github.com/bropines/chrome-lens-py/compare/v3.5.2...v3.5.3
[3.5.2]: https://github.com/bropines/chrome-lens-py/compare/v3.5.1...v3.5.2
[3.5.1]: https://github.com/bropines/chrome-lens-py/compare/v3.5.0...v3.5.1
[3.5.0]: https://github.com/bropines/chrome-lens-py/compare/v3.4.5...v3.5.0
