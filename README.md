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

## ✨ Key Features

-   **Modern Backend**: Utilizes Google's official Protobuf endpoint (`v1/crupload`) for robust and accurate results.
-   **Asynchronous & Safe**: Built with `asyncio` and `httpx`. Includes a built-in semaphore to prevent API abuse and IP bans from excessive concurrent requests.
-   **Powerful OCR & Segmentation**:
    -   Extract text from images as a single string.
    -   Get text segmented into logical blocks (paragraphs, dialog bubbles) with their own coordinates.
-   **Built-in Translation**: Instantly translate recognized text into any supported language.
-   **Versatile Image Sources**: Process images from a **file path**, **URL**, **bytes**, **PIL Image** object, or **NumPy array**.
-   **Text Overlay**: Automatically generate and save images with the translated text rendered over them(works poorly, alas, no time to do better).
-   **Feature-Rich CLI**: A simple yet powerful command-line interface (`lens_scan`) for quick use.
-   **Proxy Support**: Full support for HTTP, HTTPS, and SOCKS proxies.
-   **Clipboard Integration**: Instantly copy OCR or translation results to your clipboard with the `--sharex` flag.
-   **Flexible Configuration**: Manage settings via a `config.json` file, CLI arguments, or environment variables.

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
| `--output-blocks` | `-b` | **Output OCR text as segmented blocks** (useful for comics). Incompatible with `--get-coords`.|
| `--get-coords` | | Output recognized words and their coordinates in JSON format. Incompatible with `--output-blocks`. |
| `--sharex` | `-sx` | **Copy** the result (translation or OCR) to the clipboard. |
| `--ocr-single-line` | | Join all recognized OCR text into a single line, removing line breaks. |
| `--config-file <path>`| | Path to a custom JSON configuration file. |
| `--update-config` | | Update the default config file with settings from the current command. |
| `--font <path>` | | Path to a `.ttf` font file for the text overlay. |
| `--font-size <size>` | | Font size for the text overlay (default: 20). |
| `--proxy <url>` | | Proxy server URL (e.g., `socks5://127.0.0.1:9050`). |
| `--logging-level <lvl>`| `-l` | Set logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
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

  **3. Get Coordinates of All Individual Words**
  
  Outputs a detailed JSON array containing every single recognized word and its precise geometric data (center, size, angle). Useful for programmatic analysis or custom overlays.
  ```bash
  lens_scan "path/to/diagram.png" --get-coords
  ```
  
  ---

  **4. Translate, Save Overlay, and Copy to Clipboard**
  
  A power-user workflow. This command will:
  1. OCR a Japanese image.
  2. Translate it to Russian.
  3. Save a new image named `translated_manga.png` with the Russian text rendered on it.
  4. Copy the final translation to your clipboard.
  ```bash
  lens_scan "path/to/manga.jpg" ja -t ru -to "translated_manga.png" -sx
  ```

  ---

  **5. Process an Image from a URL as a Single Line**

  Fetches an image directly from a URL and joins all recognized text into one continuous line, removing any line breaks.
  ```bash
  lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
  ```

  ---

  **6. Use a SOCKS5 Proxy**
  
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
      max_concurrent: int = 5
  )
  ```

  #### **`process_image` Method**
  
  ```python
  result: dict = await api.process_image(
      image_path: Any,
      ocr_language: Optional[str] = None,
      target_translation_language: Optional[str] = None,
      source_translation_language: Optional[str] = None,
      output_overlay_path: Optional[str] = None,
      ocr_preserve_line_breaks: bool = True,
      output_format: Literal['full_text', 'blocks'] = 'full_text'
  )
  ```
  -   **`output_format`**: `'full_text'` (default) returns results in `ocr_text`. `'blocks'` returns a list of dictionaries in `text_blocks`.
  -   **`ocr_preserve_line_breaks`**: If `False` and `output_format` is `'full_text'`, joins all OCR text into a single line.

  **The returned `result` dictionary contains:**
  - `ocr_text` (Optional[str]): The full recognized text (if `output_format='full_text'`).
  - `text_blocks` (Optional[List[dict]]): A list of segmented text blocks (if `output_format='blocks'`). Each block is a dict with `text`, `lines`, and `geometry`.
  - `translated_text` (Optional[str]): The translated text, if requested.
  - `word_data` (List[dict]): A list of dictionaries for every recognized word with its geometry.
  - `raw_response_objects`: The "raw" Protobuf response object for further analysis.

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