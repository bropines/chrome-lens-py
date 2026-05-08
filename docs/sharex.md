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
    *Note: If you are using the standalone `.exe` from the GitHub Releases, run `lens_scan-windows-amd64.exe --setup-sharex` instead.*

**What this does:**
*   Locates your ShareX configuration.
*   Closes ShareX if it's running.
*   Adds/updates a hotkey (**Ctrl + O**) that captures a region and sends it to Google Lens.
*   Restarts ShareX automatically.

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
        *   **Arguments**: `"$input" --sharex`
        *   Check `Hidden window`.

---

## Troubleshooting
If it takes a long time to process and nothing is copied, try unchecking **"Hidden window"** in your ShareX action settings to see the error console. 

**Antivirus Warning**: Some antivirus software may flag the standalone `.exe` as a threat. This is a false positive common with compiled Python binaries. If this happens, add an exclusion or use the Python version via `pip`.
