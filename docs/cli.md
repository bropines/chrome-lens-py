# Command-line reference

[Back to the README](../README.md)

```bash
lens_scan <image_source> [ocr_lang] [options]
lens_scan <command> [options]
```

- **`image_source`**: a path to an image file, an image URL, or a directory. A directory is processed file by file (supported images only, sorted by name).
- **`ocr_lang`** (optional): BCP 47 code of the language to recognise (`en`, `ja`). Auto-detected if omitted.
- **`command`**: one of the verbs that manage `lens_scan` itself rather than read an image, see [Commands](#commands).

`lens_scan -h` prints a short help: the commands and the dozen most-used scan options. `lens_scan help options` prints the full list of options; it is generated from the argument parser and is what the [Options](#options) table below follows. `lens_scan help <command>` (or `lens_scan <command> -h`) explains one command.

## Contents

- [Options](#options)
- [Output formats](#output-formats)
- [Examples](#examples)
- [Commands](#commands)
- [The old flags](#the-old-flags)
- [Exit codes and streams](#exit-codes-and-streams)
- [Configuration](#configuration)

## Options

Defaults are in the description. Options marked "setting" can also be set in the config file or a `LENS_*` variable, see [Configuration](#configuration).

| Option | Short | Description |
| :--- | :--- | :--- |
| **Translation** | | |
| `--translate LANG` | `-t` | Translate the recognised text into this language (`en`, `ru`). Setting. |
| `--translate-from LANG` | | Source language of the translation. Auto-detected if omitted. |
| `--translate-out FILE` | `-to` | Save the image with the translation painted on it. With several images, files get `_1`, `_2`, ... before the extension. See [Overlay rendering](rendering.md). |
| **Output** | | |
| `--format FMT` | | `text` (default), `json`, `jsonl`, `hocr` or `tsv`. See [Output formats](#output-formats). |
| `--oneline` | | One compact JSON line per image: `{"file", "ocr_text", "translated_text", "error"}`. Drop-in for the [Chrome-Lens-OCR](https://github.com/timminator/Chrome-Lens-OCR) fork (SubtitleEdit, VideOCR). |
| `--output-blocks` | `-b` | Print the text as segmented blocks (paragraphs, speech bubbles). |
| `--output-lines` | `-ol` | Print the text as individual lines. |
| `--get-coords` | | Print every recognised word with its geometry (centre, size, angle) as JSON. |
| `--ocr-single-line` | | Join the recognised text into one line. Line breaks are kept by default. Setting (`ocr_preserve_line_breaks`, inverted). |
| `--quiet` | `-q` | No informational messages, result data only. |
| `--sharex` | `-sx` | Copy the result to the clipboard: the translation if `-t` is given, else the OCR text. Needs the `[clipboard]` extra. |
| `--region CX,CY,W,H` | | Re-read one region at native resolution; four numbers, normalised 0..1. See [Region queries](#region-queries). |
| `--text-query TEXT` | | Text to send alongside `--region`. |
| **Overlay rendering** (with `--translate-out`; details in [rendering.md](rendering.md)) | | |
| `--overlay-mode MODE` | | `chromium` (default) or `legacy` (white boxes, deprecated). Setting. |
| `--vertical-text MODE` | | `auto` (default), `keep` or `horizontal`. Setting. |
| `--erase-mode MODE` | | `patch` (default) or `hull`. Setting. |
| `--hull-padding N` | | How far the hull reaches past the text, in line heights (default `0.45`). Setting. |
| `--outline N` | | Multiplier on the outline behind translated text; `0` removes it (default `1.0`). Setting. |
| `--min-text-size PX` | | Floor on the rendered text size (default `0`). Setting. |
| `--text-align SIDE` | | `auto` (default), `left`, `center` or `right`. Setting. |
| `--manga` | | Preset for pages of vertical Japanese. Setting. |
| `--manga-growth N` | | How much wider than the detected box to lay out in manga mode (default `1.45`). Setting. |
| `--font FONT_PATH` | | A `.ttf` font for the overlay. Setting. |
| `--font-size SIZE` | | Font size for the overlay (default `20`). Setting. Used by the `legacy` overlay; `chromium` mode fits the size to each line. |
| **Daemon / fast mode** (details in [daemon.md](daemon.md)) | | |
| `--daemon MODE` | | `auto` (default), `on` or `off`. Setting. |
| `--daemon-idle-timeout SEC` | | An automatically started daemon exits after this long without requests (default `600`, `0` = never). Setting. |
| **Server (foreground; the `serve` command)** | | |
| `--auto` | | With `serve`: run as the managed daemon (private socket or ephemeral port, random token, idle exit). This is what `daemon start` runs. |
| `--service` | | With `serve`: run as the persistent daemon on `--port`, with the token written by `sharex --mode uploader` or `service install`. No idle exit. |
| `--host ADDR` | | Address to bind (default `127.0.0.1`). |
| `--port N` | | Port to bind (default `8765`). Also the port of `service install` and `sharex`. Setting (`daemon_port`). |
| `--token TOKEN` | | Require this bearer token. Mandatory when `--host` is not loopback. |
| `--allow-origin ORIGIN` | | Let one browser origin call the server. Repeatable. None by default. |
| **Connection** | | |
| `--api-key KEY` | | Google Cloud API key. Prefer `LENS_API_KEY`: a flag lands in your shell history. Setting. |
| `--proxy URL` | | Proxy, for example `http://user:pass@host:port` or `socks5://127.0.0.1:9050`. Setting. |
| `--no-env-proxy` | | Ignore `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` and connect directly. Setting (`trust_env`, inverted). |
| `--timeout SEC` | | Request timeout in seconds (default `60`). Setting. |
| `--retries N` | | Retries after a network error or a retryable HTTP status (default `2`). Setting. |
| `--concurrency N` | | Maximum concurrent requests (default `5`, at most `30`; a warning above `20`). Setting. |
| `--client-region CODE` | | Client region code (default `US`). Setting. |
| `--client-time-zone ID` | | Client time zone ID (default `America/New_York`). Setting. |
| **Configuration and setup** | | |
| `--config-file FILE` | | Read this JSON config file instead of the default one. |
| `--update-config` | | Save the settings given on this command line into the default config file, never the API key. The previous file is kept as `config.json.bak`. Works without an image. Has no effect together with `--config-file`. |
| `--show-config` | | Print every setting, its value and which layer set it. This is what `lens_scan config show` runs. |
| `--json` | | With `--show-config`: print it as JSON. |
| `--logging-level LEVEL` | `-l` | `DEBUG`, `INFO`, `WARNING` (default) or `ERROR`. Setting. |
| `--version` | `-V` | Print the version and which copy is running: its kind, the interpreter, the package path, and whether the clipboard extra is installed. |
| `--help` | `-h` | Show the short help and exit. `lens_scan help options` prints this full list. |

Mutually exclusive: `-b`, `-ol`, `--get-coords`, `--oneline` and `--format` other than `text`. None of them combines with `--region`.

## Output formats

Result data goes to stdout, everything else to stderr.

| Choice | What you get |
| :--- | :--- |
| default (`--format text`) | The OCR text, then the translation if one was requested, under short headings. `-q` drops the headings. |
| `-b` / `-ol` | The same, split into blocks or lines. |
| `--get-coords` | A JSON array with one entry per word: `{"word": {center_x, center_y, width, height, angle_deg}}`. Coordinates are normalised 0..1. |
| `--oneline` | One JSON line per image: `{"file", "ocr_text", "translated_text", "error"}`. |
| `--format json` | One JSON object per image (an array for several images, always one document): `file`, `width`, `height`, `detected_language`, `ocr_text`, `translated_text` and `blocks`, each holding `lines`, each holding `words`. Every node has `text` and `geometry`, plus a pixel `bbox` (`left`, `top`, `width`, `height`) when the image size is known. A failed image is `{"file", "error"}`. |
| `--format jsonl` | The same objects, one compact line each, printed as soon as each image is done. |
| `--format hocr` | hOCR 1.2 (XHTML) with pixel `bbox`es: page, area, paragraph, line and word elements. |
| `--format tsv` | Tesseract-style TSV, levels 1 (page) to 5 (word). Lens reports no confidence: words get `100`, structural rows `-1`. |

## Examples

```bash
lens_scan image.png -t en                                  # OCR + translate, language auto-detected
lens_scan manga.jpg ja -b                                  # segmented blocks
lens_scan document.png --output-lines                      # lines with geometry
lens_scan diagram.png --get-coords                         # every word with its box
lens_scan manga.jpg ja -t ru -to translated.png -sx        # translate, save the overlay, copy the text
lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
lens_scan scans/ --format jsonl -q > out.jsonl             # a whole directory
lens_scan image.png --proxy socks5://127.0.0.1:9050
```

### Region queries

The full-image pass downscales anything over 1600 px, which is when small print suffers. A region query sends only the cropped pixels, at native scale:

```bash
lens_scan page.png --region 0.8,0.82,0.35,0.06
lens_scan page.png --region 0.8,0.82,0.35,0.06 --text-query "what does this say"
```

The four numbers are the centre x, centre y, width and height, as fractions of the full image. Returned geometry is in full-image coordinates. From Python: [`process_region`](api.md#process_region).

## Commands

Reading an image is one job; keeping the machinery around it healthy is another: the warm daemon, the login service, the ShareX hotkeys, updates. That second job used to be a row of flags that behaved like commands (they ignore the image and each other), so it has verbs now. They run in your own process and never go through the daemon.

A first argument that names a command is always the command, even if a file of that name exists, so `lens_scan status` does not depend on the directory you are in. `lens_scan ./status` scans the file. This is the rule git, docker and cargo use.

| Command | What it does |
| :--- | :--- |
| `lens_scan status [--json]` | One screen: the version and how this copy was installed, the daemon, the login service, the ShareX hotkeys, the clipboard extra, the config file path and the state directory. No network. Exits 0 unless a daemon is recorded but does not answer, or the login service is installed and no daemon is running. |
| `lens_scan daemon status\|start\|stop\|restart\|logs` | The warm background daemon, see [daemon.md](daemon.md#controlling-the-daemon). `--json` on `status`, `--lines N` on `logs` (default 40), `--idle-timeout SEC` on `start` and `restart`. `status` exits 0 when the daemon runs and 1 when it does not, like `systemctl is-active`. |
| `lens_scan service status\|install\|uninstall\|start\|stop\|restart\|logs` | The daemon as a login service, see [daemon.md](daemon.md#running-it-as-a-login-service). `--port N` on `install`, `--lines N` on `logs`, `--json` on `status`. |
| `lens_scan sharex [--mode MODE] [-t LANG] [--port N]` | Wire `lens_scan` into ShareX (Windows), see [sharex.md](sharex.md). `--mode` is `program` (default, **Ctrl + O** runs `lens_scan`), `uploader` (**Ctrl + Shift + O** posts to the daemon) or `both`. `-t LANG` makes the hotkey translate. |
| `lens_scan update [--check] [--dry-run] [--json]` | Update this copy the way it was installed, see [below](#lens_scan-update). |
| `lens_scan config show\|path [--json]` | `show` (the default) prints every setting, its value and which layer set it; `path` prints the config file's location. See [Configuration](#configuration). |
| `lens_scan serve [options]` | Run the [HTTP API](daemon.md#http-api) in this terminal. Takes the options of the Server group above. |
| `lens_scan version [--json]` | What `--version` prints; `--json` gives the same facts as an object. |
| `lens_scan help [<command>\|options]` | The short help, the help of one command, or the full option list. |

```bash
lens_scan status
lens_scan daemon restart
lens_scan service install --port 9000
lens_scan sharex --mode both -t en
lens_scan update --check
lens_scan config show --json
```

### `lens_scan update`

Half a dozen things can own the name `lens_scan`, and each has its own idea of an update. Running the wrong one is worse than running none: `pip install -U` into a Homebrew install leaves two copies and the wrong one first on `PATH`. So `update` finds out how this copy was installed and runs that installer's own upgrade:

| Installed with | What runs |
| :--- | :--- |
| uv tool | `uv tool upgrade --refresh chrome-lens-py`. uv caches the package index for ten minutes, which is long enough to miss a release that has just gone out. |
| pipx | `pipx upgrade chrome-lens-py` |
| Homebrew | `brew upgrade bropines/tap/lens-scan` |
| Scoop | `scoop update <app>`, with the app name taken from the install path, so `lens-scan-portable` stays portable. |
| a standalone build from `install.ps1` / `install.sh` | The same installer, run again. On Windows it gets a new console window of its own, because Windows will not let a program replace its own running executable. |
| pip | `pip install --upgrade chrome-lens-py`, with the `[clipboard]` extra only if `pyperclip` is already installed. |
| a git checkout, a Docker image, a hand-unzipped archive | Nothing. A printed instruction instead of a guess. |

The newest version comes from PyPI's JSON API. Every channel is published from one release run, so one number describes them all, and PyPI needs no token. The command is always printed before it runs.

- `--check` only compares this version with the newest one.
- `--dry-run` prints the command without running it.
- `--json` reports what it found (`version`, `latest`, `update_available`, `method`, `command`, `hint`) and never updates, so a script can decide for itself.

A running daemon is stopped first because it holds the files being replaced, and started again afterwards: through the login service if that is what owned it. Run on a copy that is already the newest, `update` still runs the installer, since reinstalling is a reasonable thing to want; it says so first. `--check` and `--json` exit 1 if pypi.org could not be reached.

## The old flags

These still work and are not going away: ShareX configurations, Startup shortcuts, LaunchAgents and systemd units on people's machines contain them. They are no longer the documented spelling.

| Old flag | Now |
| :--- | :--- |
| `--daemon-status` | `lens_scan daemon status` |
| `--daemon-start` | `lens_scan daemon start` |
| `--daemon-stop` | `lens_scan daemon stop` |
| `--install-service` | `lens_scan service install` |
| `--uninstall-service` | `lens_scan service uninstall` |
| `--setup-sharex` (with `--mode`) | `lens_scan sharex` (with `--mode`) |
| `--serve` | `lens_scan serve` |

## Exit codes and streams

| Code | Meaning |
| :--- | :--- |
| `0` | Every image succeeded. An image that contains no text is still a success. |
| `1` | All images failed, or the run could not start: a source that is not an image, a directory with no images in it, a bad config file. |
| `2` | Some of several images failed. |
| `64` | The command line was wrong: an unknown option, a value of the wrong kind, nothing to read, options that exclude each other, a command used wrongly, or `--serve` on a public address without `--token`. |
| `130` | Interrupted. |

64 is `EX_USAGE` from `sysexits.h`. It used to be argparse's `2`, which is also "some images failed"; a caller could not tell a typo from a half-finished batch. Commands exit 0 or 1, and 64 when they are used wrongly; the cases where `status`, `daemon status` and `update` exit 1 are listed above.

Headers, progress and errors go to stderr, so `lens_scan img.png > out.txt` holds only the text. A command's own report - `status`, `daemon status`, `config show`, `update` - is what that command is for, so it goes to stdout, with or without `--json`.

## Configuration

Precedence, highest first: **a flag given explicitly > the config file > a `LENS_*` environment variable > the default**. A flag you did not type never overrides the file.

The default config file is `config.json` in `$XDG_CONFIG_HOME/chrome-lens-py/`, or in `~/.config/chrome-lens-py/` if that variable is not set. This is the same rule on Linux, macOS and Windows (`C:\Users\<user>\.config\chrome-lens-py\config.json`). Use `--config-file` for another file. `lens_scan config path` prints where the default one is, whether or not it exists yet.

When a setting seems not to work, `lens_scan config show` lists every setting with its value and the layer that decided it (`command line`, `config file <path>`, `env LENS_<NAME>` or `default`): usually the setting works and something above it is overriding it. `--json` gives the same as an object. To look at another file, pass `--config-file FILE` to it. The API key and the proxy URL, which may carry a password, are shown as `<hidden>`.

Every key is optional. A file that is not a JSON object, or a value of the wrong type, stops the run with a message that names the key. Unknown keys are ignored with a warning, and `null` means "not set". Keys are case-insensitive and may use `-` for `_`.

| Key | Env variable | Flag | Default |
| :--- | :--- | :--- | :--- |
| `api_key` | `LENS_API_KEY` | `--api-key` | built-in key |
| `proxy` | `LENS_PROXY` | `--proxy` | none |
| `trust_env` | `LENS_TRUST_ENV` | `--no-env-proxy` (inverted) | `true` |
| `client_region` | `LENS_CLIENT_REGION` | `--client-region` | `US` |
| `client_time_zone` | `LENS_CLIENT_TIME_ZONE` | `--client-time-zone` | `America/New_York` |
| `timeout` | `LENS_TIMEOUT` | `--timeout` | `60` |
| `retries` | `LENS_RETRIES` | `--retries` | `2` |
| `concurrency` | `LENS_CONCURRENCY` | `--concurrency` | `5` (max 30) |
| `target_lang` | `LENS_TARGET_LANG` | `-t` | none (no translation) |
| `ocr_preserve_line_breaks` | `LENS_OCR_PRESERVE_LINE_BREAKS` | `--ocr-single-line` (inverted) | `true` |
| `logging_level` | `LENS_LOGGING_LEVEL` | `-l` | `WARNING` |
| `font_path` | `LENS_FONT_PATH` | `--font` | system font |
| `font_size` | `LENS_FONT_SIZE` | `--font-size` | `20` |
| `overlay_mode` | `LENS_OVERLAY_MODE` | `--overlay-mode` | `chromium` |
| `vertical_text` | `LENS_VERTICAL_TEXT` | `--vertical-text` | `auto` |
| `erase_mode` | `LENS_ERASE_MODE` | `--erase-mode` | `patch` |
| `hull_padding` | `LENS_HULL_PADDING` | `--hull-padding` | `0.45` |
| `outline_scale` | `LENS_OUTLINE_SCALE` | `--outline` | `1.0` |
| `min_readable_px` | `LENS_MIN_READABLE_PX` | `--min-text-size` | `0` |
| `text_align` | `LENS_TEXT_ALIGN` | `--text-align` | `auto` |
| `manga_mode` | `LENS_MANGA_MODE` | `--manga` | `false` |
| `manga_box_growth` | `LENS_MANGA_BOX_GROWTH` | `--manga-growth` | `1.45` |
| `daemon` | `LENS_DAEMON` | `--daemon` | `auto` |
| `daemon_idle_timeout` | `LENS_DAEMON_IDLE_TIMEOUT` | `--daemon-idle-timeout` | `600` |
| `daemon_port` | `LENS_DAEMON_PORT` | `--port` | `8765` |

Also accepted as config keys: the flag spellings `translate`, `font`, `outline`, `min_text_size`, `manga`, `manga_growth` and `no_env_proxy`. Booleans in environment variables take `1/0`, `true/false`, `yes/no`, `on/off`. An empty variable counts as unset. `serve` reads the same settings.

Variables that are not settings:

| Variable | Used by |
| :--- | :--- |
| `LENS_ENDPOINT` | Comma-separated list of Lens endpoints, tried in order. Replaces the built-in one. |
| `LENS_STATE_DIR` | Directory for the daemon's state files, see [daemon.md](daemon.md#where-it-lives). |
| `LENS_TOKEN` | Required by the [Docker image](install.md#docker). |
| `LENS_SCAN_VERSION`, `LENS_SCAN_FLAVOR` | The [standalone installers](install.md#standalone-build). |

Example `config.json`:

```json
{
  "proxy": "socks5://127.0.0.1:9050",
  "client_region": "DE",
  "client_time_zone": "Europe/Berlin",
  "timeout": 90,
  "retries": 3,
  "target_lang": "en",
  "overlay_mode": "chromium",
  "concurrency": 4,
  "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
}
```

`api_key` is accepted too, but an environment variable keeps the key out of a file you might share. `--update-config` writes the file atomically and never stores the key.
