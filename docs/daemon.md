# Daemon, fast mode and HTTP API

[Back to the README](../README.md)

A cold `lens_scan` spends most of its time importing Pillow, protobuf and httpx and opening a fresh TLS connection to Google. A process that is already running has done both. So `lens_scan` hands each command to a warm background daemon **by itself**. There is nothing to set up.

This page has three parts: the automatic [fast mode](#fast-mode), the [HTTP API](#http-api) for your own programs, and the [security model](#what-can-reach-it).

## Contents

- [Fast mode](#fast-mode)
- [Controlling the daemon](#controlling-the-daemon)
- [Where it lives](#where-it-lives)
- [Running it as a login service](#running-it-as-a-login-service)
- [HTTP API](#http-api)
- [What can reach it](#what-can-reach-it)

## Fast mode

Measured on Windows 11 and Python 3.13 against the real API through a local proxy, the same image each time, median of 7:

| | median | range |
|---|---|---|
| cold `lens_scan` (`--daemon off`) | 3323 ms | 3233-3762 ms |
| `lens_scan` -> warm daemon | **451 ms** | 392-481 ms |
| `POST /v1/ocr/raw` with `curl` (no `lens_scan` process at all) | **318 ms** | 304-363 ms |
| for scale: `python -c pass` on the same machine | 98 ms | 82-143 ms |

### How `auto` works (the default)

1. `lens_scan` looks for the daemon's discovery file. If a daemon of the same version is running, it sends it the command line and prints what comes back: the same stdout, stderr and exit code.
2. If none is running, the command runs in the process itself, as it always did, **and** a detached background daemon is started for the next call. It has no console window and inherits nothing from the caller, so ShareX can read the output to EOF without waiting for the daemon.
3. The daemon exits by itself after `daemon_idle_timeout` seconds without requests (default 600) and removes its files.

Correctness never depends on the daemon. If anything is off, the client silently runs the command in-process instead: no daemon, a stale file, a version mismatch, a refused or dropped connection (even mid-request), a reply that does not parse, a timeout. A daemon of a different version is asked to exit and is replaced. Several first calls at once start one daemon (a lock file), not several.

The daemon runs the same CLI code, with the client's working directory (so relative paths work), the client's `LENS_*` variables and config file, and `--sharex` copying to the clipboard of your session. These never run in the daemon: `--help`, `--version`, `--setup-sharex`, `--update-config`, `--serve`, the service and daemon commands, and any command line that argparse would reject. They run in your own process and behave exactly as without a daemon.

## Controlling the daemon

```bash
lens_scan img.png --daemon off          # this call only
export LENS_DAEMON=off                  # this shell or CI job
#   "daemon": "off"                     # in config.json, for good
lens_scan img.png --daemon on           # wait up to 5 s for a starting daemon
                                        # instead of running in-process

lens_scan --daemon-status               # pid, version, uptime, transport, requests, idle time left
lens_scan --daemon-stop
lens_scan --daemon-start                # normally unnecessary

lens_scan --daemon-idle-timeout 3600 img.png    # longer-lived daemon
lens_scan --daemon-idle-timeout 0 img.png       # never exits on its own
```

To keep the automatic daemon alive for good, set `daemon_idle_timeout` to `0` in `config.json` or `LENS_DAEMON_IDLE_TIMEOUT=0`.

Use `LENS_DAEMON=off` in CI and containers, where a process that outlives the job is unwelcome.

Things to know:

- The client forwards `LENS_*` variables and a few rendering variables (`NO_COLOR`, `FORCE_COLOR`, `COLORTERM`, `TERM`, `XDG_CONFIG_HOME`). It does **not** forward `HTTP_PROXY`, `HTTPS_PROXY` or `ALL_PROXY`: the daemon reads those from the environment it was started in. After changing them run `lens_scan --daemon-stop`, or set `proxy` / `LENS_PROXY`, which are forwarded.
- `-l DEBUG` in a forwarded run shows this package's debug log, not httpx's.
- There is one daemon per user. It keeps one HTTP/2 connection per distinct combination of API key, proxy, timeout, region and the other connection settings.

## Where it lives

| | Windows | macOS | Linux |
|---|---|---|---|
| state directory | `%LOCALAPPDATA%\chrome-lens-py\` | `~/Library/Caches/chrome-lens-py/` | `$XDG_RUNTIME_DIR/chrome-lens-py/`, else `~/.cache/chrome-lens-py/` |
| transport | `127.0.0.1`, ephemeral port | Unix socket in that directory | Unix socket in that directory |
| directory / file mode | per-user ACL inherited from `%LOCALAPPDATA%` | `0700` / `0600` | `0700` / `0600` |
| log and `service.json` | the state directory | the state directory | `~/.cache/chrome-lens-py/` (the runtime directory vanishes at logout) |

`daemon.json` in the state directory holds `{version, pid, transport, address, token, started_at}`. It is written atomically and is how a client finds the daemon. The log is `daemon.log`. Override the state directory with `LENS_STATE_DIR`.

## Running it as a login service

The ShareX uploader mode needs a daemon that is always there, on a fixed port. `--install-service` sets that up:

```bash
lens_scan --install-service              # port from --port / daemon_port, default 8765
lens_scan --uninstall-service
```

| OS | What is installed |
|---|---|
| Windows | A Startup-folder shortcut that runs a small **supervisor**. It starts the daemon without a console window and restarts it if it crashes. |
| macOS | A LaunchAgent with `KeepAlive`. |
| Linux | A `systemd --user` unit with `Restart=on-failure`. |

The service daemon has a token that survives restarts (`service.json`) and is never stopped for being idle.

The Windows supervisor restarts a crashed daemon after 1 s, then 2, 4, and so on up to 60 s while it keeps crashing. A daemon that stayed up for a minute resets the delay to 1 s. A deliberate stop (`--daemon-stop`, `--uninstall-service`) exits with code 0 and ends the supervisor too. Its log is `supervisor.log` next to `daemon.log`.

`lens_scan --setup-sharex --mode uploader` and `--mode both` install this service for you, see [sharex.md](sharex.md).

## HTTP API

`lens_scan --serve` runs a plain HTTP server in the foreground, for your own programs. Importing Pillow, protobuf and httpx costs about a second; if something calls `lens_scan` repeatedly, run the server and pay that once.

```bash
lens_scan --serve                      # http://127.0.0.1:8765
lens_scan --serve --port 9000 --token secret
```

| Route | Body |
|---|---|
| `POST /v1/ocr` | `{"image": "<path or URL>"}` or `{"image_b64": "..."}`, plus any of `translate_to`, `translate_from`, `ocr_language`, `ocr_preserve_line_breaks`, `output_format`, `overlay_path`, `overlay_mode`, `vertical_text`, `erase_mode`, `hull_padding`, `outline_scale`, `min_readable_px`, `text_align`, `manga_mode`, `manga_box_growth`, `return_overlay`, `overlay_format` |
| `POST /v1/region` | The same image source, plus `"region": [center_x, center_y, width, height]` normalised 0..1, and optionally `text_query`, `ocr_language`, `ocr_preserve_line_breaks`. |
| `POST /v1/ocr/raw` | The image itself as the body (`Content-Type: image/png`, `image/jpeg`, `image/webp` or `image/bmp`). Query: `translate_to`, `translate_from`, `ocr_language`, `preserve_line_breaks`, `format=text\|json`. Answers `text/plain`: the translation if one was asked for, else the OCR text. Made for ShareX's custom uploader. |
| `GET /health` (also `/`) | Liveness check; reports the version. Never needs the token. |
| `GET /v1/version` | Version, Python version and limits. |

The rendering options of the CLI are accepted under their API names ([rendering.md](rendering.md#settings-reference)): `--erase-mode hull --outline 3` on the command line is `"erase_mode": "hull", "outline_scale": 3` in the body. `output_format` takes the values of [`process_image`](api.md#process_image). JSON routes need `Content-Type: application/json`.

A caller with no shared disk sets `"return_overlay": true` and gets the rendered translation in the response as base64 under `overlay_image` (PNG, or WebP with `"overlay_format": "webp"`). `overlay_path` writes a file on the server's disk and is accepted only when the server is bound to loopback.

Errors are JSON, `{"error": ...}`, with these statuses: 400 bad JSON, field or image; 401 wrong token; 403 origin refused; 404 no such route; 405 wrong method; 413 body over the limit (32 MiB); 415 wrong `Content-Type`; 429 upstream rate limit (`Retry-After` is passed on); 502 Lens unreachable or failing; 504 timeout. Every response carries `X-Request-ID`.

```bash
curl -X POST -H "Authorization: Bearer secret" -H "Content-Type: image/png" \
     --data-binary @shot.png "http://127.0.0.1:9000/v1/ocr/raw?translate_to=ru"
```

### The managed daemon

The background daemon of fast mode is the same server, started with `--serve --auto`, and adds three routes. They all need the token and exist only on a local listener:

| Route | Purpose |
|---|---|
| `POST /v1/cli` | Run a whole `lens_scan` command line and return its output. |
| `GET /v1/status` | pid, uptime, requests served, idle time left. |
| `POST /v1/shutdown` | Stop the daemon. |

## What can reach it

The server holds an API key and will call Google for anyone who reaches it, so the defaults are deliberately closed.

- **No web page can use it.** A request carrying an `Origin` header is refused unless you named that origin with `--allow-origin`. The check is on the *request*, not the response, because a page can send a POST it is forbidden to read and still get the side effect it wanted: a Google call billed to your key, or a file opened off your disk.
- **`--host` anywhere but loopback requires `--token`**, and then the server accepts only `image_b64`. A path or a URL is something it would open itself, which on a network listener means reading your disk, or fetching a host of the caller's choosing.
- Tokens are compared in constant time.
- **`/v1/ocr/raw` is closed to pages for the same reason as the JSON routes.** The four image types it accepts are not ones a page may send without a CORS preflight (only `text/plain`, form-encoded and multipart are), and the preflight carries an `Origin`, which is refused. The tests cover both the POST and the preflight.
- **The background daemon of fast mode is stricter still.** Its private socket or ephemeral port is announced only in a file readable by your user, every request needs its random token, and its extra routes (`/v1/cli`, `/v1/status`, `/v1/shutdown`, which can run a `lens_scan` command on your behalf) exist only on a local listener that has a token. The token is a random 32-byte string (`secrets.token_urlsafe`); on POSIX the socket's permissions already keep other users out, and the token is sent regardless. The client sends no `Origin`, so no browser can reach it.

```bash
# let one page you control use it
lens_scan --serve --allow-origin https://yoursite.example

# on the network: token required, pixels only
lens_scan --serve --host 0.0.0.0 --token "$(openssl rand -hex 24)"
```

The Tampermonkey userscript does **not** need any of this. It talks to Google directly through `GM_xmlhttpRequest`, which is not subject to CORS. Opening the server to a browser origin is only for pages you write yourself.

The [Docker image](install.md#docker) runs `--serve` on `0.0.0.0` inside the container, which is why it refuses to start without `LENS_TOKEN`.
