# Chrome Lens API for Python

**English** | [Русский](/README_RU.md)

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

> [!IMPORTANT]
> **Major Rewrite (Version 3.0.0+)**
> This library has been completely rewritten from the ground up. It now uses a modern asynchronous architecture (`async`/`await`) and communicates directly with Google's Protobuf endpoint for significantly improved reliability and performance.
>
> **Please update your projects accordingly. All API calls are now `async`.**
>

> [!Warning]
> Also, please note that the library has been completely rewritten, and I could have missed something, or not spelled it out. If you notice an error, please let me know in Issues

This project provides a powerful, asynchronous Python library and command-line tool for interacting with Google Lens. It allows you to perform advanced Optical Character Recognition (OCR), translate text on images, and get precise coordinates for recognized words.

## ✨ Key Features

-   **Modern Backend**: Utilizes Google's official Protobuf endpoint (`v1/crupload`) for robust and accurate results.
-   **Asynchronous Core**: Built with `asyncio` and `httpx` for high-performance, non-blocking operations.
-   **Powerful OCR**: Extracts text from images, with options to preserve line breaks or get a single, continuous string.
-   **Built-in Translation**: Instantly translate recognized text into any supported language.
-   **Versatile Image Sources**: Process images from a **file path**, **URL**, **bytes**, **PIL Image** object, or **NumPy array**.
-   **Text Overlay**: Automatically generate and save images with the translated text rendered over them (Gemini and I are in the process of researching how to make the overlay better).
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
| `--get-coords` | | Output recognized words and their coordinates in JSON format. |
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

  1.  **OCR an image (auto-detect language) and translate to English:**
      ```bash
      lens_scan "path/to/your/image.png" -t en
      ```

  2.  **OCR a Japanese image, translate to Russian, save the result, and copy to clipboard:**
      ```bash
      lens_scan "path/to/manga.jpg" ja -t ru -to "translated_manga.png" -sx
      ```
  
  3.  **Get the coordinates of all words in JSON format:**
      ```bash
      lens_scan "path/to/diagram.png" --get-coords
      ```
  
  4.  **Process an image from a URL and get the OCR text as a single line:**
      ```bash
      lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
      ```

</details>

<details>
  <summary><b>👨‍💻 Programmatic API Usage (`LensAPI`)</b></summary>
  
  > [!IMPORTANT]
  > The `LensAPI` is fully **asynchronous**. All data retrieval methods must be called with `await` from within an `async` function.

  #### **Basic Example**
  
  This example shows how to initialize the API, process an image, and print the results.

  ```python
  import asyncio
  from chrome_lens_py.api import LensAPI
  from chrome_lens_py.constants import DEFAULT_API_KEY

  async def main():
      # Initialize the API with your key.
      # You can also pass a proxy, region, etc. here.
      api = LensAPI(api_key=DEFAULT_API_KEY)

      image_source = "path/to/your/image.png" # Or a URL, PIL Image, NumPy array

      try:
          # Process the image and request a translation
          result = await api.process_image(
              image_path=image_source,
              ocr_language="ja", # Optional, can be omitted for auto-detection
              target_translation_language="en"
          )

          print("--- OCR Text ---")
          print(result.get("ocr_text"))

          print("\n--- Translated Text ---")
          print(result.get("translated_text"))

          # To print word and coordinate data:
          # print("\n--- Word Data ---")
          # import json
          # print(json.dumps(result.get("word_data"), indent=2, ensure_ascii=False))
          
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

  #### **`LensAPI` Constructor**

  ```python
  api = LensAPI(
      api_key: str,
      client_region: Optional[str] = None,
      client_time_zone: Optional[str] = None,
      proxy: Optional[str] = None,
      timeout: int = 60,
      font_path: Optional[str] = None,
      font_size: Optional[int] = None
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
      new_session: bool = True,
      ocr_preserve_line_breaks: bool = True
  )
  ```
  -   **`ocr_preserve_line_breaks`**: If `False`, joins all OCR text into a single line.
  -   **`new_session`**: If `False`, attempts to use the same server session as the previous request.

  **The returned `result` dictionary contains:**
  - `ocr_text` (str): The full recognized text.
  - `translated_text` (Optional[str]): The translated text, if requested.
  - `word_data` (List[dict]): A list of dictionaries, where each contains info about a recognized word: `word`, `separator`, and `geometry` (coordinates, angle, etc.).
  - `raw_response_objects` (LensOverlayObjectsResponse): The "raw" Protobuf response object for further analysis.

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