# Command-line reference

[Back to the README](../README.md)

```bash
lens_scan <image_source> [ocr_lang] [options]
```

- **`image_source`**: a path to an image file, an image URL, or a directory. A directory is processed file by file (supported images only, sorted by name).
- **`ocr_lang`** (optional): BCP 47 code of the language to recognise (`en`, `ja`). Auto-detected if omitted.

`lens_scan --help` prints the same list; it is generated from the argument parser.

## Contents

- [Options](#options)
- [Output formats](#output-formats)
- [Examples](#examples)
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
| `--daemon-status` | | Show whether the daemon runs, with its pid, uptime and load. |
| `--daemon-start` | | Start the daemon in the background now. |
| `--daemon-stop` | | Stop the running daemon. |
| `--install-service` | | Start the daemon at every login on a fixed port. A Windows Startup shortcut, a macOS LaunchAgent or a Linux `systemd --user` unit. |
| `--uninstall-service` | | Remove what `--install-service` set up. |
| **Server (foreground)** | | |
| `--serve` | | Run a local HTTP server instead of processing an image. |
| `--auto` | | With `--serve`: run as the managed daemon (private socket or ephemeral port, random token, idle exit). This is what `--daemon-start` runs. |
| `--service` | | With `--serve`: run as the persistent daemon on `--port`, with the token written by `--setup-sharex --mode uploader`. No idle exit. |
| `--host ADDR` | | Address to bind (default `127.0.0.1`). |
| `--port N` | | Port to bind (default `8765`). Setting (`daemon_port`). |
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
| `--setup-sharex` | | Wire `lens_scan` into ShareX (Windows). `-t LANG` makes the hotkey translate. See [sharex.md](sharex.md). |
| `--mode MODE` | | With `--setup-sharex`: `program` (default, **Ctrl + O** runs `lens_scan`), `uploader` (**Ctrl + Shift + O** posts to the daemon) or `both`. |
| `--logging-level LEVEL` | `-l` | `DEBUG`, `INFO`, `WARNING` (default) or `ERROR`. Setting. |
| `--version` | `-V` | Print the version and which copy is running: its kind, the interpreter, the package path, and whether the clipboard extra is installed. |
| `--help` | `-h` | Show the help and exit. |

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

## Exit codes and streams

| Code | Meaning |
| :--- | :--- |
| `0` | Every image succeeded. |
| `1` | All images failed, or the arguments were invalid. |
| `2` | Some images failed. |

Headers, progress and errors go to stderr, so `lens_scan img.png > out.txt` holds only the text.

## Configuration

Precedence, highest first: **a flag given explicitly > the config file > a `LENS_*` environment variable > the default**. A flag you did not type never overrides the file.

The default config file is `config.json` in `$XDG_CONFIG_HOME/chrome-lens-py/`, or in `~/.config/chrome-lens-py/` if that variable is not set. This is the same rule on Linux, macOS and Windows (`C:\Users\<user>\.config\chrome-lens-py\config.json`). Use `--config-file` for another file.

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

Also accepted as config keys: the flag spellings `translate`, `font`, `outline`, `min_text_size`, `manga`, `manga_growth` and `no_env_proxy`. Booleans in environment variables take `1/0`, `true/false`, `yes/no`, `on/off`. An empty variable counts as unset. `--serve` reads the same settings.

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
