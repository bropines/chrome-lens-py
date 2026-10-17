# Python API

[Back to the README](../README.md)

`LensAPI` is fully asynchronous. Every method that talks to Google is a coroutine: call it with `await` from an `async` function.

```bash
pip install chrome-lens-py
```

## Contents

- [Quick example](#quick-example)
- [Image sources](#image-sources)
- [Output formats](#output-formats)
- [Constructor](#constructor)
- [process_image](#process_image)
- [process_region](#process_region)
- [Exceptions](#exceptions)

## Quick example

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    async with LensAPI() as api:
        result = await api.process_image(
            "path/to/image.png",
            ocr_language="ja",
            target_translation_language="en",
        )
        print(result["ocr_text"])
        print(result["translated_text"])

asyncio.run(main())
```

`LensAPI` is an async context manager. Leaving the block closes the pooled connections. Without `async with`, call `await api.aclose()` when you are done. No API key is needed: a built-in one is the default.

## Image sources

`process_image` and `process_region` take a **file path** (`str` or `Path`), a **URL**, **bytes**, a **PIL Image** or a **NumPy array**.

```python
from PIL import Image
import numpy as np

async with LensAPI() as api:
    from_url = await api.process_image("https://i.imgur.com/VPd1y6b.png")

    with Image.open("path/to/image.png") as img:
        from_pil = await api.process_image(img)
        from_numpy = await api.process_image(np.array(img))  # e.g. a frame from OpenCV
```

## Output formats

`output_format` chooses how the recognised text comes back. Each value fills a different key of the result.

| `output_format` | Result key | Content |
| :--- | :--- | :--- |
| `'full_text'` (default) | `ocr_text` | One string. |
| `'blocks'` | `text_blocks` | Paragraphs or speech bubbles: `{"text", "lines", "geometry"}`. |
| `'lines'` | `line_blocks` | Single lines: `{"text", "geometry"}`. |
| `'detailed'` | `detailed_blocks` | Paragraphs, each with `lines`, each with `words`; geometry at every level. |

```python
async with LensAPI() as api:
    result = await api.process_image("manga.jpg", output_format="blocks")
    for i, block in enumerate(result["text_blocks"], 1):
        print(f"--- Block #{i} ---")
        print(block["text"])        # block["lines"] and block["geometry"] are there too

    result = await api.process_image("document.png", output_format="lines")
    for line in result["line_blocks"]:
        print(line["text"], line["geometry"])

    result = await api.process_image("document.png", output_format="detailed")
    for block in result["detailed_blocks"]:
        for line in block["lines"]:
            for word in line["words"]:
                print(word["text"], word["geometry"])
```

Geometry is a dict: `center_x`, `center_y`, `width`, `height` (fractions of the image, 0..1) and `angle_deg`.

## Constructor

```python
LensAPI(
    api_key: Union[str, Sequence[str]] = <built-in key>,
    client_region: Optional[str] = None,          # falls back to "US"
    client_time_zone: Optional[str] = None,       # falls back to "America/New_York"
    proxy: Union[str, Dict[str, httpx.AsyncBaseTransport], None] = None,
    timeout: float = 60,
    font_path: Optional[str] = None,
    font_size: Optional[int] = None,
    max_concurrent: int = 10,
    trust_env: bool = True,
    max_retries: int = 2,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    deadline: Optional[float] = None,
    endpoints: Union[str, Sequence[str], None] = None,
    direct_fallback: bool = False,
    alpha_mode: str = "contrast",
)
```

| Parameter | Meaning |
| :--- | :--- |
| `api_key` | One key, or a list tried in order. When a key is rejected (HTTP 401, or 400/403 that names the key) the next one is used and remembered. |
| `client_region`, `client_time_zone` | What the request tells Google about the client. |
| `proxy` | A proxy URL (`http://...`, `socks5://...`) or a dict of httpx transports (mounts). |
| `timeout` | Per-request read timeout in seconds. |
| `font_path`, `font_size` | Font for the [overlay](rendering.md). `font_size` only matters for the `legacy` overlay. |
| `max_concurrent` | How many requests run at once; the rest wait. The CLI passes its `concurrency` setting here (default 5). |
| `trust_env` | Honour `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` from the environment. Set `False` if a stale variable makes requests hang. An explicit `proxy` always wins. |
| `max_retries` | Retries per request for connection errors, timeouts and HTTP 429, 500, 502, 503, 504. |
| `backoff_base`, `backoff_max` | Jittered exponential backoff between retries, in seconds. A `Retry-After` header on 429/503 replaces the computed delay. |
| `deadline` | Wall-clock cap in seconds for one request including all retries and fallbacks. Default: `3 * timeout`. |
| `endpoints` | A URL or a list of URLs, tried in order when a connection fails. Default: `$LENS_ENDPOINT` (comma-separated), else Google's `crupload` endpoint. |
| `direct_fallback` | If the proxy taken from the environment is unreachable, retry once without it. Off by default, because a proxy is often an egress policy. An explicit `proxy` is never bypassed. |
| `alpha_mode` | How to upload an image that really uses transparency. `"contrast"` (default): JPEG on white or black, whichever the content stands out against. `"flatten"`: JPEG on white. `"webp"`: what Chromium does, but the server composites onto black, so dark text on a transparent PNG can read back empty. |

## process_image

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
    # overlay rendering, see rendering.md
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
    return_overlay: bool = False,
    overlay_format: Literal['png', 'webp'] = 'png',
)
```

| Parameter | Meaning |
| :--- | :--- |
| `ocr_language` | BCP 47 code of the text to recognise. Auto-detected if omitted. |
| `target_translation_language`, `source_translation_language` | Translate into / from this language. The source is auto-detected if omitted. |
| `output_overlay_path` | Write the image with the translation painted on it. Needs a translation to exist; if the image has no translated text, no file is written and `overlay_path` is `None`. A file that cannot be written raises `LensImageError`. |
| `new_session` | `True`: every call gets its own session, so concurrent calls do not interfere. `False`: reuse one session; calls on it are serialised. |
| `ocr_preserve_line_breaks` | With `'full_text'`, `False` joins the text into one line. |
| `output_format` | See [Output formats](#output-formats). |
| rendering parameters | Only matter when an overlay is requested. Each has a CLI flag, listed in [rendering.md](rendering.md). |
| `include_raw_response` | Attach the raw protobuf object as `raw_response_objects`. Off by default: it is large and not serialisable. |
| `return_overlay` | Also return the rendered picture as bytes, for callers without a shared disk. |
| `overlay_format` | Encoding of `overlay_image`: `'png'` or `'webp'`. |

### The result dict

| Key | Content |
| :--- | :--- |
| `ocr_text` / `text_blocks` / `line_blocks` / `detailed_blocks` | The recognised text, one of them per `output_format`. |
| `translated_text` | The translation, or `None` if none was requested or found. |
| `word_data` | A list with one entry per recognised word: `word`, `separator`, `geometry`. |
| `detected_language` | Language Lens detected, or `None`. |
| `image_size` | `[width, height]` of the original image in pixels. |
| `objects` | Detected objects with their bounding boxes and segmentation polygons. |
| `translation_render_data` | Per-paragraph data for repainting the translation yourself: translation, languages, writing direction, alignment, and per line the colours, geometry and the server's background patch. |
| `overlay_path` | The path the overlay was written to, or `None`. |
| `overlay_image`, `overlay_mime_type` | Only with `return_overlay=True`: the encoded picture and its MIME type. |
| `raw_response_objects` | Only with `include_raw_response=True`. |

## process_region

Re-reads one region of an image at native resolution. Small print comes back far better than in the full-image pass, which downscales anything over 1600 px.

```python
result: dict = await api.process_region(
    image_path: Any,
    region: Tuple[float, float, float, float],   # center_x, center_y, width, height
    ocr_language: Optional[str] = None,
    text_query: Optional[str] = None,
    ocr_preserve_line_breaks: bool = True,
)
```

`region` is normalised 0..1 against the full image. The method runs the full-image pass first (the server wants a session before a follow-up), then sends only the cropped pixels. Returned geometry is in full-image coordinates, so it lines up with `process_image` output.

```python
async with LensAPI() as api:
    result = await api.process_region("page.png", (0.8, 0.82, 0.35, 0.06))
    print(result["ocr_text"])
```

The result holds `ocr_text`, `line_blocks`, `word_data`, `detected_language`, `region`, `crop_size`, `image_size` and `encoded_response`.

## Exceptions

All are in `chrome_lens_py.exceptions`. `LensAPI`, `LensException`, `LensAPIError`, `LensImageError` and `LensProtobufError` can also be imported from `chrome_lens_py`.

```
LensException
├── LensAPIError            (status_code, response_body)
│   ├── LensRateLimitError  429/503 and the retries ran out (retry_after)
│   ├── LensAuthError       401/403 and no fallback key worked
│   ├── LensTimeoutError    read timeout or the overall deadline
│   └── LensConnectionError DNS, TCP, TLS or proxy failure
├── LensImageError          the image could not be loaded, decoded or the overlay saved
├── LensProtobufError
├── LensFontError
└── LensConfigError         invalid constructor or configuration value
```

Any other failure inside the library is wrapped in `LensException`.

```python
from chrome_lens_py import LensAPI, LensAPIError

try:
    async with LensAPI() as api:
        result = await api.process_image("image.png")
except LensAPIError as e:
    print(e.status_code, e)
```
