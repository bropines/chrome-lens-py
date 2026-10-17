# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/). Future entries are generated from
conventional commits with [git-cliff](https://git-cliff.org) (see `cliff.toml`).

## [Unreleased]

## [3.8.2] - 2026-10-17

### Bug Fixes

- `lens_scan update` works on a uv tool install, which is how the Windows and
  the uv installers put it there. `uv tool upgrade` has no `--refresh` (that
  belongs to `uv tool install`), so the command 3.8.1 built was rejected
  outright; and `uv tool install --force` cannot run from inside the tool it
  is replacing, because on Windows that environment holds the very
  `python.exe` executing the update. It now runs `uv tool upgrade --reinstall`,
  which keeps the environment and replaces the packages in it. A tool that was
  installed pinned to a version is reinstalled without the pin instead - `uv
  tool upgrade` honours a pin and would have reported success while moving
  nothing - and on Windows that variant is handed to a console window of its
  own. The extras the tool was installed with (`[clipboard]`) survive either
  way; they are read from uv's own receipt.
- A command's output is flushed as it is written. With stdout redirected, the
  lines `update` prints before handing the terminal to uv or brew appeared
  after that command's own output.

## [3.8.1] - 2026-10-17

### Bug Fixes

- A wrong command line exits 64 everywhere. 3.8.0 gave argparse's usage errors
  a parser that exits 64, but the CLI built its parser with a plain
  `ArgumentParser` for a local run, so `lens_scan img.png --fromat json` still
  exited 2 - the code that means "some images of several failed".
- `lens_scan status` and `lens_scan daemon status` say when the daemon that is
  running is of an older version. It answers with the old behaviour until the
  next scan retires it, which is worth seeing rather than a bare "running".
  `--json` carries it as `daemon.stale`.

## [3.8.0] - 2026-10-17

### Highlights

- **Commands.** The half of `lens_scan` that manages the program rather than
  reading an image has verbs now: `lens_scan status`, `daemon
  status|start|stop|restart|logs`, `service
  install|uninstall|status|start|stop|restart|logs`, `sharex`, `update`,
  `config show|path`, `serve`, `version`, `help`. They were flags
  (`--daemon-status`, `--install-service`, `--setup-sharex`) that looked like
  options but behaved like commands - they ignore the image, they ignore each
  other, and `--help` buried them among sixty other lines. Every old flag
  still works: ShareX configurations, Startup shortcuts, LaunchAgents and
  systemd units written by earlier versions contain them.
- **`lens_scan status`** answers "is this working?" on one screen: the version
  and how this copy was installed, the daemon, the login service, the ShareX
  hotkeys, the clipboard extra, the config file. It asks nothing of the
  network, and exits 1 when something is actually wrong - a login service with
  no daemon behind it, or a daemon that stopped answering.
- **`lens_scan update`** updates this copy the way it was installed: `uv tool
  upgrade --refresh`, `pipx upgrade`, `brew upgrade`, `scoop update`, `pip
  install -U`, or the install script that put a standalone build here. Running
  the wrong one of those is worse than running none, so it works out which
  install it belongs to first; a git checkout, a Docker image or a
  hand-unzipped archive gets a printed instruction instead of a guess. A
  running daemon is stopped before and put back afterwards.
- **`lens_scan -h` is short again** - the commands and the dozen options people
  use - and `lens_scan help options` prints the full reference. `lens_scan help
  <command>` explains one command.

### Features

- Anything that reports takes `--json`: `status`, `daemon status`, `service
  status`, `config show`, `version`, `update`. The human output and the JSON
  are rendered from the same data, so they cannot disagree.
- `lens_scan config show` lists every setting with its value and the layer that
  decided it (command line > config file > `LENS_*` > default), which is the
  first thing to look at when a setting "does not work". `config path` prints
  where the file is. Also available as `--show-config`.
- `lens_scan daemon logs` and `lens_scan service logs [--lines N]` print the end
  of the daemon and supervisor logs, instead of leaving you to find them.
- `lens_scan service start|stop|restart` go through the platform's own manager
  (the Windows supervisor, `launchctl`, `systemctl --user`), because a daemon
  that launchd or systemd watches would be started again a second after being
  killed.
- `lens_scan daemon restart` replaces the stop-then-start pair, and does not
  start a second daemon if the first one would not stop.

### Changed

- **A wrong command line now exits 64** (`EX_USAGE` from `sysexits.h`) instead
  of 1 or argparse's 2. 2 is this CLI's "some images of several failed", so a
  caller could not tell a typo from a half-finished batch. Unknown options, a
  malformed `--region`, two output formats at once, a command used wrongly and
  `--serve` on a public address without `--token` are all 64 now.
- A command whose name matches a file still runs as a command, as in git,
  docker and cargo; `lens_scan ./status` scans the file.
- The commands run in your own process, before the client looks for a daemon,
  and the whole command layer is standard-library-only - so a scan pays nothing
  for it and `lens_scan status` answers in milliseconds.
- The README leads with one install command per platform; everything else moved
  to `docs/install.md`, which now has an "Updating" section.

## [3.7.1] - 2026-10-17

### Bug Fixes

- On Windows, a daemon installed with uv, pipx or any virtual environment
  showed up as two processes: the environment's `python.exe` is a launcher that
  starts the real interpreter and waits on it. The supervisor and the daemon
  now start the real interpreter directly, so the always-on service is exactly
  two processes - the supervisor and the daemon - instead of four.

## [3.7.0] - 2026-10-17

### Features

- **`--setup-sharex --mode both`**: two hotkeys. **Ctrl+Shift+O** posts the
  capture straight to the daemon - no process per capture, the fastest path.
  **Ctrl+O** runs `lens_scan` and keeps working when the daemon is down, then
  brings it back. `--mode uploader` installs only the first.
- **The Windows service restarts a crashed daemon.** The login item runs a small
  supervisor (`--daemon-supervise`) that keeps the daemon as a child and
  restarts it on any abnormal exit, backing off from 1 s to 60 s while it keeps
  crashing. `--daemon-stop` and `--uninstall-service` still stop it for good.
  macOS (launchd `KeepAlive`) and Linux (systemd `Restart=on-failure`) already
  did this.

### Bug Fixes

- Uploader mode no longer asks to be made ShareX's global image destination,
  which would have sent every screenshot the user uploaded anywhere to the OCR
  daemon. The uploader is registered in `UploadersConfig.json` and selected by
  its own hotkey only.
- The compiled `lens_scan.exe` started at login no longer leaves a minimised
  console on the taskbar: it runs under `conhost.exe --headless`.
- Building the HTTP client no longer blocks the event loop while the CA bundle
  loads, which made the daemon miss a status probe right after starting.

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

[Unreleased]: https://github.com/bropines/chrome-lens-py/compare/v3.8.2...HEAD
[3.8.2]: https://github.com/bropines/chrome-lens-py/compare/v3.8.1...v3.8.2
[3.8.1]: https://github.com/bropines/chrome-lens-py/compare/v3.8.0...v3.8.1
[3.8.0]: https://github.com/bropines/chrome-lens-py/compare/v3.7.1...v3.8.0
[3.7.1]: https://github.com/bropines/chrome-lens-py/compare/v3.7.0...v3.7.1
[3.7.0]: https://github.com/bropines/chrome-lens-py/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/bropines/chrome-lens-py/compare/v3.5.3...v3.6.0
[3.5.3]: https://github.com/bropines/chrome-lens-py/compare/v3.5.2...v3.5.3
[3.5.2]: https://github.com/bropines/chrome-lens-py/compare/v3.5.1...v3.5.2
[3.5.1]: https://github.com/bropines/chrome-lens-py/compare/v3.5.0...v3.5.1
[3.5.0]: https://github.com/bropines/chrome-lens-py/compare/v3.4.5...v3.5.0
