## Custom ShareX OCR with Google Lens

It's possible to use the `chrome-lens-py` package with ShareX to OCR images using the Google Lens API, providing a significant upgrade over the default OCR in ShareX.

## Two ways to wire it up

| | **Program mode** (default) | **Uploader mode** |
|---|---|---|
| what ShareX does per capture | runs `lens_scan` | posts the image to the daemon |
| processes started per capture | one (a thin client) | none |
| set up with | `lens_scan --setup-sharex` | `lens_scan --setup-sharex --mode uploader` and `lens_scan --install-service` |
| needs a daemon running | no - one starts by itself | yes, on a fixed port |
| result lands on the clipboard via | `lens_scan --sharex` | ShareX's "Copy URL to clipboard" |

**Program mode is already fast.** `lens_scan` hands each capture to a warm
background daemon (starting one after the first call), so a capture costs a few
hundred milliseconds instead of three seconds, with no extra setup. See
[Daemon / fast mode](../README.md#-daemon--fast-mode) in the README for how it works, how to
turn it off (`--daemon off`) and what it measures.

**Uploader mode** removes even that process: ShareX's *custom uploader* feature POSTs
the picture to the daemon and copies the text it answers with. Skip to
[Uploader mode](#uploader-mode-no-process-per-capture) below.

---

### 🚀 Recommended: Automated Setup (Windows)

The easiest way to set up ShareX is to use the built-in automation command.

1.  **Install the library** (if you haven't already):
    ```bash
    pip install "chrome-lens-py[clipboard]"
    ```
2.  **Run the setup command**:
    ```bash
    lens_scan --setup-sharex
    ```

**What this does:**
*   Locates your ShareX configuration.
*   Closes ShareX if it's running (a normal close first, so ShareX saves its own state; a forced kill only if it does not exit within a few seconds).
*   Copies `HotkeysConfig.json` to `HotkeysConfig.json.bak-<timestamp>` next to it. Nothing is changed before this copy exists.
*   Adds/updates a hotkey (**Ctrl + O**) that captures a region and sends it to Google Lens. The new file is written atomically, so a crash cannot leave a half-written config.
*   Restarts ShareX automatically.

If anything fails (for example the config is not valid JSON) the original file is left untouched.

**Translate instead of just OCR.** Pass a target language and the hotkey's action gets `-t <lang>`:
```bash
lens_scan --setup-sharex --translate ru     # same as -t ru
```
The action's arguments become `-t ru --sharex "$input"`. Run the command again with another language (or none) to change it; the existing `lens` action is updated in place. Language codes may contain only letters, digits, `-` and `_`.

**Other defaults** (proxy, timeout, region, `target_lang`, ...) do not need to be baked into the hotkey: `lens_scan` reads `config.json` and `LENS_*` environment variables on every run, so changing them later needs no ShareX re-setup. See the configuration table in the README.

**Exit status.** `--setup-sharex` exits `0` on success and `1` if it could not complete.

The action's arguments can include `--daemon off` if you would rather ShareX always ran `lens_scan` cold.

---

### Uploader mode (no process per capture)

```bash
lens_scan --setup-sharex --mode uploader          # add -t ru to translate
lens_scan --install-service                       # daemon at every login
```

1.  `--setup-sharex --mode uploader` writes `Google Lens OCR (chrome-lens-py).sxcu` into
    `Documents\ShareX\` (your ShareX folder, if it exists) and starts the persistent
    daemon. The file is a ShareX *custom uploader*:

    ```json
    {
      "Version": "15.0.0",
      "Name": "Google Lens OCR (chrome-lens-py)",
      "DestinationType": "ImageUploader",
      "RequestMethod": "POST",
      "RequestURL": "http://127.0.0.1:8765/v1/ocr/raw",
      "Parameters": { "translate_to": "ru" },
      "Headers": { "Authorization": "Bearer <your token>" },
      "Body": "Binary",
      "URL": "{response}",
      "ErrorMessage": "{json:error}"
    }
    ```

    ShareX sends the capture's bytes with its own `Content-Type` (`image/png`, ...);
    the daemon answers with the recognised text as `text/plain`, and `{response}` makes
    ShareX take that whole reply as the result. `Parameters` is present only with `-t`.
2.  **Double-click the `.sxcu` file.** ShareX asks whether to add the uploader and to
    use it for images - say yes.
3.  In ShareX, make sure *After capture tasks* has **Upload image to host** (that is
    what sends the picture) and *After upload tasks* has **Copy URL to clipboard** (that
    is what puts the text on the clipboard). Your OCR hotkey (for example *Capture
    region*) then needs nothing else.
4.  `--install-service` keeps the daemon running across logins: a shortcut in your
    Startup folder on Windows (macOS: a LaunchAgent, Linux: a `systemd --user` unit).
    Without it the uploader works while a daemon is up on that port: right after step 1,
    and again after any plain `lens_scan` run, which restarts the daemon in its persistent
    form for as long as the token file exists - but not after a reboot with no `lens_scan`
    call.

The port is `daemon_port` (default `8765`, `--port` to change it before running the
setup). The token is generated once and kept in `service.json` in the user data
directory, so restarts do not invalidate the uploader; **the `.sxcu` contains it, so do not
share the file.** If you ever need a new one, `--uninstall-service` forgets the token and
the next `--setup-sharex --mode uploader` makes a new `.sxcu`.

Why a web page cannot use this endpoint and why it needs the token: see
[What can reach it](../README.md#what-can-reach-it).

**Troubleshooting uploader mode.** The daemon's log is `daemon.log` in
`%LOCALAPPDATA%\chrome-lens-py\`. An error reply is JSON (`{"error": ...}`) and ShareX shows
its `error` text. `401` means the token in ShareX no longer matches the daemon's
(re-import the `.sxcu`); `415` means ShareX did not send an image `Content-Type`
(only `image/png`, `image/jpeg`, `image/webp` and `image/bmp` are accepted); a connection
error means no daemon is listening - run `lens_scan --daemon-status`.
You can test the same request without ShareX:

```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: image/png"      --data-binary @shot.png "http://127.0.0.1:8765/v1/ocr/raw?translate_to=ru"
```

---

### 🛠️ Manual Setup (Fallback)

If the automated setup fails or you want custom settings, follow these steps:

1.  **Install Python 3.10+** and ensure "Add Python to PATH" is checked.
2.  **Install the library**: `pip install "chrome-lens-py[clipboard]"`
3.  **Find the path** to the `lens_scan` executable:
    ```powershell
    (Get-Command lens_scan).Source
    ```
4.  **Configure ShareX Hotkey**:
    *   Open `Hotkey settings...` in ShareX.
    *   Create a new hotkey for `Screen capture` -> `Capture region (Light)`.
    *   Open its settings (gear icon) -> `Actions` tab -> check `Override actions`.
    *   **Add** a new action:
        *   **Name**: `Lens OCR`
        *   **File path**: (Paste the path from step 3)
        *   **Arguments**: `--sharex "$input"` (add `-t ru` in front to translate)
        *   Check `Hidden window`.

---

## Troubleshooting
If something went wrong with the automated setup, restore the previous configuration by closing ShareX and copying `Documents\ShareX\HotkeysConfig.json.bak-<timestamp>` over `HotkeysConfig.json`.

If the hotkey runs but nothing lands on the clipboard, `lens_scan` now exits non-zero and prints the reason to stderr; remove **"Hidden window"** to see it. The usual cause is a missing clipboard extra: `pip install "chrome-lens-py[clipboard]"`.

If it takes a long time to process and nothing is copied, try unchecking **"Hidden window"** in your ShareX action settings to see the error console. 

**Antivirus Warning**: some antivirus software distrusts unsigned compiled executables. The Windows installer detects a quarantined binary and installs the portable build instead, which runs the package through python.org's signed `python.exe`. You can also install with `uv tool install "chrome-lens-py[clipboard]"`.
