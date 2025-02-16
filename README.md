# Chrome Lens API for Python

[English](/README.md) | [Русский](/README_RU.md)

This project provides a Python library and CLI tool for interacting with Google Lens's OCR functionality via the API used in Chromium. This allows you to process images and extract text data, including full text, coordinates, and stitched text using various methods.

## Features

- **Extract the full text**: Extract the full text from the image.
- **Coordinate Extraction**: Extract the text along with its coordinates.
- **Stitched text**: Restore text from coordinate blocks using various methods:
  - **Smart method**: Improved line-by-line text stitching, suitable for most images (but may be less effective on heavily rotated text).
  - **Sequential method**: Sequential stitching of text blocks, a more basic approach.
- **Input from various sources**: Process images from file paths, URLs, [PIL Image objects](https://pillow.readthedocs.io/en/stable/reference/Image.html), and [NumPy arrays](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.html) (including images read by [OpenCV](https://opencv.org/)).
- **Scan images from URLs**: Process images directly from URLs without downloading them manually.
- **Cookie Management**: Download and manage cookies from a file in Netscape format or directly through the configuration.
- **Proxy Support**: Supports HTTP, HTTPS, and SOCKS4/5 proxies to make requests over different networks.
- **Rate Limiting**: Control the number of requests per minute to respect API usage limits.
- ~~**Header Type Selection**: Choose between different sets of request headers (`default`, `custom`, `chrome`).~~ Temporarily deleted!

**Important: Asynchronous API**

**This library now uses asynchronous requests for improved performance and efficiency. When using the programmatic API, you must use `async` and `await` in your code to call the API methods. See the "Programmatic API Usage" section for examples.**

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
lens_scan <image_source> <data_type> [options]
```

- `<image_source>`: Path to the image file or URL, or path to a directory for batch processing.
- `<data_type>`: Type of data to extract (see below).
- `[options]`: Optional flags to customize behavior.

#### Data Types

- **all**: Get all data (full text, coordinates, and stitched text using both smart and sequential methods).
- **full_text_default**: Get only the default full text.
- **full_text_sequential**: Get stitched text using the sequential method.
- **full_text_smart**: Get stitched text using the smart method.
- **coordinates**: Get text along with coordinates.

#### Options

- **`-h, --help`**: Show this help message and exit.
- **`-c, --cookie-file <path>`**: Path to the Netscape cookie file.
- **`-p, --proxy <proxy_url>`**: Specify proxy server (e.g., `socks5://user:pass@host:port`).
- **`--config-file <path>`**: Path to the configuration file.
- **`--debug=(info|debug)`**: Enable logging at the specified level (`info` or `debug`).
- **`--coordinate-format=(percent|pixels)`**: Output coordinates format: `'percent'` or `'pixels'`.
- **`-st, --sleep-time <milliseconds>`**: Sleep time between requests in milliseconds (for batch processing).
- **`-uc, --update-config`**: Update the default config file with CLI arguments (excluding proxy and cookies).
- **`--debug-out <path>`**: Path to save debug output response (when `--debug=debug` is used).
- **`--out-txt=(per_file|filename.txt)`**: Output option for batch processing: `'per_file'` to output each result to a separate text file, or specify a `filename.txt` for a single output file.
- ~~**`--header-type=(default|custom|chrome)`**: Header type to use: `'default'`, `'custom'`, or `'chrome'`.~~ Temporarily deleted!
- **`--rate-limit-rpm <rpm>`**: Set maximum requests per minute (RPM), value between 1 and 40.

#### Examples

To extract text using the smart stitching method from a local file:

```bash
lens_scan path/to/image.jpg full_text_smart
```

To extract text using the smart stitching method from a URL:

```bash
lens_scan https://example.com/image.jpg full_text_smart
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

~~To use Chrome-like headers for requests:~~ Temporarily deleted!

```bash
lens_scan path/to/image.jpg all --header-type chrome
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

**The `LensAPI` is designed for asynchronous operations. You must use `async` and `await` when calling its methods.**

#### Basic Programmatic Usage

First, import the `LensAPI` class and `asyncio`:

```python
import asyncio
from chrome_lens_py import LensAPI
```

#### Example Programmatic Usage

1. **Instantiate the API**:

   ```python
   api = LensAPI() # Or with configuration, see "Configuration Options"
   ```

2. **Process an image**:

   You can process images from various sources: file paths, URLs, PIL Image objects, and NumPy arrays.

   - **Get all data from a local file**:

     ```python
     import asyncio
     from chrome_lens_py import LensAPI

     async def main():
         api = LensAPI()
         result = await api.get_all_data('path/to/image.jpg') # Use await!
         print(result)

     if __name__ == "__main__":
         asyncio.run(main())
     ```

   - **Get all data from a URL**:

     ```python
     import asyncio
     from chrome_lens_py import LensAPI

     async def main():
         api = LensAPI()
         result = await api.get_all_data('https://example.com/image.jpg') # Use await!
         print(result)

     if __name__ == "__main__":
         asyncio.run(main())
     ```

   - **Get the default full text from a PIL Image object**:

     ```python
     import asyncio
     from PIL import Image
     from chrome_lens_py import LensAPI

     async def main():
         api = LensAPI()
         image = Image.open('path/to/image.jpg')
         result = await api.get_full_text(image) # Pass PIL Image object, use await!
         print(result)

     if __name__ == "__main__":
         asyncio.run(main())
     ```

   - **Get stitched text using the smart method from a NumPy array**:

     ```python
     import asyncio
     import numpy as np
     from PIL import Image # Pillow is needed for image loading in this example
     from chrome_lens_py import LensAPI

     async def main():
         api = LensAPI()
         image_np_array = np.array(Image.open('path/to/image.jpg')) # Load image as NumPy array
         result = await api.get_stitched_text_smart(image_np_array) # Pass NumPy array, use await!
         print(result)

     if __name__ == "__main__":
         asyncio.run(main())
     ```

   - **Other methods (full_text_sequential, get_text_with_coordinates, etc.)**: Follow the same pattern, using `await` before calling the API methods and ensuring your calling code is within an `async` function.

#### Configuration Options

You can customize the behavior of the `LensAPI` by passing a `config` dictionary and other parameters when instantiating the class. This allows you to control various aspects of the API, such as ~~headers~~, proxies, cookie management, debugging, request timing, and rate limiting.

The `LensAPI` constructor accepts the following parameters:

- **`config` (dict, optional)**: A dictionary containing configuration options (see below for details).
- **`sleep_time` (int, optional)**: Sets the default delay in milliseconds between consecutive API requests. Default is `1000` (1 second). Can be overridden by the `sleep_time` in the `config`.
- **`logging_level` (int, optional)**: Sets the logging level for the API. Uses Python's `logging` module levels (e.g., `logging.DEBUG`, `logging.INFO`, `logging.WARNING`). Default is `logging.WARNING`. Can be overridden by the `debug` in the `config`.
- **`rate_limit_rpm` (int, optional)**: Sets the maximum requests per minute (RPM) for rate limiting. Value must be between 1 and 40. Can be overridden by the `rate_limiting` in the `config`.

The following keys can be used within the `config` dictionary:

- ~~**`header_type`**:  Selects the set of headers to use for requests.~~ Temporarily deleted!
    - `'default'`: Uses the default set of headers.
    - `'custom'`: Uses a custom set of headers.
    - `'chrome'`: Uses headers that resemble those sent by Chrome browser.
    ```python
    api = LensAPI(config={'header_type': 'chrome'})
    ```

- **`proxy`**: Specifies a proxy server for making requests. Supports HTTP, HTTPS, and SOCKS proxies.
    ```python
    api = LensAPI(config={'proxy': 'socks5://127.0.0.1:2080'})
    ```

- **`cookies`**:  Manages cookies for the session. Can be a file path to a Netscape format cookie file, a cookie string, or a cookie dictionary.
    ```python
    api = LensAPI(config={'cookies': '/path/to/cookie_file.txt'})
    ```
    ```python
    api = LensAPI(config={'cookies': '__Secure-ENID=...; NID=...'})
    ```
    ```python
    api = LensAPI(config={'cookies': {'__Secure-ENID': {'name': '...', 'value': '...', 'expires': ...}, 'NID': {'name': '...', 'value': '...', 'expires': ...}}})
    ```

- **`sleep_time`**: Sets the delay in milliseconds between consecutive API requests. This is particularly useful in batch processing to avoid overloading the server. Overrides the `sleep_time` parameter in `LensAPI` constructor.
    ```python
    api = LensAPI(config={'sleep_time': 500}) # Set a 500ms delay
    ```

- **`debug`**: Enables debug logging.
    - `'info'`: Enables informational logging.
    - `'debug'`: Enables detailed debug logging and saves raw API responses to `response_debug.txt`. Overrides the `logging_level` parameter in `LensAPI` constructor.
    ```python
    api = LensAPI(config={'debug': 'debug'})
    ```

- **`debug_out`**:  Specifies the file path to save the raw API response for debugging purposes when `debug` is set to `'debug'`.
    ```python
    api = LensAPI(config={'debug_out': '/path/to/response_debug.txt'})
    ```

- **`rate_limiting`**: Configures rate limiting settings.
    - **`max_requests_per_minute`**: Sets the maximum requests per minute (RPM). Value must be between 1 and 50. Overrides the `rate_limit_rpm` parameter in `LensAPI` constructor.
    ```python
    api = LensAPI(config={'rate_limiting': {'max_requests_per_minute': 30}})
    ```


</details>

<details>
  <summary><b>Cookie Management</b></summary>

This project supports the management of cookies through various methods.

To receive cookies in Netscape format, you can use the following extensions:

- Chrome (Chromium): [Cookie Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)
- Firefox: [Cookie Editor](https://addons.mozilla.org/ru/firefox/addon/cookie-editor/)

1. **Loading Cookies from a Netscape Format File**:

   * You can load cookies from a Netscape format file by specifying the file path.

   **Programmatic API**:

   ```python
   config = {
       'cookies': '/path/to/cookie_file.txt'
   }
   api = LensAPI(config=config)
   ```

   **CLI**:

   ```bash
   lens_scan path/to/image.jpg all -c /path/to/cookie_file.txt
   ```
2. **Passing Cookies Directly as a String**:

   * You can also pass cookies directly as a string in the configuration or via CLI.

   **Programmatic API**:

   ```python
   config = {
       'cookies': '__Secure-ENID=17.SE=-dizH-; NID=511=---bcDwC4fo0--lgfi0n2-'
   }
   api = LensAPI(config=config)
   ```

   or

   ```python
   config = {
       'cookies': {
           '__Secure-ENID': {
               'name': '__Secure-ENID',
               'value': '',
               'expires': 1756858205,
           },
           'NID': {
               'name': 'NID',
               'value': '517=4.......',
               'expires': 1756858205,
           }
       }
   }
   api = LensAPI(config=config)
   ```

</details>

<details>
  <summary><b>Proxy Support</b></summary>

You can make requests through a proxy server using the API or CLI. The library supports HTTP, HTTPS, and SOCKS4/5 proxies.

* **Set Proxy in API**:

  ```python
  config = {
      'proxy': 'socks5://127.0.0.1:2080'
  }
  api = LensAPI(config=config)
  ```
* **Set Proxy in CLI**:

  ```bash
  lens_scan path/to/image.jpg all -p socks5://127.0.0.1:2080
  ```

</details>

<details>
  <summary><b>Programmatic API Methods</b></summary>

**Important: Asynchronous Methods**

**All methods of the `LensAPI` class are asynchronous and must be called with `await`.**

- **`get_all_data(image_source, coordinate_format='percent')`**: Returns all available data for the given image source (file path, URL, PIL Image object, or NumPy array).
    - `image_source`: Path to the image file, image URL, PIL Image object, or NumPy array.
    - `coordinate_format` (str, optional): Output coordinate format, either `'percent'` or `'pixels'`. Defaults to `'percent'`.
- **`get_full_text(image_source, coordinate_format='percent')`**: Returns only the full text from the image source.
    - `image_source`: Path to the image file, image URL, PIL Image object, or NumPy array.
    - `coordinate_format` (str, optional): Output coordinate format, either `'percent'` or `'pixels'`. Defaults to `'percent'`.
- **`get_text_with_coordinates(image_source, coordinate_format='percent')`**: Returns text along with its coordinates in JSON format from the image source.
    - `image_source`: Path to the image file, image URL, PIL Image object, or NumPy array.
    - `coordinate_format` (str, optional): Output coordinate format, either `'percent'` or `'pixels'`. Defaults to `'percent'`.
- **`get_stitched_text_smart(image_source, coordinate_format='percent')`**: Returns stitched text using the smart method from the image source.
    - `image_source`: Path to the image file, image URL, PIL Image object, or NumPy array.
    - `coordinate_format` (str, optional): Output coordinate format, either `'percent'` or `'pixels'`. Defaults to `'percent'`.
- **`get_stitched_text_sequential(image_source, coordinate_format='percent')`**: Returns stitched text using the basic sequential method from the image source.
    - `image_source`: Path to the image file, image URL, PIL Image object, or NumPy array.
    - `coordinate_format` (str, optional): Output coordinate format, either `'percent'` or `'pixels'`. Defaults to `'percent'`.

</details>

<details>
  <summary><b>Working with Coordinates</b></summary>

In our project, coordinates are used to define the position, size, and rotation of text on an image. Each text region is described by a set of values that help accurately determine where and how to display the text. Here's how these values are interpreted:

1. **Y Coordinate**: The first value in the coordinates array represents the vertical position of the top-left corner of the text region on the image. The value is expressed as a fraction of the image's total height, with `0.0` corresponding to the top edge and `1.0` to the bottom.

2. **X Coordinate**: The second value indicates the horizontal position of the top-left corner of the text region. The value is expressed as a fraction of the image's total width, where `0.0` corresponds to the left edge and `1.0` to the right.

3. **Width**: The third value represents the width of the text region as a fraction of the image's total width. This value determines how much horizontal space the text will occupy.

4. **Height**: The fourth value indicates the height of the text region as a fraction of the image's total height.

5. **Fifth Parameter**: In the current data, this parameter is always zero and appears to be unused. It might be reserved for future use or specific text modifications.

6. **Sixth Parameter**: Specifies the rotation angle of the text region in degrees. Positive values indicate clockwise rotation, while negative values indicate counterclockwise rotation.

Coordinates are measured from the top-left corner of the image. This means that `(0.0, 0.0)` corresponds to the very top-left corner of the image, while `(1.0, 1.0)` corresponds to the very bottom-right corner.

#### Example of Coordinate Usage

```json
{
    "text": "Sample text",
    "coordinates": [
        0.5,
        0.5,
        0.3,
        0.1,
        0,
        -45
    ]
}
```

In this example:

- `0.5` — Y coordinate (50% of the image height, text centered vertically).
- `0.5` — X coordinate (50% of the image width, text centered horizontally).
- `0.3` — width of the text region (30% of the image width).
- `0.1` — height of the text region (10% of the image height).
- `0` — not used, default value (possibly reserved for future use).
- `-45` — rotation angle of the text counterclockwise by 45 degrees.

These values are used to accurately place, scale, and display the text on the image.

#### **Using Coordinate Format**

You can choose the coordinate output format: percentages or pixels. By default, coordinates are output in percentages, but you can switch to pixels using the appropriate settings.

##### **In Console**

When using the command line, you can specify the coordinate format using the `--coordinate-format` flag. Acceptable values are `'percent'` or `'pixels'`.

**Usage Examples:**

- **Output coordinates in percentages (default):**

  ```bash
  lens_scan image.jpg coordinates
  ```

- **Output coordinates in pixels:**

  ```bash
  lens_scan image.jpg coordinates --coordinate-format=pixels
  ```

##### **In API**

When using the programmatic API, you can pass the `coordinate_format` parameter to the methods of the `LensAPI` class. Acceptable values are `'percent'` or `'pixels'`.

**Usage Example:**

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    api = LensAPI()

    # Path to the image
    image_path = 'image.jpg'

    # Get data with coordinates in pixels
    result = await api.get_all_data(image_path, coordinate_format='pixels') # Use await!

    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

#### **Important**

- When selecting the `'pixels'` format, coordinates will be calculated relative to the **original dimensions** of the image, even if the image was resized for processing.
- If the format is not specified, coordinates are output in percentages by default.
- When working with pixel coordinates, ensure you use the original image for accurate placement of text regions.
</details>

<details>
  <summary><b>Debugging and Logging</b></summary>

When using the CLI tool `lens_scan`, you can control the logging level using the `--debug` flag. There are two levels available:

- `--debug=info`: Enables logging of informational messages, which include general information about the processing steps.
- `--debug=debug`: Enables detailed debugging messages, including verbose output and the saving of the raw response from the API to a file named `response_debug.txt` in the current directory.

**Example Usage:**

- To run with informational logging:

  ```bash
  lens_scan path/to/image.jpg all --debug=info
  ```

- To run with detailed debugging logging:

  ```bash
  lens_scan path/to/image.jpg all --debug=debug
  ```

When using `--debug=debug`, the library will save the raw response from the API to `response_debug.txt` in the current working directory. This can be useful for deep debugging and understanding the exact response from the API.

#### Programmatic Debugging

When using the API in your Python scripts, you can control the logging level by configuring the logging module and by passing the `logging_level` parameter when instantiating the `LensAPI` class, or by setting `debug` in the `config`.

**Example Usage:**

```python
import asyncio
import logging
from chrome_lens_py import LensAPI

async def main():
    # Configure basic logging to console (optional, for general Python logging)
    logging.basicConfig(level=logging.DEBUG)

    # Instantiate the API with the desired logging level
    api = LensAPI(logging_level=logging.DEBUG) # Or api = LensAPI(config={'debug': 'debug'})

    # Process an image
    result = await api.get_all_data('path/to/image.jpg') # Use await!
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

The `logging_level` parameter in `LensAPI` constructor (or `debug` in `config`) accepts logging levels from Python's `logging` module, such as `logging.INFO`, `logging.DEBUG`, `logging.WARNING`, etc.  You can also use string values `'info'` and `'debug'` in the `config` for `debug` parameter.

When the logging level is set to `logging.DEBUG` (or `debug: 'debug'`), the library will output detailed debugging information and save the raw API response to `response_debug.txt` in the current directory.

The `--debug-out` flag (or `debug_out` in `config`) will allow you to specify the path where to save the response from the server, in the case of the debug level `DEBUG`. By default, it is saved, as described above, in the folder where the console is launched, that is, in `CWD`.

#### Notes on Logging Levels

- **INFO** level: Provides general information about the process, such as when requests are sent and responses are received.
- **DEBUG** level: Provides detailed information useful for debugging, including internal state and saved responses.

</details>

<details> <summary><b>Configuration Management</b></summary>

### Configuration Priority

When running the CLI tool `lens_scan`, the application determines settings based on the following priority order (from highest to lowest):

1. **Command-line arguments (CLI)**: Options specified directly when running the command have the highest priority.
2. **Environment variables**: If a setting is not specified in the CLI, the application will check for corresponding environment variables.
3. **Configuration file**: If a setting is not found in the CLI arguments or environment variables, the application will look into the configuration file.
4. **Default values**: If a setting is not specified in any of the above, default values are used.

### Default Configuration File

* The default configuration file is located in the user's configuration directory, which varies by operating system:
    * **Windows**: `C:\Users\<YourUserName>\.config\chrome-lens-py\config.json`
    * **Unix/Linux**: `/home/<YourUserName>/.config/chrome-lens-py/config.json`
    * **macOS**: `/Users/<YourUserName>/Library/Application Support/chrome-lens-py/config.json`

### Specifying a Custom Configuration File

* You can specify a custom configuration file using the `--config-file` flag:

    ```bash
    lens_scan --config-file path/to/your/config.json <image_source> <data_type>
    ```

* When a custom configuration file is specified, it is treated as read-only and will not be modified by the application.


### Configuration Settings

The configuration file is a JSON file that can include the following settings:

* **`proxy`**: Specify a proxy server to route requests.

    ```json
    {
      "proxy": "socks5://username:password@proxy.example.com:1080"
    }
    ```

* **`cookies`**: Specify cookies to use with requests. This can be a path to a cookies file or a cookie string.

    ```json
    {
      "cookies": "path/to/your/cookie_file.txt"
    }
    ```

    or

    ```json
    {
      "cookies": "__Secure-ENID=17.SE=-dizH-; NID=511=---bcDwC4fo0--lgfi0n2-"
    }
    ```

* **`coordinate_format`**: Set the format of output coordinates. Acceptable values are `"percent"` or `"pixels"`.

    ```json
    {
      "coordinate_format": "pixels"
    }
    ```

* **`debug`**: Set the logging level for CLI and API. Acceptable values are `"info"` or `"debug"`.

    ```json
    {
      "debug": "debug"
    }
    ```

* **`debug_out`**:  Specifies the file path to save the raw API response for debugging purposes when `debug` is set to `'debug'`.

    ```json
    {
      "debug_out": "/path/to/response_debug.txt"
    }
    ```

* **`data_type`**: Set the default type of [output data](#data-types) for CLI if not specified in command line.

    ```json
    {
      "data_type": "all"
    }
    ```

* **`sleep_time`**: Sets the default delay in milliseconds between consecutive API requests, used in batch processing and API calls if not overridden in `LensAPI` constructor.

    ```json
    {
      "sleep_time": 500
    }
    ```

* ~~**`header_type`**:  Selects the default set of headers to use for requests if not specified via CLI or API constructor. Acceptable values: `"default"`, `"custom"`, `"chrome"`.~~ Temporarily deleted!

    ```json
    {
      "header_type": "chrome"
    }
    ```

* **`rate_limiting`**: Configures rate limiting settings.
    - **`max_requests_per_minute`**: Sets the maximum requests per minute (RPM). Value must be between 1 and 40. Overrides the `rate_limit_rpm` parameter in `LensAPI` constructor and `--rate-limit-rpm` CLI option if not specified in command line.

    ```json
    {
      "rate_limiting": {
        "max_requests_per_minute": 30
      }
    }
    ```


### Complete Example Configuration File

Here is an example of a configuration file that includes all possible configuration parameters:

```json
{
  "proxy": "socks5://username:password@proxy.example.com:1080",
  "cookies": "path/to/your/cookie_file.txt",
  "coordinate_format": "pixels",
  "debug": "debug",
  "debug_out": "/path/to/response_debug.txt",
  "data_type": "all",
  "sleep_time": 500,
  "header_type": "chrome",
  "rate_limiting": {
    "max_requests_per_minute": 30
  }
}
```

### Updating the Configuration File

* To update the default configuration file with new settings from the CLI, use the `-uc` or `--update-config` flag.

    ```bash
    lens_scan <image_source> <data_type> [options] -uc
    ```

* **Note**: The configuration file will only be updated if it's the default configuration file (i.e., not specified via `--config-file`).

* Only specific settings will be updated:

    * **Settings that can be updated**:

        * `coordinate_format`
        * `debug`
        * `data_type`
        * `sleep_time`
        * `header_type`
        * `rate_limiting.max_requests_per_minute`
    * **Settings that will **not** be updated**:

        * `proxy`
        * `cookies`
        * `image_source`

* This allows you to persist certain settings across runs without affecting critical configurations like proxy settings or cookies.


### Example Usage

* **Updating the coordinate format in the default configuration file**:

    ```bash
    lens_scan path/to/image.jpg all --coordinate-format=pixels -uc
    ```

    * This command will set the coordinate format to pixels for the current run and update the default configuration file so that future runs will also use pixels as the coordinate format.
* **Using a proxy without updating the configuration file**:

    ```bash
    lens_scan path/to/image.jpg all -p socks5://127.0.0.1:2080
    ```

    * The proxy setting will be used for this run but will not be saved to the configuration file.
* **Specifying a custom configuration file (read-only)**:

    ```bash
    lens_scan --config-file path/to/config.json path/to/image.jpg all
    ```

    * The application will use settings from the specified configuration file but will not modify it, even if the `-uc` flag is used.

### Environment Variables

You can also specify settings via environment variables:

* **`LENS_SCAN_PROXY`**: Set the proxy server.

    ```bash
    export LENS_SCAN_PROXY="socks5://username:password@proxy.example.com:1080"
    ```

* **`LENS_SCAN_COOKIES`**: Provide cookies.

    ```bash
    export LENS_SCAN_COOKIES="__Secure-ENID=17.SE=-dizH-; NID=511=---"
    ```

* **`LENS_SCAN_CONFIG_PATH`**: Specify a custom configuration file.

    ```bash
    export LENS_SCAN_CONFIG_PATH="path/to/your/config.json"
    ```

</details>

<details>
<summary><b>Batch Processing</b></summary>

### Batch Processing of Multiple Images

This project supports batch processing of images when a directory path is provided instead of a single image file. The application will process all image files in the specified directory.

#### CLI Usage

To perform batch processing via the command line, simply provide the path to the directory containing the images instead of a single image file.

```bash
lens_scan path/to/directory <data_type> [options]
```

* **`path/to/directory`**: Path to the directory containing image files.
* **`<data_type>`**: Type of data to extract (e.g., `all`, `full_text_default`, etc.).
* **`[options]`**: Additional options such as `--out-txt`, `--sleep-time`, etc.

**Example:**

```bash
lens_scan /path/to/images all --out-txt=per_file --sleep-time=500
```

#### Output Options with `--out-txt`

The `--out-txt` flag allows you to control how the output is saved when processing multiple images:

* **`--out-txt=per_file`**: Outputs each result to a separate text file based on the image name within the same directory.
* **`--out-txt=filename.txt`**: Outputs all results into a single text file with the specified name within the same directory.
* **No `--out-txt` flag**: By default, all results are saved into a file named `output.txt` within the same directory.

**Examples:**

1. **Output to Separate Files Per Image:**

    ```bash
    lens_scan /path/to/images all --out-txt=per_file
    ```

    This command processes all images in `/path/to/images` and saves each result to a separate text file named after the image (e.g., `image1.txt`, `image2.txt`).

2. **Output All Results to a Single File:**

    ```bash
    lens_scan /path/to/images all --out-txt=results.txt
    ```

    This command processes all images and saves all results into `results.txt` within the same directory.

3. **Default Output (output.txt):**

    ```bash
    lens_scan /path/to/images all
    ```

    Without specifying `--out-txt`, the results are saved into `output.txt` within the same directory.


#### Output Format

When outputting to a single file (default behavior or when specifying a filename with `--out-txt`), the format of the output file is:

```plaintext
#filename1.jpg
Extracted text from filename1.jpg

#filename2.png
Extracted text from filename2.png

...
```

Each image's extracted text is prefixed with a `#` followed by the filename, and the text retains the original formatting, including newline characters.

#### Sleep Time Between Requests

To avoid overwhelming the API and to comply with rate limiting policies, the library introduces a delay between processing each image. By default, this sleep time is set to 1000 milliseconds (1 second). You can adjust this delay using the `-st` or `--sleep-time` flag, specifying the time in milliseconds.

**Example:**

```bash
lens_scan /path/to/images all --sleep-time 500
```

This command sets the sleep time to 500 milliseconds between processing each image.

#### Programmatic API Usage

You can also perform batch processing using the Python API by providing a directory path to the methods. **Note that batch processing via API methods is also asynchronous and requires `await`.**

**Example:**

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    api = LensAPI(sleep_time=500)  # Set sleep time to 500 milliseconds

    # Path to the directory containing images
    directory_path = '/path/to/images'

    # Process the directory to extract full text from each image
    results = await api.get_full_text(directory_path) # Use await!

    # Iterate through the results
    for filename, text in results.items():
        if 'error' in text:
            print(f"Error processing {filename}: {text['error']}")
        else:
            print(f"# {filename}")
            print(text)
            print()

if __name__ == "__main__":
    asyncio.run(main())
```


#### Notes:

* **Supported Image Files**: Only image files with supported MIME types will be processed. Non-image files or unsupported formats will be ignored.
* **Adjusting Sleep Time**: The sleep time between requests can be adjusted to meet your needs, but be cautious when reducing it to prevent being rate-limited by the API.
* **Rate Limiting**: Be mindful of rate limits, especially when processing large batches of images. Use `--rate-limit-rpm` CLI option or `rate_limit_rpm` parameter in `LensAPI` constructor to control the request rate.
* **Error Handling**: If an error occurs while processing an image, the error message will be stored in the results under that filename.
* **Output Files**: When using `--out-txt=per_file`, the output text files will be saved in the same directory as the images, with the same base filename and a `.txt` extension.

</details>


## Project Structure

```plain
/chrome-lens-api-py
│
├── /src
│   ├── /chrome_lens_py
│   │   ├── __init__.py           # Package initialization
│   │   ├── constants.py          # Constants used in the project
│   │   ├── utils.py              # Utility functions
│   │   ├── image_processing.py   # Image processing module
│   │   ├── request_handler.py    # API request handling module
│   │   ├── text_processing.py    # Text processing module
│   │   ├── lens_api.py           # API interface for use in other scripts
│   │   └── main.py               # CLI tool entry point
│
├── setup.py                      # Installation setup
├── README.md                     # Project description and usage guide
└── requirements.txt              # Project dependencies
```

## Acknowledgments

Special thanks to [dimdenGD](https://github.com/dimdenGD) for the method of text extraction used in this project. You can check out their work on the [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr) repository. This project is inspired by their approach to leveraging Google Lens OCR functionality.

## TODO

- [X] Add `scan by url`
- [X] Add output in pixels
- [X] Support input from PIL Image and NumPy arrays
- [X] Implement Rate Limiting
- [ ] Move all methods from [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr)
  - cookie!?
- [X] Do everything beautifully, and not like 400 lines of code, cut into modules by GPT chat
- [ ] Something else very, very important...

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Disclaimer

This project is intended for educational purposes only. The use of Google Lens OCR functionality must comply with Google's Terms of Service. The author of this project is not responsible for any misuse of this software or for any consequences arising from its use. Users are solely responsible for ensuring that their use of this software complies with all applicable laws and regulations.

## Author

### Bropines - [Mail](mailto:bropines@gmail.com) / [Telegram](https://t.me/bropines)
