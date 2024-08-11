# Chrome Lens API for Python

[English](/README.md) | [Русский](/README_RU.md)

This project provides a Python library and CLI tool for interacting with Google Lens's OCR functionality via the API used in Chromium. This allows you to process images and extract text data, including full text, coordinates, and stitched text using various methods.

## Features

- **Full Text Extraction**: Extract the complete text from an image.
- **Coordinates Extraction**: Extract text along with its coordinates.
- **Stitched Text**: Reconstruct text from blocks using various methods:
  - **Default Full Text**: Basic method for stitching text blocks.
  - **Old Method**: Sequential text stitching.
  - **New Method**: Enhanced text stitching.

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

### CLI Usage

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

### Programmatic API Usage

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

#### Programmatic API Methods

- **`get_all_data(image_path)`**: Returns all available data for the given image.
- **`get_full_text(image_path)`**: Returns only the full text from the image.
- **`get_text_with_coordinates(image_path)`**: Returns text along with its coordinates in JSON format.
- **`get_stitched_text_smart(image_path)`**: Returns stitched text using the enhanced method.
- **`get_stitched_text_sequential(image_path)`**: Returns stitched text using the basic sequential method.

## Project Structure

```
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
