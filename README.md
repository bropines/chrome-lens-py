# Chrome Lens API for Python

**English** | [Русский](/README_RU.md)

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

> [!IMPORTANT]
> **Major Rewrite (Version 3.1.0+)**
> This library has been completely rewritten from the ground up. It now uses a modern asynchronous architecture (`async`/`await`) and communicates directly with Google's Protobuf endpoint for significantly improved reliability and performance.
>
> **Please update your projects accordingly. All API calls are now `async`.**
>

> [!Warning]
> Also, please note that the library has been completely rewritten, and I could have missed something, or not spelled it out. If you notice an error, please let me know in Issues

This project provides a powerful, asynchronous Python library and command-line tool for interacting with Google Lens. It allows you to perform advanced Optical Character Recognition (OCR), get segmented text blocks (e.g., for comics), translate text, and get precise word coordinates.

## 🚀 Quick Start for Windows Users

If you don't want to install Python, you can download the standalone **lens_scan-windows-amd64.exe** from the [Releases](https://github.com/bropines/chrome-lens-py/releases) section.

> [!NOTE]
> **About the antivirus warnings.** Earlier releases shipped a single-file
> binary, which unpacks an executable payload into `%TEMP%` and runs it on every
> launch. That is packer behaviour, and it is what Defender's ML heuristic
> reacted to with `Trojan:Win32/Wacatac.H!ml` - a verdict on *behaviour*, not a
> signature, which is why it fired on user machines while a local scan came back
> clean. The builds are now a plain folder that does none of that. If you would
> rather avoid a binary entirely, `uv tool install` below installs the real
> Python package and has nothing for a heuristic to object to.

### 📸 Automated ShareX Setup
If you use **ShareX**, you can fully automate the setup with one command:
```bash
# Using the installed package:
lens_scan --setup-sharex

# Or using the standalone .exe:
lens_scan-windows-amd64.exe --setup-sharex
```
This will automatically configure a hotkey (**Ctrl + O**) and the necessary actions to use Google Lens OCR.

---

## ✨ Key Features

-   **Modern Backend**: Utilizes Google's official Protobuf endpoint (`v1/crupload`) for robust and accurate results.
-   **Asynchronous & Safe**: Built with `asyncio` and `httpx`. Includes a built-in semaphore to prevent API abuse and IP bans from excessive concurrent requests.
-   **Powerful OCR & Segmentation**:
    -   Extract text from images as a single string.
    -   Get text segmented into logical blocks (paragraphs, dialog bubbles) with their own coordinates.
    -   Get individual text lines with their own precise geometry.
-   **Built-in Translation**: Instantly translate recognized text into any supported language.
-   **Versatile Image Sources**: Process images from a **file path**, **URL**, **bytes**, **PIL Image** object, or **NumPy array**.
-   **Chromium-Accurate Text Overlay**: Repaints translated text in place the way Chrome's own Lens overlay does — erasing the source with the server's inpainted background patch, then drawing the translation in the original colours, angle and line box. Handles right-to-left scripts, vertical CJK, and per-character font fallback.
-   **Region Queries**: Re-read one region of an image at native resolution (`process_region`), which reads small print far better than the full-image pass.
-   **Local Daemon**: `lens_scan --serve` keeps a warm process so callers skip the ~1.2 s interpreter start on every invocation. Doubles as a backend for browser userscripts.
-   **Feature-Rich CLI**: A simple yet powerful command-line interface (`lens_scan`) for quick use.
-   **Proxy Support**: Full support for HTTP, HTTPS, and SOCKS proxies, plus `--no-env-proxy` when you want to bypass the proxy your environment sets.
-   **Clipboard Integration**: Instantly copy OCR or translation results to your clipboard with the `--sharex` flag.
-   **Flexible Configuration**: Manage settings via a `config.json` file, CLI arguments, or environment variables.

## 📦 Which install to pick

| | startup | download | notes |
|---|---|---|---|
| **`uv tool install`** | 488 ms | ~10 MB | no binary at all, so nothing for antivirus heuristics to flag; updates with one command |
| **standalone zip** | **202 ms** | 25 MB | no Python needed; a folder, not a single file |
| ~~onefile `.exe`~~ | 1782 ms | 18 MB | no longer built: self-extracts on every run, which is both the antivirus trigger and the startup cost |

