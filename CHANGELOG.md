# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/). Future entries are generated from
conventional commits with [git-cliff](https://git-cliff.org) (see `cliff.toml`).

## [Unreleased]

## [3.6.0] - 2026-10-17

### Highlights

- **Warm daemon, transparently.** `lens_scan` now talks to a background daemon
  that keeps the imports loaded and the HTTP/2 connection to Google open. The
  first call runs normally and starts one; later calls are forwarded to it.
  Measured on Windows, same image, real API: **401 ms** through the daemon
  against 3433 ms cold. Same flags, same output, same exit codes; any problem
  with the daemon falls back to running in-process. `--daemon off` (or
  `LENS_DAEMON=off`) disables it, `--daemon-status` / `--daemon-stop` manage it,
  and it exits after 10 idle minutes.
- **ShareX without starting a process**: `lens_scan --setup-sharex --mode
  uploader` writes a ShareX custom uploader that POSTs the screenshot straight
  to the daemon (`/v1/ocr/raw`, 318 ms). `--install-service` keeps that daemon
  running from login (Startup folder / LaunchAgent / systemd user unit).
- **Fallback paths**: several API keys (tried in order on an auth error, the
  working one remembered), several endpoints (`LENS_ENDPOINT`), retries with
  jittered backoff that honour `Retry-After`, and an overall deadline per
  request so nothing hangs forever.

### Features

- Output formats: `--format text|json|jsonl|hocr|tsv`, plus `--oneline` and
  `--retries` (drop-in with the timminator fork used by SubtitleEdit/VideOCR).
- One typed `Settings` with a single precedence: command line > config file >
  `LENS_*` environment variables > defaults. Every option, including the
  rendering ones, can now live in `config.json`; `--serve` reads it too.
- `--help` is generated from the parser, so it can no longer drift from it.
- The daemon returns the rendered overlay (`"return_overlay": true`), has
  `/v1/version`, request IDs, size and time limits, and shuts down gracefully.
- Typed exceptions: `LensRateLimitError` (with `retry_after`), `LensAuthError`,
  `LensTimeoutError`, `LensConnectionError`.
- Results carry `image_size` and `overlay_path`.
- `--setup-sharex -t ru` makes the hotkey translate; the ShareX config is
  backed up and written atomically.
- `python -m chrome_lens_py` works.
- Builds for Linux arm64 and macOS Intel; Linux builds target glibc 2.35.
- A portable Windows build with no executable of ours in it (the signed
  python.org `python.exe` plus the package); the installer falls back to it if
  antivirus quarantines the compiled build.
- Docker image (`ghcr.io/bropines/chrome-lens-py`), a Scoop bucket, build
  provenance attestations on every archive.

### Performance

- Rendering 2-2.5x faster: fonts are cached by (path, face, size) instead of
  being reopened up to 990 times per image.
- Image decoding, encoding and rendering run off the event loop, so the
  daemon keeps answering while it renders and `--concurrency` really is
  concurrent.

### Bug Fixes

- Exit codes: 0 all succeeded, 1 all failed, 2 partial. Errors go to stderr,
  results to stdout untouched by rich (which used to wrap long lines at 80
  columns and delete `[...]` from `--get-coords` JSON).
- `-l DEBUG` was silently ignored whenever a config file existed.
- A failed overlay save was reported as saved.
- `--outline 0` did not remove the outline, and the outline setting was
  ignored in manga mode and for vertical text; `--min-text-size` was ignored
  for vertical text.
- Manga/hull mode painted inpaint patches back over the hull fill.
- Text in `.ttc` fonts used the wrong regional face (SC/TC/KR); mixed-script
  lines drew tofu instead of falling back per run. Vertical text uses vertical
  presentation forms for dashes and brackets.
- Transparent PNGs with dark text came back empty: the server composites
  transparency onto black. Uploads now pick a contrasting background.
- `Accept-Encoding: br` was advertised without a brotli decoder installed.
- Concurrent calls on a shared session overwrote each other's routing state,
  and `image_sequence_id` did not advance.
- Python 3.9: `LensAPI` built outside an event loop failed on first use.
- Daemon: error replies could be lost to a TCP reset on Linux; Ctrl+C handling
  of an embedding program was not restored after the server stopped;
  `"false"` was truthy for boolean options; a non-ASCII token crashed the
  connection.
- The protobuf modules are built with a protoc that understands editions (most
  had been silently skipped since February), and the weekly update can no
  longer reintroduce the bare import that breaks frozen builds - it now opens a
  tested pull request instead of pushing.

### Changed

- Informational headers moved from stdout to stderr, so `lens_scan img >
  out.txt` contains only the result.
- Requires `Pillow>=10.1` and `protobuf>=6.33.5`.
- `overlay_mode="legacy"`, `call_raw_endpoint` and `start_new_session` are
  deprecated.

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

[Unreleased]: https://github.com/bropines/chrome-lens-py/compare/v3.6.0...HEAD
[3.6.0]: https://github.com/bropines/chrome-lens-py/compare/v3.5.3...v3.6.0
[3.5.3]: https://github.com/bropines/chrome-lens-py/compare/v3.5.2...v3.5.3
[3.5.2]: https://github.com/bropines/chrome-lens-py/compare/v3.5.1...v3.5.2
[3.5.1]: https://github.com/bropines/chrome-lens-py/compare/v3.5.0...v3.5.1
[3.5.0]: https://github.com/bropines/chrome-lens-py/compare/v3.4.5...v3.5.0
