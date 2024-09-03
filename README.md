
# Chrome Lens API for Python

[English](/README.md) | [Русский](/README_RU.md)

This project provides a Python library and CLI tool for interacting with Google Lens's OCR functionality via the API used in Chromium. This allows you to process images and extract text data, including full text, coordinates, and stitched text using various methods.

## Features

- **Extract the full text**: Extract the full text from the image.
- **Coordinate Extraction**: Extract the text along with its coordinates.
- **Stitched text**: Restore text from coordinate blocks using various methods:
- **Old method**: Sequential stitching of text.
  - **New method**: Improved text stitching by calculating them line by line. It is not recommended on rotated texts. Use the past one.
- **Cookie Management**: Download and manage cookies from a file in Netscape format or directly through the configuration.
- **Proxy Support**: Supports HTTP, HTTPS and SOCKS4/5 proxies to make requests over different networks.

PS. Lens has a problem with the way it displays full text, which is why methods have been added that stitch text from coordinates.

## Installation

You can install the package using `pip`:

### From PyPI

```bash
pip install chrome-lens-py
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
lens_scan <image_file> <data_type>
```

#### Data Types

- **all**: Get all data (full text, coordinates, and stitched text using both methods).
- **full_text_default**: Get only the default full text.
- **full_text_old_method**: Get stitched text using the old sequential method.
- **full_text_new_method**: Get stitched text using the new enhanced method.
- **coordinates**: Get text along with coordinates.

#### Example 

To extract text using the new method for stitching:

```bash
lens_scan path/to/image.jpg full_text_new_method
```

To get all available data:

```bash
lens_scan path/to/image.jpg all
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

#### Basic Programmatic Usage

First, import the `LensAPI` class:

```python
from chrome_lens_py import LensAPI
```

#### Example Programmatic Usage

1. **Instantiate the API**:

    ```python
    api = LensAPI()
    ```

2. **Process an image**:

    - **Get all data**:
  
        ```python
        result = api.get_all_data('path/to/image.jpg')
        print(result)
        ```

    - **Get the default full text**:
  
        ```python
        result = api.get_full_text('path/to/image.jpg')
        print(result)
        ```

    - **Get stitched text using the old method**:
  
        ```python
        result = api.get_stitched_text_sequential('path/to/image.jpg')
        print(result)
        ```

    - **Get stitched text using the new method**:
  
        ```python
        result = api.get_stitched_text_smart('path/to/image.jpg')
        print(result)
        ```

    - **Get text with coordinates**:
  
        ```python
        result = api.get_text_with_coordinates('path/to/image.jpg')
        print(result)
        ```

</details>

<details>
  <summary><b>Cookie Management</b></summary>

This project supports the management of cookies through various methods:

1. **Loading Cookies from a Netscape Format File**:
    
    * You can load cookies from a Netscape format file by specifying the file path.
    
    **Programmatic API**:
    
    ```python
    config = {
        'headers': {
            'cookie': '/path/to/cookie_file.txt'
        }
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
        'headers': {
            'cookie': '__Secure-ENID=17.SE=-dizH-; NID=511=---bcDwC4fo0--lgfi0n2-'
        }
    }
    api = LensAPI(config=config)
    ```
    or
   
    ```python
    config = 
       'headers': {
        'cookie': {
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

- **`get_all_data(image_path)`**: Returns all available data for the given image.
- **`get_full_text(image_path)`**: Returns only the full text from the image.
- **`get_text_with_coordinates(image_path)`**: Returns text along with its coordinates in JSON format.
- **`get_stitched_text_smart(image_path)`**: Returns stitched text using the enhanced method.
- **`get_stitched_text_sequential(image_path)`**: Returns stitched text using the basic sequential method.

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

For clarity, let's look at the following example of coordinates:

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
- `0


.5` — Y coordinate (50% of the image height, text centered vertically).
- `0.5` — X coordinate (50% of the image width, text centered horizontally).
- `0.3` — width of the text region (30% of the image width).
- `0.1` — height of the text region (10% of the image height).
- `0` — not used, default value (possibly reserved for future use).
- `-45` — rotation angle of the text counterclockwise by 45 degrees.

These values are used to accurately place, scale, and display the text on the image.

</details>

## Project Structure

```plain text
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
- Move all methods from [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr)
- Do everything beautifully, and not like 400 lines of code, cut into modules by GPT chat
- Something else very, very important...

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Disclaimer

This project is intended for educational purposes only. The use of Google Lens OCR functionality must comply with Google's Terms of Service. The author of this project is not responsible for any misuse of this software or for any consequences arising from its use. Users are solely responsible for ensuring that their use of this software complies with all applicable laws and regulations.

## Author

### Bropines  - [Mail](mailto:bropines@gmail.com) / [Telegram](https://t.me/bropines)