Measured on the same machine, `--help` only, median of six runs.

The standalone build starts fastest of the three because Nuitka has compiled the
imports away; the one-file variant lost to both by unpacking itself first.

Four ways in, differing in what they need from you:

| | needs Python? | how | update with |
|---|---|---|---|
| **Homebrew** (macOS, Linux) | no | `brew install bropines/tap/lens-scan` | `brew upgrade lens-scan` |
| **uv** | no — uv fetches one | `install-uv.ps1` / `install-uv.sh` | `uv tool upgrade chrome-lens-py` |
| **standalone zip** | no | `install.ps1` / `install.sh` | re-run the installer |
| **pip** | yes, your own | `pip install chrome-lens-py` | `pip install -U chrome-lens-py` |

```bash
brew install bropines/tap/lens-scan           # macOS / Linux
uv tool install "chrome-lens-py[clipboard]"   # or: pipx install chrome-lens-py
pip install chrome-lens-py                    # if you manage Python yourself
```

### Homebrew

That is one command, not two: `brew` taps
[bropines/homebrew-tap](https://github.com/bropines/homebrew-tap) on the way
past. It installs the prebuilt standalone folder, so it does not care which
Python you have, and the formula is bumped automatically on every release.

Published builds cover Apple Silicon and x86_64 Linux. On an Intel Mac or ARM
Linux the formula stops and points you at uv, rather than failing to download
something that was never built.

### One-line install with uv

Installs uv if you do not have it, then installs `lens_scan` as a uv tool and
puts it on PATH. Nothing is frozen into an executable, so there is nothing for
antivirus heuristics to react to, and no Python is needed beforehand — uv
brings its own.

```powershell
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh | sh
```

Installs the `[clipboard]` extra too, so `--sharex` works out of the box.

```bash
uv tool upgrade chrome-lens-py      # later
uv tool uninstall chrome-lens-py
```

> **If another `lens_scan` is already on your PATH** — a pip install behind a
> pyenv shim, say, or an older standalone build — that one may come first and
> keep winning after this install. The installer warns you when it spots this.
> `lens_scan --version` prints the path it actually ran from, which settles it.

### One-line install of the standalone build

Downloads the latest release, verifies its SHA-256, unpacks it, puts `lens_scan`
on your PATH, and checks it starts before declaring victory.

```powershell
# Windows
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | sh
```

Installs to `%LOCALAPPDATA%\Programs\lens-scan` or `~/.local/share/lens-scan`;
re-running replaces the existing install. Both scripts refuse to install a
pre-standalone release rather than quietly handing you the self-extracting build
that caused the antivirus reports.

Every release publishes a `.sha256` next to each archive, and the installers
check it before unpacking. Verify one by hand with:

```bash
sha256sum -c lens_scan-linux-amd64.zip.sha256
```

Be clear about what that buys: it catches a corrupted or truncated download and
a CDN serving something other than what was uploaded. It is not a signature —
anyone able to rewrite the release could rewrite the checksum with it.

Not sure which copy you are running? `lens_scan --version` prints the version
along with the path it was loaded from, which settles the usual confusion
between a pip install, a `uv tool` install, an editable checkout and a
standalone build all owning the same name.

## 🚀 Installation

You can install the package using `pip`:

```bash
pip install chrome-lens-py
```

To enable clipboard functionality (the `--sharex` flag), install the library with the `[clipboard]` extra:

```bash
pip install "chrome-lens-py[clipboard]"
```

Or, install the latest version directly from GitHub:
```bash
pip install git+https://github.com/bropines/chrome-lens-py.git
```

## 🚀 Usage

<details>
  <summary><b>🛠️ CLI Usage (`lens_scan`)</b></summary>

  The command-line tool provides quick access to the library's features directly from your terminal.

  ```bash
  lens_scan <image_source> [ocr_lang] [options]
  ```

  -   **`<image_source>`**: Path to a local image file or an image URL.
  -   **`[ocr_lang]`** (optional): BCP 47 language code for OCR (e.g., 'en', 'ja'). If omitted, the API will attempt to auto-detect the language.

  #### **Options**

| Flag | Alias | Description |
| :--- | :--- | :--- |
| `--translate <lang>` | `-t` | **Translate** the OCR text to the target language code (e.g., `en`, `ru`). |
| `--translate-from <lang>` | | Specify the source language for translation (otherwise auto-detected). |
| `--translate-out <path>` | `-to` | **Save** the image with the translated text overlaid to the specified file path. |
| `--output-blocks` | `-b` | **Output OCR text as segmented blocks** (useful for comics). Incompatible with `--get-coords` and `--output-lines`.|
| `--output-lines` | `-ol` | **Output OCR text as individual lines** with their geometry. Incompatible with `--output-blocks` and `--get-coords`.|
| `--get-coords` | | Output recognized words and their coordinates in JSON format. Incompatible with `--output-blocks` and `--output-lines`. |
| `--sharex` | `-sx` | **Copy** the result (translation or OCR) to the clipboard. |
| `--ocr-single-line` | | Join all recognized OCR text into a single line, removing line breaks. |
| `--config-file <path>`| | Path to a custom JSON configuration file. |
| `--update-config` | | Update the default config file with settings from the current command. |
| `--font <path>` | | Path to a `.ttf` font file for the text overlay. |
| `--font-size <size>` | | Font size for the text overlay (default: 20). |
| `--proxy <url>` | | Proxy server URL (e.g., `socks5://127.0.0.1:9050`). |
| `--no-env-proxy` | | Ignore `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` and connect directly. |
| `--concurrency <N>` | | Maximum concurrent requests (default 5, hard limit 30). |
| `--timeout <sec>` | | Request timeout in seconds (default 60). |
| `--overlay-mode <mode>`| | `chromium` (default) or `legacy`, the old white-box overlay. |
| `--vertical-text <mode>`| | Vertical CJK source: `auto`, `keep` or `horizontal`. |
| `--erase-mode <mode>` | | `patch` (server inpaint) or `hull` (cover the whole area). |
| `--hull-padding <N>` | | How far the hull reaches past the text, in line heights. |
| `--outline <N>` | | Multiplier on the outline behind translated text; `0` removes it. |
| `--min-text-size <px>` | | Floor on rendered text size, for readability. |
| `--text-align <side>` | | `auto`, `left`, `center` or `right`. |
| `--manga` | | Preset for vertical Japanese pages (see the rendering section). |
| `--manga-growth <N>` | | How much wider than the detected box to lay out in manga mode. |
| `--region <cx,cy,w,h>` | | Re-read one region at native resolution (normalized 0..1). |
| `--text-query <text>` | | Text to send alongside `--region`. |
| `--serve` | | Run as a local HTTP daemon instead of processing one image. |
| `--host <addr>` | | Address for the daemon (default `127.0.0.1`). |
| `--port <N>` | | Port for the daemon (default `8765`). |
| `--token <token>` | | Require a bearer token. Mandatory when `--host` is not loopback. |
| `--allow-origin <origin>`| | Let one browser origin call the daemon (repeatable). None by default. |
| `--setup-sharex` | | Wire `lens_scan` into ShareX automatically. |
| `--logging-level <lvl>`| `-l` | Set logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--version` | `-V` | Show the version and which copy of it is running. |
| `--help` | `-h` | Show this help message and exit. |

  #### **Examples**

  **1. Basic OCR and Translation**
  
  Auto-detects the source language on the image and translates it to English. This is the most common use case.
  ```bash
  lens_scan "path/to/your/image.png" -t en
  ```

  ---
  
  **2. Get Segmented Text Blocks (for Comics/Manga)**

  Ideal for images with multiple, separate text boxes. This command outputs each recognized text block individually, making it perfect for translating comics or complex documents.
  ```bash
  lens_scan "path/to/manga.jpg" ja -b
  ```
  - `-b` is the alias for `--output-blocks`.

  ---
  
  **3. Get Individual Text Lines**
  
  Outputs each recognized line of text along with its geometry.
  ```bash
  lens_scan "path/to/document.png" --output-lines
  ```
  - `-ol` is the alias for `--output-lines`.

  ---

  **4. Get Coordinates of All Individual Words**
  
  Outputs a detailed JSON array containing every single recognized word and its precise geometric data (center, size, angle). Useful for programmatic analysis or custom overlays.
  ```bash
  lens_scan "path/to/diagram.png" --get-coords
  ```
  
  ---

  **5. Translate, Save Overlay, and Copy to Clipboard**
  
  A power-user workflow. This command will:
  1. OCR a Japanese image.
  2. Translate it to Russian.
  3. Save a new image named `translated_manga.png` with the Russian text rendered on it.
  4. Copy the final translation to your clipboard.
  ```bash
  lens_scan "path/to/manga.jpg" ja -t ru -to "translated_manga.png" -sx
  ```

  ---

  **6. Process an Image from a URL as a Single Line**

  Fetches an image directly from a URL and joins all recognized text into one continuous line, removing any line breaks.
  ```bash
  lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
  ```

  ---

  **7. Use a SOCKS5 Proxy**
  
  All requests to the Google API will be routed through the specified proxy server, which is useful for privacy or bypassing region restrictions.
  ```bash
  lens_scan "image.png" --proxy "socks5://127.0.0.1:9050"
  ```

</details>

<details>
  <summary><b>👨‍💻 Programmatic API Usage (`LensAPI`)</b></summary>
  
  > [!IMPORTANT]
  > The `LensAPI` is fully **asynchronous**. All data retrieval methods must be called with `await` from within an `async` function.

  #### **Basic Example (Full Text)**
  
  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def main():
      # Initialize the API. You can pass a proxy, region, etc. here.
      # By default, an API key is not required.
      api = LensAPI()

      image_source = "path/to/your/image.png" # Or a URL, PIL Image, NumPy array

      try:
          # Process the image and get a single string of text
          result = await api.process_image(
              image_path=image_source,
              ocr_language="ja",
              target_translation_language="en"
          )

          print("--- OCR Text ---")
          print(result.get("ocr_text"))

          print("\n--- Translated Text ---")
          print(result.get("translated_text"))
          
      except Exception as e:
          print(f"An error occurred: {e}")

  if __name__ == "__main__":
      asyncio.run(main())
  ```
  
  #### **Working with Different Image Sources**

  The `process_image` method seamlessly handles various input types.

  ```python
  from PIL import Image
  import numpy as np

  # ... inside an async function ...
  
  # From a URL
  result_url = await api.process_image("https://i.imgur.com/VPd1y6b.png")

  # From a PIL Image object
  with Image.open("path/to/image.png") as img:
      result_pil = await api.process_image(img)

  # From a NumPy array (e.g., loaded via OpenCV)
  with Image.open("path/to/image.png") as img:
      numpy_array = np.array(img)
      result_numpy = await api.process_image(numpy_array)
  ```

  #### **Getting Segmented Text Blocks**

  To get text segmented into logical blocks (like dialog bubbles in a comic), use the `output_format='blocks'` parameter.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_comics():
      api = LensAPI()
      image_source = "path/to/manga.jpg"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='blocks' # Get segmented blocks instead of a single string
      )

      # The result now contains a 'text_blocks' key
      text_blocks = result.get("text_blocks", [])
      print(f"Found {len(text_blocks)} text blocks.")

      for i, block in enumerate(text_blocks):
          print(f"\n--- Block #{i+1} ---")
          print(block['text'])
          # block also contains 'lines' and 'geometry' keys
  
  asyncio.run(process_comics())
  ```

  #### **Getting Individual Lines and their Geometry**

  To get each recognized line of text as a separate item, use the `output_format='lines'` parameter.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_document_lines():
      api = LensAPI()
      image_source = "path/to/document.png"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='lines' # Get individual lines with their geometry
      )

      # The result now contains a 'line_blocks' key
      line_blocks = result.get("line_blocks", [])
      print(f"Found {len(line_blocks)} lines.")

      for i, line in enumerate(line_blocks):
          print(f"\n--- Line #{i+1} ---")
          print(f"Text: {line['text']}")
          print(f"Geometry: {line['geometry']}")
  
  asyncio.run(process_document_lines())
  ```

  #### **Getting Fully Detailed Text Structures**

