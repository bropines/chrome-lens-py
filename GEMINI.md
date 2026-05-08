# GEMINI.md

## Project Overview
`chrome-lens-py` is a powerful, asynchronous Python library and command-line tool designed to interact directly with Google Lens via its reverse-engineered Protobuf endpoint (`v1/crupload`). This project enables advanced Optical Character Recognition (OCR), logical text segmentation (ideal for comics/manga), translation, and precise coordinate extraction for recognized text.

### Key Technologies
- **Python 3.8+**: Core language.
- **Asyncio & HTTPX**: For high-performance, asynchronous networking.
- **Protobuf (betterproto)**: For structured communication with Google's internal APIs.
- **Pillow (PIL)**: For image manipulation and processing.
- **NumPy**: For supporting array-based image inputs.
- **Rich**: For beautiful terminal output in the CLI.

### Architecture
- **API Layer (`src/chrome_lens_py/api.py`)**: The primary `LensAPI` class for programmatic interaction.
- **Core Logic (`src/chrome_lens_py/core/`)**:
    - `image_processor.py`: Handles image normalization and preparation.
    - `protobuf_builder.py`: Constructs the complex Protobuf messages required by Google.
    - `request_handler.py`: Manages the low-level HTTP communication and session state.
- **CLI Layer (`src/chrome_lens_py/cli/main.py`)**: Provides the `lens_scan` command-line utility.
- **Utils (`src/chrome_lens_py/utils/`)**: Contains Protobuf definitions and helper functions.

---

## Building and Running

### Installation
For development, it is recommended to install the package in editable mode with development dependencies:
```bash
pip install -e ".[dev,clipboard]"
```

### Running the CLI
The CLI tool `lens_scan` is the primary way to use the library from the terminal:
```bash
# Basic OCR and Translation
lens_scan "image.png" -t en

# Get segmented blocks (for comics)
lens_scan "manga.jpg" ja -b
```

### Running Tests
- **Automated Tests**: Use `pytest` to run the test suite.
  ```bash
  pytest
  ```
- **Manual/Integration Tests**: The `test_base.py` script provides a deep dive into session initialization and complex Protobuf queries.
  ```bash
  python test_base.py
  ```

---

## Development Conventions

### Coding Style
- **Asynchronous First**: All network-bound operations MUST be `async`.
- **Typing**: Use type hints for all function signatures.
- **Linting & Formatting**: Adhere to `black` formatting and `isort` for import sorting. `flake8` is used for linting with a max line length of 140.
  ```bash
  # Check formatting
  black .
  isort .
  # Lint
  flake8 src
  ```

### Protobuf Management
The project relies heavily on Protobuf definitions located in `src/chrome_lens_py/utils/protobufs/`. Any changes to the communication protocol should be reflected in these definitions. Note that `lens_betterproto.py` is a generated file that should be handled with care.

### API Safety
The `LensAPI` includes a built-in semaphore (`max_concurrent`) to prevent API abuse. When extending the library, ensure that high-frequency requests are properly throttled to avoid IP bans.

### Image Sources
The library supports multiple input types (file paths, URLs, bytes, PIL Images, NumPy arrays). Always use `prepare_image_for_api` from `chrome_lens_py.core.image_processor` to normalize inputs before sending them to the API.
