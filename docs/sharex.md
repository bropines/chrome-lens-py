## Custom ShareX OCR with Google Lens

It's possible to use the `chrome-lens-py` package with ShareX to OCR images using the Google Lens API, providing a significant upgrade over the default OCR in ShareX. Here's how to set it up:

0. Get [ShareX](https://getsharex.com/) if you don't have it already.
1. Install Python 3.10+ from the [Python Official website](https://www.python.org/downloads/) or via [Pyenv-WIN](https://github.com/pyenv-win/pyenv-win).
   **IMPORTANT:** During installation, you **must** check the "Add Python to PATH" option, otherwise this will not work.

2. Install the `chrome-lens-py` library with clipboard support:
   ```bash
   pip install "chrome-lens-py[clipboard]"
   ```
3. Find the path to the installed `lens_scan` executable. Run the following command in PowerShell:
   ```powershell
   (Get-Command lens_scan).Source
   ```
   You will get a path similar to this:
   ```
   C:\Users\bropi\.pyenv\pyenv-win\shims\lens_scan.bat
   ```

   Copy this path for the next steps.

4. Open the ShareX main window and navigate to `Hotkey settings...`. Create a new hotkey. For the task, select `Screen capture` -> `Capture region (Light)`.

5. Now, open the settings for that new hotkey (the gear icon).
   - Under the **Tasks** tab, ensure `Capture region (Light)` is selected.
   - Go to the **Actions** tab and check the `Override actions` box.
   - Click **Add...** and set up a new action with the following details:

   ![Screenshot of ShareX Action settings]()

   - **Name:** `Lens OCR` (or any name you prefer)
   - **File path:** Paste the path you copied in step 3. For example:
     - `C:\Users\bropi\.pyenv\pyenv-win\shims\lens_scan.bat`
   - **Arguments:** Enter `"$input" --sharex`
   - Uncheck `Hidden window` if you need to troubleshoot later. Otherwise, leaving it checked is fine.

6. Save the action. Back in the Hotkey settings, make sure your new `Lens OCR` action is checked in the list.

7. You can now close the settings windows. Use your new hotkey to capture a region of your screen. The image will be processed, and the recognized text will be automatically copied to your clipboard.

![GIF demonstrating the OCR process](https://lune.dimden.dev/1bf28abae5b0.gif)

## Troubleshooting
If it takes a long time to process the image and nothing gets copied to your clipboard, an error might be occurring in the script. To see the error, go back to your `Lens OCR` Action settings (step 5), uncheck the **"Hidden window"** option, and run the hotkey again. A console window will appear showing any error messages.

## Updating
To update the package to the latest version, simply run the following command in your terminal:
```bash
pip install --upgrade "chrome-lens-py[clipboard]"
```