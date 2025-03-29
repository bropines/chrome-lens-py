> [!IMPORTANT] 
> The library switched to Async. Update your projects !!!!

> [!NOTE] 
> If you don't want to figure out what's in the modules (and there's a lot of garbage written here), and how to transfer it to your project, go to experiments/reverse.py . It's enough for you to figure out how it all works. 

# Chrome Lens API for Python

[English](/README.md) | [Русский](/README_RU.md)

This project provides a Python library and CLI tool for interacting with Google Lens's OCR functionality via the API used in Chromium. This allows you to process images and extract text data, including full text, coordinates, and stitched text using various methods.

## Features

- **Extract the full text**: Extract the main reconstructed text from the image.
- **Coordinate Extraction**: Extract word annotations along with their coordinates (center position, size, and angle in degrees).
- **Stitched text**: Restore text from word annotations using various methods:
  - **Smart method**: Attempts line reconstruction based on vertical positions.
  - **Sequential method**: Sequential stitching based on the order words were recognized.
- **Input from various sources**: Process images from file paths, URLs, [PIL Image objects](https://pillow.readthedocs.io/en/stable/reference/Image.html), and [NumPy arrays](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.html) (including images read by [OpenCV](https://opencv.org/)).
- **Scan images from URLs**: Process images directly from URLs without downloading them manually.
- **Cookie Management**: Handles session cookies automatically, saving/loading them from a `.pkl` file. Can import from Netscape format files or strings via configuration.
- **Proxy Support**: Supports HTTP, HTTPS, and SOCKS4/5 proxies to make requests over different networks.
- **Rate Limiting**: Automatically controls the number of requests per minute to respect API usage limits (configurable).
- ~~**Header Type Selection**: Choose between different sets of request headers.~~ Temporarily deleted!
- **Multilingual**: In the updated version, if there are several languages in the image, they are now recognized. 
> [!NOTE]
> Unfortunately, I have not tested this before, so the final language will be the one that was last in the server response list.

**Important: Asynchronous API**

**This library now uses asynchronous requests (`asyncio`, `httpx`) for improved performance and efficiency. When using the programmatic API, you MUST use `async` and `await` in your code to call the API methods. See the "Programmatic API Usage" section for examples.**

_PS: Lens has a problem with the way it displays full text, which is why methods have been added that stitch text from coordinates._

## Installation

You can install the package using `pip`:

### From PyPI

```bash
pip install chrome-lens-py
```

### Update from PyPI

```bash
pip install -U chrome-lens-py
```

### From GIT

```bash
pip install git+https://github.com/bropines/chrome-lens-py.git
```

### From source

Clone the repository and install the package:

```bash
git clone https://github.com/bropines/chrome-lens-api-py.git
cd chrome-lens-api-py
pip install -r requirements.txt
pip install .
```

## Usage

You can use the `lens_scan` command from the CLI to process images and extract text data, or you can use the Python API to integrate this functionality into your own projects.

<details>
  <summary><b>CLI Usage</b></summary>

```bash
lens_scan <image_source> [data_type] [options]
```

- `<image_source>`: Path to the image file or URL, or path to a directory for batch processing.
- `[data_type]` (optional): Type of data to extract (default: `all`). See below.
- `[options]`: Optional flags to customize behavior.

#### Data Types

- **`all`**: Get all data (language, full text, coordinates, and stitched text using both methods).
- **`full_text_default`**: Get the main reconstructed text.
- **`full_text_old_method`**: Get stitched text using the sequential method.
- **`full_text_new_method`**: Get stitched text using the smart (line reconstruction) method.
- **`coordinates`**: Get word annotations with coordinates.

#### Options

- **`-h, --help`**: Show this help message and exit.
- **`-c, --cookie-file <path>`**: Path to the Netscape or `.pkl` cookie file used by the library.
- **`-p, --proxy <proxy_url>`**: Specify proxy server (e.g., `http://user:pass@host:port`, `socks5://host:port`).
- **`--config-file <path>`**: Path to the JSON configuration file.
- **`--debug=(info|debug)`**: Enable logging at the specified level (`info` or `debug`).
- **`--coordinate-format=(percent|pixels)`**: Output coordinates format: `'percent'` (default) or `'pixels'`.
- **`-st, --sleep-time <milliseconds>`**: DEPRECATED. Sleep time is handled by the internal rate limiter.
- **`-uc, --update-config`**: Update the default config file with non-sensitive CLI arguments.
- **`--debug-out <path>`**: Path to save raw metadata response text (useful when `--debug=debug` is used).
- **`--out-txt=(per_file|filename.txt)`**: Output option when processing a directory: `'per_file'` to output each result to a separate text file, or specify a `filename.txt` for a single combined output file. If not specified for a directory, results print to console.
- ~~**`--header-type=(default|custom|chrome)`**: IGNORED.~~ Temporarily deleted!
- **`--rate-limit-rpm <rpm>`**: Set maximum requests per minute (RPM), e.g., 30. Overrides config value.

#### Examples

To extract text using the smart stitching method from a local file:

```bash
lens_scan path/to/image.jpg full_text_new_method
```

To extract text using the smart stitching method from a URL:

```bash
lens_scan https://example.com/image.jpg full_text_new_method
```

To get all available data from a local file and output coordinates in pixels:

```bash
lens_scan path/to/image.jpg all --coordinate-format=pixels
```

To process all images in a directory and save results to separate files:

```bash
lens_scan /path/to/images all --out-txt=per_file
```

To set a rate limit of 30 requests per minute:

```bash
lens_scan path/to/image.jpg all --rate-limit-rpm 30
```

#### CLI Help

You can use the `-h` or `--help` option to display usage information:

```bash
lens_scan -h
```

</details>

<details>
  <summary><b>Programmatic API Usage</b></summary>

In addition to the CLI tool, this project provides a Python API that can be used in your scripts.

**Important: Asynchronous API**

**The `LensAPI` is designed for asynchronous operations. You MUST use `async` and `await` when calling its methods.**

#### Basic Programmatic Usage

First, import the `LensAPI` class and `asyncio`:

```python
import asyncio
from chrome_lens_py import LensAPI
```

#### Example Programmatic Usage

1.  **Instantiate the API**:

    ```python
    # Instantiate LensAPI - it will handle client setup internally
    api = LensAPI()
    # Example with proxy and debug logging:
    # api = LensAPI(config={'proxy': 'socks5://127.0.0.1:7265'}, logging_level=logging.DEBUG)
    ```

2.  **Process an image within an `async` function**:

    You can process images from various sources: file paths, URLs, PIL Image objects, and NumPy arrays.

    ```python
    import asyncio
    import logging # For setting log level example
    from chrome_lens_py import LensAPI
    from PIL import Image
    import numpy as np

    async def run_lens_tasks():
        # Initialize API (consider proxy, cookies, logging level here)
        # Example: Enable debug logging and set a proxy
        api = LensAPI(
            config={'proxy': 'socks5://127.0.0.1:7265', 'debug_out': 'debug_response.json'},
            logging_level=logging.DEBUG
        )

        image_path = 'd:/bropi/Documents/ShareX/Screenshots/2025-03/NVIDIA_Overlay_GknkEZGEgr.png' # Your image path
        image_url = 'https://www.google.com/images/branding/googlelogo/1x/googlelogo_light_color_272x92dp.png' # Example URL

        try:
            # --- Test 1: Get all data from local file ---
            print("\n--- Testing get_all_data (local file) ---")
            result_all_file = await api.get_all_data(image_path, coordinate_format='pixels')
            print(result_all_file)

            # --- Test 2: Get full text from URL ---
            print("\n--- Testing get_full_text (URL) ---")
            # Corresponds to full_text_default in CLI
            result_text_url = await api.get_full_text(image_url)
            print(result_text_url)

            # --- Test 3: Get coordinates from PIL Image ---
            print("\n--- Testing get_text_with_coordinates (PIL Image) ---")
            try:
                pil_image = Image.open(image_path)
                result_coords_pil = await api.get_text_with_coordinates(pil_image, coordinate_format='percent')
                print(result_coords_pil)
                pil_image.close()
            except FileNotFoundError:
                print(f"PIL Test skipped: Image file not found at {image_path}")
            except Exception as e:
                print(f"Error processing PIL image: {e}")

            # --- Test 4: Get smart stitched text from NumPy array ---
            print("\n--- Testing get_stitched_text_smart (NumPy array) ---")
            # Corresponds to full_text_new_method in CLI
            try:
                np_image = np.array(Image.open(image_path)) # Load image into numpy array
                result_smart_np = await api.get_stitched_text_smart(np_image)
                print(result_smart_np)
            except FileNotFoundError:
                print(f"NumPy Test skipped: Image file not found at {image_path}")
            except Exception as e:
                print(f"Error processing NumPy array: {e}")

            # --- Test 5: Get sequential stitched text from local file ---
            print("\n--- Testing get_stitched_text_sequential (local file) ---")
            # Corresponds to full_text_old_method in CLI
            result_seq_file = await api.get_stitched_text_sequential(image_path)
            print(result_seq_file)

        except Exception as e:
            print(f"\n--- An error occurred during testing: {e} ---")
            logging.exception("Error details:") # Log traceback if logging is enabled
        finally:
            # --- IMPORTANT: Close the session when done ---
            print("\n--- Closing API session ---")
            await api.close_session()

    if __name__ == "__main__":
        # Basic logging setup for the test script
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        asyncio.run(run_lens_tasks())
    ```

#### Configuration Options

You can customize the behavior of the `LensAPI` by passing a `config` dictionary and other parameters when instantiating the class. This allows you to control various aspects of the API, such as proxies, cookie management, debugging, and rate limiting.

The `LensAPI` constructor accepts the following parameters:

-   **`config` (dict, optional)**: A dictionary containing configuration options (see below for details).
-   **`sleep_time` (int, optional)**: DEPRECATED. Internal rate limiter handles delays. Parameter is ignored.
-   **`logging_level` (int, optional)**: Sets the logging level for the API. Uses Python's `logging` module levels (e.g., `logging.DEBUG`, `logging.INFO`, `logging.WARNING`). Default is `logging.WARNING`. Can be overridden by the `debug` in the `config`.
-   **`rate_limit_rpm` (int, optional)**: Sets the maximum requests per minute (RPM) for rate limiting. Overrides `rate_limiting` in `config`. Processed internally.

The following keys can be used within the `config` dictionary:

-   **`proxy`**: Specifies a proxy server for making requests. Supports HTTP, HTTPS, and SOCKS proxies.
    ```python
    api = LensAPI(config={'proxy': 'socks5://127.0.0.1:7265'})
    ```

-   **`cookies`**: Manages cookies for the session. Can be a file path to a Netscape format cookie file to import initially, a cookie string, or a cookie dictionary. The library will manage cookies in its own `.pkl` file after initialization.
    ```python
    # Import from Netscape file on first run
    api = LensAPI(config={'cookies': '/path/to/cookie_file.txt'})
    ```
    ```python
    # Import from header string on first run
    api = LensAPI(config={'cookies': '__Secure-ENID=...; NID=...'})
    ```
    ```python
    # Import from dictionary on first run
    api = LensAPI(config={'cookies': {'__Secure-ENID': {'name': '...', 'value': '...'}, 'NID': {'name': '...', 'value': '...'}}})
    ```

-   **`debug`**: Enables debug logging.
    -   `'info'`: Enables informational logging (level `logging.INFO`).
    -   `'debug'`: Enables detailed debug logging (level `logging.DEBUG`). Overrides the `logging_level` parameter in `LensAPI` constructor.
    ```python
    api = LensAPI(config={'debug': 'debug'})
    ```

-   **`debug_out`**: Specifies the file path to save the raw API metadata response for debugging purposes when `debug` level is `'debug'`.
    ```python
    api = LensAPI(config={'debug': 'debug', 'debug_out': '/path/to/response_debug.json'})
    ```

-   **`rate_limiting`**: Configures rate limiting settings.
    -   **`max_requests_per_minute`**: Sets the maximum requests per minute (RPM). Defaults to around 30 if not set.
    ```python
    api = LensAPI(config={'rate_limiting': {'max_requests_per_minute': 20}})
    ```

</details>

<details>
  <summary><b>Cookie Management</b></summary>

This library automatically manages cookies using a `cookies.pkl` file stored in the user's default configuration directory.

You can **import** cookies initially using the `cookies` option in the `config` dictionary when creating a `LensAPI` instance, or via the `-c` flag in the CLI. Supported import formats:

1.  **Netscape Format File**: Provide the path to the file.

    *   Use browser extensions like [Cookie Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) (Chrome) or [Cookie Editor](https://addons.mozilla.org/en-US/firefox/addon/cookie-editor/) (Firefox) to export cookies in this format.

    **Programmatic API (Initial Import)**:
    ```python
    api = LensAPI(config={'cookies': '/path/to/google_cookies.txt'})
    ```
    **CLI (Initial Import)**:
    ```bash
    lens_scan path/to/image.jpg all -c /path/to/google_cookies.txt
    ```

2.  **Cookie Header String**: Provide the string value of a `Cookie:` HTTP header.

    **Programmatic API (Initial Import)**:
    ```python
    api = LensAPI(config={'cookies': '__Secure-ENID=...; NID=...'})
    ```

3.  **Cookie Dictionary**: Provide a dictionary where keys are cookie names and values are either the cookie value string or another dictionary with details like `name`, `value`, `expires`.

    **Programmatic API (Initial Import)**:
    ```python
    config = {
        'cookies': {
            '__Secure-ENID': 'value1.....',
            'NID': 'value2.....'
         }
    }
    # OR more detailed:
    # config = {
    #    'cookies': {
    #        '__Secure-ENID': {'name': '__Secure-ENID', 'value': 'value1', 'expires': 1756858205},
    #        'NID': {'name': 'NID', 'value': 'value2', 'expires': 1756858205}
    #    }
    # }
    api = LensAPI(config=config)
    ```

**Note**: Once initialized, the library manages cookies internally using `cookies.pkl`. The import options are primarily for the *first run* or if you need to force-reload cookies. Cookies received from the server during requests will automatically update the internal store and the `.pkl` file.

</details>

<details>
  <summary><b>Proxy Support</b></summary>

You can make requests through a proxy server using the API or CLI. The library supports HTTP, HTTPS, and SOCKS4/5 proxies via `httpx`.

*   **Set Proxy in API**:

    ```python
    config = {
        'proxy': 'socks5://127.0.0.1:7265' # Your proxy address
    }
    api = LensAPI(config=config)
    ```
*   **Set Proxy in CLI**:

    ```bash
    lens_scan path/to/image.jpg all -p socks5://127.0.0.1:7265
    ```

</details>

<details>
  <summary><b>Programmatic API Methods</b></summary>

**Important: Asynchronous Methods**

**All data retrieval methods of the `LensAPI` class are asynchronous and MUST be called with `await` from within an `async` function.**

-   **`async get_all_data(image_source, coordinate_format='percent')`**: Returns a dictionary containing all available data (language, full text, coordinates, stitched text) for the given image source.
    -   `image_source`: Path to image file, image URL, PIL Image object, NumPy array, or bytes.
    -   `coordinate_format` (str, optional): Output coordinate format (`'percent'` or `'pixels'`). Defaults to `'percent'`.
-   **`async get_full_text(image_source)`**: Returns the main reconstructed full text (string). Corresponds to CLI `full_text_default`.
    -   `image_source`: Path to image file, image URL, PIL Image object, NumPy array, or bytes.
-   **`async get_text_with_coordinates(image_source, coordinate_format='percent')`**: Returns a list of dictionaries, each containing word text, coordinates (bbox list), and angle (`angle_degrees`). Corresponds to CLI `coordinates`.
    -   `image_source`: Path to image file, image URL, PIL Image object, NumPy array, or bytes.
    -   `coordinate_format` (str, optional): Output coordinate format (`'percent'` or `'pixels'`). Defaults to `'percent'`.
-   **`async get_stitched_text_smart(image_source)`**: Returns text stitched using the smart (line reconstruction) method (string). Corresponds to CLI `full_text_new_method`.
    -   `image_source`: Path to image file, image URL, PIL Image object, NumPy array, or bytes.
-   **`async get_stitched_text_sequential(image_source)`**: Returns text stitched using the basic sequential method (string). Corresponds to CLI `full_text_old_method`.
    -   `image_source`: Path to image file, image URL, PIL Image object, NumPy array, or bytes.
-   **`async close_session()`**: Closes the underlying network session. **Should be called when you are finished using the API instance.**

</details>

<details>
  <summary><b>Working with Coordinates</b></summary>

The API returns coordinate information for each recognized word. This information is provided within the `text_with_coordinates` list when using `get_all_data` or `get_text_with_coordinates`. Each item in the list is a dictionary containing:

-   **`"text"`**: The recognized word (string).
-   **`"coordinates"`**: A list representing the bounding box (`bbox`). The format is typically `[center_y, center_x, height, width, angle_in_radians?, confidence_score?]`.
    -   `center_y`, `center_x`: Coordinates of the bounding box center, relative to image dimensions (0.0 to 1.0).
    -   `height`, `width`: Dimensions of the bounding box, relative to image dimensions (0.0 to 1.0).
    -   `angle_in_radians`: Rotation angle of the box (optional, might not always be present). 0 means no rotation. This value remains in radians as received from the API.
    -   `confidence_score`: A score indicating the OCR confidence (optional).
-   **`"angle_degrees"`** (optional): The rotation angle conveniently converted to **degrees**. This key is added by the library if an angle in radians was present in the raw `coordinates` list. Positive is clockwise, negative is counter-clockwise.

Coordinates (`center_y`, `center_x`, `height`, `width`) are relative to the image dimensions (top-left is `(0.0, 0.0)`, bottom-right is `(1.0, 1.0)`), unless `coordinate_format='pixels'` is used.

#### Example Coordinate Entry

```json
{
  "text": "Example",
  "coordinates": [
    0.5123,    // center_y (relative)
    0.3456,    // center_x (relative)
    0.087,     // height (relative)
    0.25,      // width (relative)
    -0.174533, // angle (radians, approx -10 deg)
    0.95       // confidence
  ],
  "angle_degrees": -10.0  // Angle automatically converted to degrees
}
```

#### Using Coordinate Format (`percent` vs `pixels`)

You can choose the output format for the `coordinates` list values:

-   **`'percent'` (Default)**: Values remain relative (0.0 to 1.0).
-   **`'pixels'`**: The first four values (`center_y`, `center_x`, `height`, `width`) are converted to absolute pixel values based on the **original dimensions** of the image. The angle (in radians) and confidence inside the `coordinates` list remain unchanged. The `angle_degrees` key is unaffected.

##### **In Console**

Use the `--coordinate-format` flag:

```bash
# Output coordinates in pixels:
lens_scan image.jpg coordinates --coordinate-format=pixels
```

##### **In API**

Pass the `coordinate_format` parameter to the relevant methods:

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    api = LensAPI()
    image_path = 'image.jpg'
    # Get data with coordinates in pixels
    result = await api.get_text_with_coordinates(image_path, coordinate_format='pixels') # Use await!
    print(result)
    await api.close_session() # Don't forget to close

if __name__ == "__main__":
    asyncio.run(main())
```

#### **Important Notes**

-   Pixel conversion uses the **original** image dimensions detected before any resizing for the API request.
-   The `angle_degrees` key provides the angle in degrees regardless of the `coordinate_format` setting. The angle value *inside* the `coordinates` list always remains in radians (if originally present).

</details>

<details>
  <summary><b>Debugging and Logging</b></summary>

When using the CLI tool `lens_scan`, you can control the logging level using the `--debug` flag. There are two levels available:

-   `--debug=info`: Enables logging of informational messages (`logging.INFO`).
-   `--debug=debug`: Enables detailed debugging messages (`logging.DEBUG`), including potentially sensitive data.

**Example Usage:**

```bash
# Run with informational logging:
lens_scan path/to/image.jpg all --debug=info

# Run with detailed debugging logging:
lens_scan path/to/image.jpg all --debug=debug
```

When using `--debug=debug`, you can also use `--debug-out <path>` to save the raw JSON metadata response from the API to the specified file path (e.g., `--debug-out response.json`). This is useful for inspecting the raw data structure.

#### Programmatic Debugging

When using the API in your Python scripts, you can control the logging level by configuring the Python `logging` module and by passing the `logging_level` parameter (e.g., `logging.DEBUG`, `logging.INFO`) when instantiating `LensAPI`, or by setting `debug` (`'info'` or `'debug'`) in the `config`.

**Example Usage:**

```python
import asyncio
import logging
from chrome_lens_py import LensAPI

async def main():
    # Configure basic logging for the application
    # logging.basicConfig(level=logging.DEBUG) # Can set global level here

    # Instantiate the API with DEBUG level and specify debug output file
    api = LensAPI(
        logging_level=logging.DEBUG,
        config={'debug_out': 'api_response.json'}
    )
    # Or using config:
    # api = LensAPI(config={'debug': 'debug', 'debug_out': 'api_response.json'})

    try:
        result = await api.get_all_data('path/to/image.jpg') # Use await!
        print(result)
    finally:
        await api.close_session() # Ensure closure

if __name__ == "__main__":
    # Set format for logging if basicConfig wasn't used or needs overriding
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format) # Set default level for script run
    asyncio.run(main())
```

The `logging_level` parameter in `LensAPI` constructor (or `debug` in `config`) controls the library's internal logging verbosity.

When the level is `logging.DEBUG` (or `debug: 'debug'`), the library will output detailed information. If `debug_out` is also specified in the config, the raw metadata response will be saved.

</details>

<details> <summary><b>Configuration Management</b></summary>

### Configuration Priority

Settings are determined in this order (highest priority first):

1.  **Command-line arguments (CLI)**
2.  **Environment variables** (`LENS_SCAN_PROXY`, `LENS_SCAN_COOKIES`, `LENS_SCAN_CONFIG_PATH`)
3.  **Configuration file** (specified by `--config-file`, env var, or default location)
4.  **Default values** built into the library.

### Default Configuration File

*   Stored in the user's OS-specific config directory (e.g., `~/.config/chrome-lens-py/config.json` on Linux, `~/Library/Application Support/chrome-lens-py/config.json` on macOS, `%USERPROFILE%/.config/chrome-lens-py/config.json` on Windows). File name: `config.json`.

### Specifying a Custom Configuration File

*   Use `--config-file path/to/your/config.json` or set `LENS_SCAN_CONFIG_PATH`.
*   Custom config files are **read-only** and not updated by `-uc`.

### Configuration Settings (JSON File)

*   **`proxy`** (string): Proxy URL (e.g., `"socks5://user:pass@host:port"`).
*   **`cookies`** (string or dict): Initial cookies to import (path, header string, or dict). See Cookie Management section.
*   **`coordinate_format`** (string): `"percent"` or `"pixels"`.
*   **`debug`** (string): `"info"` or `"debug"`. Controls logging level.
*   **`debug_out`** (string): Path to save raw metadata response when `debug` is `"debug"`.
*   **`data_type`** (string): Default data type for CLI (`"all"`, `"full_text_default"`, etc.).
*   **`rate_limiting`** (dict): Rate limit settings.
    *   **`max_requests_per_minute`** (int): Max RPM (e.g., `30`).

*Deprecated settings (ignored): `sleep_time`, `header_type`.*

### Example `config.json`

```json
{
  "proxy": "socks5://username:password@proxy.example.com:1080",
  "cookies": "path/to/your/cookie_file.txt",
  "coordinate_format": "percent",
  "debug": "info",
  "debug_out": null,
  "data_type": "all",
  "rate_limiting": {
    "max_requests_per_minute": 25
  }
}
```

### Updating the Default Configuration File (`-uc`)

*   Use the `-uc` or `--update-config` CLI flag to save some settings from the current run *to the default config file location only*.
*   **Updates**: `coordinate_format`, `debug`, `data_type`, `rate_limiting.max_requests_per_minute`, `debug_out`.
*   **Does NOT update**: `proxy`, `cookies`.

### Environment Variables

*   `LENS_SCAN_PROXY`: Overrides proxy config/CLI.
*   `LENS_SCAN_COOKIES`: Overrides cookies config/CLI for initial import.
*   `LENS_SCAN_CONFIG_PATH`: Specifies config file path, overrides default location.

</details>

<details>
<summary><b>Batch Processing (Directory Input)</b></summary>

### Processing Multiple Images in a Directory

Provide a directory path as the `<image_source>` to process all supported images within it using the CLI.

#### CLI Usage

```bash
lens_scan path/to/directory [data_type] [options]
```

*   **`path/to/directory`**: Path to the directory containing images.
*   **`[data_type]`**: Type of data to extract (e.g., `all`, `full_text_default`).
*   **`[options]`**: Such as `--out-txt`, `--rate-limit-rpm`.

**Example:**

```bash
lens_scan /path/to/images all --out-txt=per_file --rate-limit-rpm=20
```

#### Output Options with `--out-txt` (for Directory Input)

*   **`--out-txt=per_file`**: Saves each result to a separate `.txt` file named after the image in the source directory.
*   **`--out-txt=filename.txt`**: Saves all results combined into the specified file in the source directory.
*   **If `--out-txt` is NOT used**: Results for each file are printed to the console sequentially. No combined output file is created by default.

**Examples:**

1.  **Output to Separate Files:**
    ```bash
    lens_scan /path/to/images all --out-txt=per_file
    ```
    (Creates `image1.txt`, `image2.txt`, etc. in `/path/to/images`)

2.  **Output All to a Single File:**
    ```bash
    lens_scan /path/to/images all --out-txt=combined_results.txt
    ```
    (Creates `combined_results.txt` in `/path/to/images`)

3.  **Output to Console (Default for Directory):**
    ```bash
    lens_scan /path/to/images full_text_new_method
    ```
    (Prints results for each image to the standard output)

#### Output Format (Combined File)

When using `--out-txt=filename.txt`, the output file format is:

```plaintext
# --- Result for: image1.jpg ---
{ ... JSON or text result ... }

# --- Result for: image2.png ---
{ ... JSON or text result ... }

# --- FAILED processing: image3.gif ---

...
```

#### Rate Limiting

The internal rate limiter automatically manages delays between requests based on the configured RPM (`--rate-limit-rpm` or config file). The old `--sleep-time` flag is ignored.

#### Programmatic API Usage for Batch

Currently, the programmatic API (`LensAPI` methods) only accepts single image sources (path, URL, PIL, NumPy, bytes). **Batch processing logic (iterating a directory) needs to be implemented in your own code** using the single-source API methods. See the example in the previous `README.md` version or the test script for guidance.

#### Notes:

*   **Supported Files**: Only files recognized as supported image types by `filetype` are processed by the CLI directory mode.
*   **Rate Limiting**: Ensure your RPM settings are reasonable for large directories.
*   **Error Handling**: Errors during individual file processing are logged and typically result in an error entry if collecting results programmatically, or printed to console/file in CLI mode.

</details>

## Project Structure

```plain
/chrome-lens-api-py
│
├── /src
│   ├── /chrome_lens_py
│   │   ├── __init__.py           # Package initialization
│   │   ├── constants.py          # Constants (Endpoints, Headers)
│   │   ├── exceptions.py         # Custom exceptions
│   │   ├── utils.py              # Utility functions (mime check, path, url)
│   │   ├── cookies_manager.py    # Cookie handling (PKL storage, import)
│   │   ├── image_processing.py   # Image resizing, format conversion
│   │   ├── request_handler.py    # Core async HTTP request logic (LensCore, Lens)
│   │   ├── text_processing.py    # Parsing API response, stitching text
│   │   ├── lens_api.py           # Public async API interface (LensAPI)
│   │   └── main.py               # CLI tool entry point (using LensAPI)
│
├── setup.py                      # Installation setup
├── README.md                     # This file
├── README_RU.md                  # Russian README
├── LICENSE                       # MIT License file
└── requirements.txt              # Project dependencies
```

## Acknowledgments

Special thanks to [dimdenGD](https://github.com/dimdenGD) for the original method of text extraction used in earlier versions and inspiration. You can check out their work on the [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr) repository.

## TODO

-   [X] Add `scan by url`
-   [X] Add output in pixels
-   [X] Support input from PIL Image and NumPy arrays
-   [X] Implement Rate Limiting (Automatic via internal limiter)
-   [X] Convert library to `async`/`await` using `httpx`.
-   [X] Add angle in degrees to coordinate output.
-   [ ] Add support for uploading translated images (yes, he can do that now too, in any language (almost)).
-   [ ] Re-evaluate cookie import/export needs (`.pkl` is primary now).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Disclaimer

This project is intended for educational purposes only. The use of Google Lens OCR functionality must comply with Google's Terms of Service. The author of this project is not responsible for any misuse of this software or for any consequences arising from its use. Users are solely responsible for ensuring that their use of this software complies with all applicable laws and regulations.

## Author

### Bropines - [Mail](mailto:bropines@gmail.com) / [Telegram](https://t.me/bropines)