To get a complete, nested structure of paragraphs, lines, and words with geometry at each level, use `output_format='detailed'`.

```python
import asyncio
from chrome_lens_py import LensAPI

async def process_with_details():
    api = LensAPI()
    image_source = "path/to/document.png"
    
    result = await api.process_image(
        image_path=image_source,
        output_format='detailed' # Get the fully nested structure
    )

    # The result now contains a 'detailed_blocks' key
    detailed_blocks = result.get("detailed_blocks", [])
    print(f"Found {len(detailed_blocks)} detailed blocks.")

    for i, block in enumerate(detailed_blocks):
        print(f"\n--- Block #{i+1} ---")
        print(f"  Geometry: {block['geometry']}")
        for j, line in enumerate(block['lines']):
            print(f"    --- Line #{j+1}: '{line['text']}' ---")
            for k, word in enumerate(line['words']):
                 print(f"      - Word: '{word['text']}', Geometry: {word['geometry']}")

asyncio.run(process_with_details())
```


  #### **`LensAPI` Constructor**

  ```python
  api = LensAPI(
      api_key: str = "YOUR_API_KEY_OR_DEFAULT",
      client_region: Optional[str] = None,
      client_time_zone: Optional[str] = None,
      proxy: Optional[str] = None,
      timeout: int = 60,
      font_path: Optional[str] = None,
      font_size: Optional[int] = None,
      max_concurrent: int = 5,
      trust_env: bool = True,
  )
  ```
  -   **`trust_env`**: Whether to honour `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` from the environment. Set `False` if a stale proxy variable is making requests hang — that was the cause of the "it only works with a proxy on" reports.

  `LensAPI` is an async context manager, and closing it returns the pooled
  connections:

  ```python
  async with LensAPI() as api:
      ...
  # or: api = LensAPI(); ...; await api.aclose()
  ```

  #### **`process_image` Method**

  ```python
  result: dict = await api.process_image(
      image_path: Any,
      ocr_language: Optional[str] = None,
      target_translation_language: Optional[str] = None,
      source_translation_language: Optional[str] = None,
      output_overlay_path: Optional[str] = None,
      new_session: bool = True,
      ocr_preserve_line_breaks: bool = True,
      output_format: Literal['full_text', 'blocks', 'lines', 'detailed'] = 'full_text',
      # overlay rendering; see the rendering section for what each one is for
      overlay_mode: Literal['chromium', 'legacy'] = 'chromium',
      vertical_text: Literal['keep', 'auto', 'horizontal'] = 'auto',
      erase_mode: Literal['patch', 'hull'] = 'patch',
      hull_padding: float = 0.45,
      outline_scale: float = 1.0,
      min_readable_px: float = 0.0,
      text_align: Literal['auto', 'left', 'center', 'right'] = 'auto',
      manga_mode: bool = False,
      manga_box_growth: float = 1.45,
      include_raw_response: bool = False,
  )
  ```
  -   **`output_format`**: Controls the structure of the OCR output. `'full_text'` (default) returns a single string in `ocr_text`. `'blocks'` returns a list in `text_blocks`. `'lines'` returns a list in `line_blocks`. `'detailed'` returns a fully nested structure in `detailed_blocks`.
  -   **`ocr_preserve_line_breaks`**: If `False` and `output_format` is `'full_text'`, joins all OCR text into a single line.
  -   **`include_raw_response`**: Off by default. The raw protobuf objects are large and not serializable, so they are only attached when you ask.
  -   The rendering parameters only matter when `output_overlay_path` is set. Each one has a CLI flag of the same name — see [Overlay rendering](#-overlay-rendering).

  **The returned `result` dictionary contains:**
  - `ocr_text` (Optional[str]): The full recognized text (if `output_format='full_text'`).
  - `text_blocks` (Optional[List[dict]]): A list of segmented text blocks (if `output_format='blocks'`). Each block is a dict with `text`, `lines`, and `geometry`.
  - `line_blocks` (Optional[List[dict]]): A list of individual text lines (if `output_format='lines'`). Each block is a dict with `text` and `geometry`.
  - `translated_text` (Optional[str]): The translated text, if requested.
  - `word_data` (List[dict]): A list of dictionaries for every recognized word with its geometry.
  - `detailed_blocks` (Optional[List[dict]]): A list of fully structured text blocks (if `output_format='detailed'`). Each block contains lines, which in turn contain words, with geometry at every level.
  - `raw_response_objects`: The "raw" Protobuf response object — **only when `include_raw_response=True`**.

  #### **`process_region` Method**

  ```python
  result: dict = await api.process_region(
      image_path: Any,
      region: Tuple[float, float, float, float],   # center_x, center_y, w, h
      ocr_language: Optional[str] = None,
      text_query: Optional[str] = None,
      ocr_preserve_line_breaks: bool = True,
  )
  ```
  Re-reads one region at native resolution. See [Region queries](#-region-queries).

</details>

<details>
  <summary><b>⚙️ Configuration</b></summary>
  
  Settings are loaded with the following priority: **CLI Arguments > `config.json` File > Library Defaults**.
  
  #### **`config.json`**
  
  A `config.json` file can be placed in your system's default config directory to set persistent options.
  -   **Linux**: `~/.config/chrome-lens-py/config.json`
  -   **macOS**: `~/Library/Application Support/chrome-lens-py/config.json`
  -   **Windows**: `C:\Users\<user>\.config\chrome-lens-py\config.json`

  ##### **Example `config.json`**
  ```json
  {
    "api_key": "OPTIONAL! If you don't know what this is, I don't recommend setting it here.",
    "proxy": "socks5://127.0.0.1:9050",
    "client_region": "DE",
    "client_time_zone": "Europe/Berlin",
    "timeout": 90,
    "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "ocr_preserve_line_breaks": true
  }
  ```

</details>

## 🖥️ Daemon mode

Importing Pillow, protobuf and httpx costs roughly a second. If something calls
`lens_scan` repeatedly — ShareX on every screenshot, say — run it as a daemon and
pay that once:

```bash
lens_scan --serve                      # http://127.0.0.1:8765
lens_scan --serve --port 9000 --token secret
```

| route | body |
|---|---|
| `POST /v1/ocr` | `{"image": "<path or URL>"}` or `{"image_b64": "..."}`, plus any of `translate_to`, `translate_from`, `ocr_language`, `ocr_preserve_line_breaks`, `output_format`, `overlay_path`, `overlay_mode`, `vertical_text`, `erase_mode`, `hull_padding`, `outline_scale`, `min_readable_px`, `text_align`, `manga_mode`, `manga_box_growth` |
| `POST /v1/region` | the same source, plus `"region": [center_x, center_y, width, height]` normalized 0..1, and optionally `text_query` |
| `GET /health` | liveness check; reports the version |

Every rendering option the CLI has is accepted here under the same name, so
`--erase-mode hull --outline 3` on the command line is `"erase_mode": "hull",
"outline_scale": 3` in the body. Requests must be `Content-Type:
application/json`.

### What can reach it

This daemon holds an API key and will call Google for anyone who reaches it, so
the defaults are deliberately closed:

- **No web page can use it.** A request carrying an `Origin` header is refused
  unless you named that origin with `--allow-origin`. The check is on the
  *request*, not the response, because a page can send a POST it is forbidden to
  read and still get the side effect it wanted — a Google call billed to your
  key, or a file opened off your disk.
- **`--host` anywhere but loopback requires `--token`**, and then the daemon
  accepts only `image_b64`. A path or a URL is something it would go and open
  itself, which on a network listener means reading your disk, or fetching a
  host of the caller's choosing.
- Tokens are compared in constant time.

```bash
# let one page you control use it
lens_scan --serve --allow-origin https://yoursite.example

# on the network: token required, pixels only
lens_scan --serve --host 0.0.0.0 --token "$(openssl rand -hex 24)"
```

The Tampermonkey userscript does **not** need any of this — it talks to Google
directly through `GM_xmlhttpRequest`, which is not subject to CORS. Opening the
daemon to a browser origin is only for pages you write yourself.

Measured here, same work each time:

| | median |
|---|---|
| daemon | **0.37 s** |
| `python -m`, from source | 1.53 s |
| Nuitka onefile binary | 2.00 s |

The binary being the slowest is not a typo. Onefile extracts its payload to a
temporary directory on every run, which costs more than importing the modules
did: startup alone is 1.67 s against 0.52 s from source. Freezing is for
distribution, not for speed - if startup is what you care about, the daemon is
the answer, and `--standalone` rather than `--onefile` would at least stop the
binary making it worse.

## 🔍 Region queries

The full-image pass downscales anything over 1600px, which is exactly when small
print suffers. A region query sends only the cropped pixels, at native scale:

```python
async with LensAPI() as api:
    # (center_x, center_y, width, height), normalized against the full image
    result = await api.process_region("page.png", (0.8, 0.82, 0.35, 0.06))
    print(result["ocr_text"])
```

```bash
lens_scan page.png --region 0.8,0.82,0.35,0.06
lens_scan page.png --region 0.8,0.82,0.35,0.06 --text-query "what does this say"
```

Geometry comes back in full-image coordinates, so it lines up with
`process_image` output directly.

## 🎨 Overlay rendering

```bash
lens_scan manga.png -t ru -to out.png                      # Chromium-style, default
lens_scan manga.png -t ru -to out.png --vertical-text horizontal
lens_scan page.png  -t ru -to out.png --overlay-mode legacy
```

`--vertical-text` controls what happens to top-to-bottom CJK source text:

| value | behaviour |
|---|---|
| `auto` (default) | stays vertical only when translating into a CJK language |
| `keep` | always vertical, exactly like Chromium |
| `horizontal` | reflows the paragraph into horizontal wrapped lines |

### Making the result readable

Chromium repaints each line into the box the original occupied. That is right
for a street sign and wrong for a manga bubble, where the translation is far
longer than the Japanese it replaces. These knobs exist for that gap:

| flag | API parameter | what it does |
|---|---|---|
| `--erase-mode patch\|hull` | `erase_mode` | `patch` uses the server's inpainted background, like Chromium. `hull` wraps the text area in a convex hull and fills it with the surrounding colour — cleaner, but only where that colour is flat. |
| `--hull-padding N` | `hull_padding` | How far past the text the hull reaches, in fractions of line height (default `0.45`). |
| `--outline N` | `outline_scale` | Multiplier on the outline drawn behind translated text; `0` removes it. Drawn with a real stroke, so it stays clean up to `8`. |
| `--min-text-size PX` | `min_readable_px` | Floor on rendered text size. Enlarging the text does *not* enlarge the erased area — that is measured from the text as actually drawn. |
| `--text-align auto\|left\|center\|right` | `text_align` | `auto` follows the source line. |
| `--manga` | `manga_mode` | Preset for pages of vertical Japanese: always reflow, lay out wider than the detected box, erase by hull, bigger minimum size. |
| `--manga-growth N` | `manga_box_growth` | How much wider than the detected box to lay out in manga mode (default `1.45`). |

```bash
lens_scan page.png -t en -to out.png --manga
lens_scan page.png -t en -to out.png --erase-mode hull --outline 3 --min-text-size 18
```

Right-to-left targets (Arabic, Hebrew, Persian…) need shaping that Pillow's
published wheels cannot do, since they are built without libraqm:

```bash
pip install "chrome-lens-py[rtl]"      # python-bidi + arabic-reshaper
pip install "chrome-lens-py[fonts]"    # fontTools, for per-character font fallback
```

Without the `fonts` extra the renderer still works, but a font lacking glyphs for
the target script will draw tofu boxes.

## Sharex Integration
Check [sharex.md](docs/sharex.md) for more information on how to use this library with ShareX.

## ❤️ Support & Acknowledgments

-   **OWOCR**: Greatly inspired by and based on [OWOCR](https://github.com/AuroraWright/owocr). Thank you to them for their research into Protobuf and OCR implementation.
-   **Chrome Lens OCR**: For the original implementation and ideas that formed the basis of this library. The update with SHAREX support was originally tested and added by me to [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr), thanks for the initial implementation and ideas.
-   **AI Collaboration**: A significant portion of the v3.0 code, including the architectural refactor, asynchronous implementation, and Protobuf integration, was developed in collaboration with an advanced AI assistant.
-   **GOOGLE**: For the convenient and high-quality Lens technology.
-   **Support the Author**: If you find this library useful, you can support the author - **[Boosty](https://boosty.to/pinus)**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bropines/chrome-lens-py&type=Date)](https://www.star-history.com/#bropines/chrome-lens-py&Date)

### Disclaimer

This project is intended for educational and experimental purposes only. Use of Google's services must comply with their Terms of Service. The author is not responsible for any misuse of this software.