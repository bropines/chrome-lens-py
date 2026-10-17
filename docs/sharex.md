## Custom ShareX OCR with Google Lens

It's possible to use the `chrome-lens-py` package with ShareX to OCR images using the Google Lens API, providing a significant upgrade over the default OCR in ShareX.

## Two hotkeys, and why you want both

```bash
lens_scan --setup-sharex --mode both          # add -t ru to translate
```

| | **Ctrl + O** - program mode | **Ctrl + Shift + O** - uploader mode |
|---|---|---|
| what ShareX does per capture | runs `lens_scan` | posts the image to the daemon |
| processes started per capture | one (a thin client) | none |
| if the daemon is down | still works: runs the request itself, then restarts the daemon | fails until the daemon is back |
| set up with | `--mode program` (the default) | `--mode uploader` |

`--mode both` installs both, which is the point: **Ctrl + Shift + O** is the fastest
path, **Ctrl + O** is the one that always works. Uploader and both modes also install
the daemon as a login service, supervised so that a crash is restarted (below).

**Program mode is already fast.** `lens_scan` hands each capture to a warm background
daemon (starting one after the first call), so a capture costs a few hundred
milliseconds instead of three seconds, with no extra setup. See
[Daemon / fast mode](../README.md#-daemon--fast-mode) in the README for how it works,
how to turn it off (`--daemon off`) and what it measures.

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
lens_scan --setup-sharex --mode uploader          # or --mode both; add -t ru to translate
```

What it does, in order:

1.  **Installs the daemon as a login service** on a fixed port (`daemon_port`, default
    `8765`; `--port` to change it) with a token that survives restarts
    (`service.json` in the user data directory).
    *   **Windows**: a Startup-folder shortcut runs a small **supervisor** that keeps
        the daemon alive: if the daemon crashes, it is restarted after 1 s, then 2,
        4, ... up to 60 s while it keeps crashing, back to 1 s once it has run for a
        minute. A deliberate stop (`--daemon-stop`, `--uninstall-service`) exits with
        code 0 and ends the supervisor too. No console window: `pythonw.exe` for a
        Python install, `conhost.exe --headless` for the compiled `lens_scan.exe`.
    *   **macOS**: a LaunchAgent with `KeepAlive`. **Linux**: a `systemd --user` unit
        with `Restart=on-failure`.
2.  **Registers a custom uploader** directly in ShareX's `UploadersConfig.json`,
    named *Google Lens OCR (chrome-lens-py)*. It POSTs the capture's bytes to
    `http://127.0.0.1:<port>/v1/ocr/raw` with the token, and takes the daemon's
    `text/plain` reply as the result.
3.  **Adds Ctrl + Shift + O**: capture a region, upload it with *that* uploader, copy
    the result. The hotkey selects the uploader itself (ShareX's per-task
    *Override custom uploader*), so **your normal image destination is not touched**:
    screenshots you upload elsewhere still go wherever they went before.

Both ShareX files are backed up (`*.bak-<timestamp>`) and written atomically, with ShareX
closed. Running the setup again refreshes the port, token and language in place.
If Ctrl + Shift + O is already bound to something else, the setup says so.

**Always on.** The service starts at login and is never stopped for being idle. For
the auto daemon that program mode starts, idle exit is 10 minutes by default:
`daemon_idle_timeout: 0` in `config.json` (or `LENS_DAEMON_IDLE_TIMEOUT=0`) keeps it
until reboot.

Why a web page cannot use this endpoint and why it needs the token: see
[What can reach it](../README.md#what-can-reach-it).

**Troubleshooting uploader mode.** The daemon logs to `daemon.log`, the Windows
supervisor (crashes and restarts) to `supervisor.log`, both in
`%LOCALAPPDATA%\chrome-lens-py\`. An error reply is JSON
(`{"error": ...}`) and ShareX shows its `error` text. `401` means the token no longer
matches (run the setup again); `415` means ShareX did not send an image `Content-Type`; a
connection error means no daemon is listening - `lens_scan --daemon-status`, and meanwhile
**Ctrl + O** still works. You can test the same request without ShareX:

```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: image/png" --data-binary @shot.png "http://127.0.0.1:8765/v1/ocr/raw?translate_to=ru"
```

`--uninstall-service` removes the login item and forgets the token; the ShareX uploader
then needs the setup run again.

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
If something went wrong with the automated setup, restore the previous configuration by closing ShareX and copying `Documents\ShareX\HotkeysConfig.json.bak-<timestamp>` (and `UploadersConfig.json.bak-<timestamp>`, for uploader mode) over the originals.

If the hotkey runs but nothing lands on the clipboard, `lens_scan` now exits non-zero and prints the reason to stderr; remove **"Hidden window"** to see it. The usual cause is a missing clipboard extra: `pip install "chrome-lens-py[clipboard]"`.

If it takes a long time to process and nothing is copied, try unchecking **"Hidden window"** in your ShareX action settings to see the error console. 

**Antivirus Warning**: some antivirus software distrusts unsigned compiled executables. The Windows installer detects a quarantined binary and installs the portable build instead, which runs the package through python.org's signed `python.exe`. You can also install with `uv tool install "chrome-lens-py[clipboard]"`.
