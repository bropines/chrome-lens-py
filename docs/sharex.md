## Custom ShareX OCR with Google Lens

It's possible to use the `chrome-lens-py` package with ShareX to OCR images using the Google Lens API, providing a significant upgrade over the default OCR in ShareX.

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
