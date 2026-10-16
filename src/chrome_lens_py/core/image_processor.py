import asyncio
import contextlib
import io
import logging
import math
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional, Tuple

import httpx
from PIL import Image, ImageDraw, ImageFile, ImageStat, features

from ..constants import (
    DEFAULT_ALPHA_MODE,
    DEFAULT_IMAGE_JPEG_QUALITY,
    DEFAULT_IMAGE_MAX_AREA,
    DEFAULT_IMAGE_MAX_HEIGHT,
    DEFAULT_IMAGE_MAX_WIDTH,
    DEFAULT_IMAGE_WEBP_QUALITY,
)
from ..exceptions import LensImageError
from ..utils.font_manager import FontType
from ..utils.general import is_url

if TYPE_CHECKING:
    from ..utils.lens_betterproto import CenterRotatedBox

logger = logging.getLogger(__name__)

MIME_JPEG = "image/jpeg"
MIME_WEBP = "image/webp"

ALPHA_MODES = ("webp", "flatten", "contrast")


@contextlib.contextmanager
def _allow_truncated_images():
    """Scope Pillow's truncated-image tolerance to our own decodes.

    Setting ImageFile.LOAD_TRUNCATED_IMAGES at import time changed behaviour for
    the entire host process, including code that never asked for it.
    """
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        yield
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


def _is_numpy_array(obj: Any) -> bool:
    """Detect ndarray without importing numpy.

    numpy costs ~75 ms of import time and was only ever needed for this check,
    which matters for a CLI that ShareX launches per screenshot.
    """
    return type(obj).__module__.split(".")[0] == "numpy" and hasattr(
        obj, "__array_interface__"
    )


def _open_and_load(fp: Any) -> Image.Image:
    with _allow_truncated_images():
        img = Image.open(fp)
        img.load()
    return img


def _load_local(image_source: Any) -> Image.Image:
    """Blocking decode of everything that is not a URL (run in a worker thread)."""
    if isinstance(image_source, Image.Image):
        logger.debug("Processing PIL.Image object source.")
        return image_source.copy()

    if isinstance(image_source, str):
        logger.debug("Processing file path source: %s", image_source)
        try:
            return _open_and_load(image_source)
        except FileNotFoundError:
            raise LensImageError(f"File not found at path: {image_source}")
        except Exception as e:
            raise LensImageError(
                f"Error opening file path '{image_source}': {e}"
            ) from e

    if _is_numpy_array(image_source):
        logger.debug("Processing NumPy array source.")
        try:
            return Image.fromarray(image_source)
        except Exception as e:
            raise LensImageError(f"Error converting NumPy array to image: {e}") from e

    if isinstance(image_source, (bytes, bytearray, memoryview)):
        logger.debug("Processing bytes source.")
        try:
            return _open_and_load(io.BytesIO(bytes(image_source)))
        except Exception as e:
            raise LensImageError(f"Error opening image from bytes: {e}") from e

    raise LensImageError(f"Unsupported image source type: {type(image_source)}")


async def _download(url: str, client: Optional[httpx.AsyncClient]) -> bytes:
    logger.debug("Processing URL source: %s", url)
    try:
        if client is not None:
            # Reuse the API client so --proxy / trust_env apply here too.
            response = await client.get(url, follow_redirects=True)
        else:
            async with httpx.AsyncClient(timeout=30) as fallback:
                response = await fallback.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except httpx.RequestError as e:
        raise LensImageError(f"Network error downloading URL '{url}': {e}") from e
    except Exception as e:
        raise LensImageError(f"Error processing URL '{url}': {e}") from e


async def load_image(
    image_source: Any, client: Optional[httpx.AsyncClient] = None
) -> Image.Image:
    """Any supported source -> a PIL image that the caller owns.

    Decoding runs in a worker thread so a large image does not stall the event
    loop (and with it every other request in the daemon). Raises LensImageError
    if the source is unsupported or cannot be decoded.
    """
    if isinstance(image_source, str) and is_url(image_source):
        content = await _download(image_source, client)
        try:
            return await asyncio.to_thread(_open_and_load, io.BytesIO(content))
        except Exception as e:
            raise LensImageError(f"Error processing URL '{image_source}': {e}") from e
    return await asyncio.to_thread(_load_local, image_source)


# Kept under its old name for callers that imported the private helper.
_get_pil_from_source = load_image


def should_downscale(width: int, height: int) -> bool:
    """Chromium's rule: shrink only when the image is both large and oversized.

    Mirrors lens::ShouldDownscaleSize in components/lens/lens_bitmap_processing.cc.
    The previous unconditional thumbnail(1500) shrank images Chromium keeps at
    full resolution (a 1600x900 screenshot, say), losing OCR detail for nothing.
    """
    return width * height > DEFAULT_IMAGE_MAX_AREA and (
        width > DEFAULT_IMAGE_MAX_WIDTH or height > DEFAULT_IMAGE_MAX_HEIGHT
    )


def _preferred_size(width: int, height: int) -> Tuple[int, int]:
    scale = min(
        DEFAULT_IMAGE_MAX_WIDTH / width,
        DEFAULT_IMAGE_MAX_HEIGHT / height,
    )
    return max(1, int(width * scale)), max(1, int(height * scale))


class EncodedImage(NamedTuple):
    """An upload-ready image: bytes plus what the request must say about them."""

    data: bytes
    width: int
    height: int
    mime_type: str


def has_meaningful_alpha(pil_image: Image.Image) -> bool:
    """True if any pixel is not fully opaque.

    Mirrors Chromium's SkBitmap::isOpaque() test: an RGBA screenshot whose alpha
    channel is solid 255 is, for upload purposes, an opaque image.
    """
    mode = pil_image.mode
    if mode in ("RGBA", "LA", "PA"):
        alpha = pil_image.getchannel("A")
    elif mode in ("P", "RGB", "L") and "transparency" in pil_image.info:
        # Palette or colour-key transparency only shows up on conversion.
        alpha = pil_image.convert("RGBA").getchannel("A")
    else:
        return False
    extrema: Tuple[int, int] = alpha.getextrema()  # type: ignore[assignment]
    return extrema[0] < 255


def _webp_available() -> bool:
    return bool(features.check("webp"))


def _flatten(pil_image: Image.Image, background: Tuple[int, int, int]) -> Image.Image:
    rgba = pil_image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, background)
    flattened.paste(rgba, mask=rgba.split()[-1])
    return flattened


def _contrasting_background(pil_image: Image.Image) -> Tuple[int, int, int]:
    """White behind dark content, black behind light content.

    The server composites a transparent upload onto black (checked live: black
    text on a transparent PNG reads back empty, white text reads fine), so an
    unconditional white flatten loses white text and an unconditional black one
    loses dark text. Picking by the mean luminance of the opaque pixels keeps both.
    """
    rgba = pil_image.convert("RGBA")
    mask = rgba.getchannel("A").point(lambda a: 255 if a > 128 else 0)
    if mask.getextrema()[1] == 0:
        return (255, 255, 255)
    mean = ImageStat.Stat(rgba.convert("L"), mask=mask).mean[0]
    return (255, 255, 255) if mean < 128 else (0, 0, 0)


def encode_image_for_api(
    pil_image: Image.Image,
    jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY,
    webp_quality: int = DEFAULT_IMAGE_WEBP_QUALITY,
    alpha_mode: str = DEFAULT_ALPHA_MODE,
) -> EncodedImage:
    """Downscale if needed and encode the way Chromium does.

    Chromium's lens overlay sends JPEG at quality 40
    (kLensOverlayImageCompressionQuality), except that an image which really
    uses transparency goes up as WebP at quality 40 with its alpha intact. We
    used to flatten those onto white, which erases e.g. white text on a
    transparent PNG.

    ``alpha_mode`` decides what happens to an image with real transparency:
    "webp" (Chromium's behaviour), "flatten" (JPEG on white) or "contrast"
    (JPEG on white or black, whichever the content stands out against). The
    server drops the alpha channel by compositing onto black, so "webp" cannot
    read dark text on a transparent background; see ``_contrasting_background``.

    CPU-bound: call it through ``asyncio.to_thread`` from async code.
    """
    if should_downscale(pil_image.width, pil_image.height):
        target = _preferred_size(pil_image.width, pil_image.height)
        pil_image = pil_image.resize(target, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    if has_meaningful_alpha(pil_image):
        if alpha_mode == "webp" and _webp_available():
            rgba = pil_image if pil_image.mode == "RGBA" else pil_image.convert("RGBA")
            rgba.save(buffer, format="WEBP", quality=webp_quality)
            return EncodedImage(buffer.getvalue(), rgba.width, rgba.height, MIME_WEBP)
        # JPEG has no alpha. White is what a browser would have shown behind
        # the image anyway.
        background = (
            _contrasting_background(pil_image)
            if alpha_mode == "contrast"
            else (255, 255, 255)
        )
        pil_image = _flatten(pil_image, background)
    elif pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")

    pil_image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    return EncodedImage(buffer.getvalue(), pil_image.width, pil_image.height, MIME_JPEG)


def _resize_and_serialize_pil_image(
    pil_image: Image.Image, jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY
) -> Tuple[bytes, int, int]:
    """JPEG-only encode (used for crops, which carry no format field)."""
    encoded = encode_image_for_api(pil_image, jpeg_quality, alpha_mode="flatten")
    return encoded.data, encoded.width, encoded.height


async def prepare_image(
    image_source: Any,
    client: Optional[httpx.AsyncClient] = None,
    keep_original: bool = True,
    jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY,
    webp_quality: int = DEFAULT_IMAGE_WEBP_QUALITY,
    alpha_mode: str = DEFAULT_ALPHA_MODE,
) -> Tuple[EncodedImage, Optional[Image.Image], Tuple[int, int]]:
    """Load and encode an image, off the event loop.

    Returns the encoded upload, if ``keep_original`` the decoded source for
    overlay rendering (no copy is needed: encoding never mutates it), and the
    source's (width, height) before any downscaling.
    """
    try:
        pil_image = await load_image(image_source, client=client)
        encoded = await asyncio.to_thread(
            encode_image_for_api, pil_image, jpeg_quality, webp_quality, alpha_mode
        )
        return (
            encoded,
            (pil_image if keep_original else None),
            (pil_image.width, pil_image.height),
        )
    except LensImageError:
        raise
    except Exception as e:
        raise LensImageError(
            f"An unexpected error occurred during image preparation: {e}"
        ) from e


async def prepare_image_for_api(
    image_source: Any,
    client: Optional[httpx.AsyncClient] = None,
    keep_original: bool = True,
    jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY,
) -> Tuple[bytes, int, int, Optional[Image.Image]]:
    """JPEG-only variant of ``prepare_image`` (the pre-WebP return shape)."""
    encoded, original, _ = await prepare_image(
        image_source,
        client=client,
        keep_original=keep_original,
        jpeg_quality=jpeg_quality,
        alpha_mode="flatten",
    )
    return encoded.data, encoded.width, encoded.height, original


def crop_region(
    image: Image.Image,
    region: Tuple[float, float, float, float],
    jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY,
) -> Tuple[bytes, int, int]:
    """Cut a normalized (center_x, center_y, width, height) region and encode it.

    The crop is sent at its native pixel size (only downscaled if it is itself
    huge), so a small region arrives at far higher effective resolution than the
    same pixels would inside a downscaled full image.
    """
    width, height = image.size
    center_x, center_y, region_w, region_h = region

    left = int(round((center_x - region_w / 2) * width))
    top = int(round((center_y - region_h / 2) * height))
    right = int(round((center_x + region_w / 2) * width))
    bottom = int(round((center_y + region_h / 2) * height))

    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right - left < 1 or bottom - top < 1:
        raise LensImageError(
            f"Region {region} is empty within a {width}x{height} image."
        )

    return _resize_and_serialize_pil_image(
        image.crop((left, top, right, bottom)), jpeg_quality=jpeg_quality
    )


def get_word_geometry_data(box: "CenterRotatedBox") -> Optional[Dict[str, Any]]:
    """Extracts detailed, user-friendly geometry data from a CenterRotatedBox object."""
    angle_rad = box.rotation_z
    angle_deg = math.degrees(angle_rad)

    coord_type_enum = box.coordinate_type
    coord_type_str = {1: "NORMALIZED", 2: "IMAGE"}.get(coord_type_enum, "UNSPECIFIED")

    return {
        "center_x": box.center_x,
        "center_y": box.center_y,
        "width": box.width,
        "height": box.height,
        "angle_deg": angle_deg,
        "coordinate_type": coord_type_str,
    }


def draw_overlay_on_image(
    original_image: Image.Image,
    ocr_boxes_norm: list[Tuple[float, float, float, float]],
    translated_text: Optional[str],
    font: FontType,
    fill_color: str = "white",
    text_color: str = "black",
) -> Image.Image:
    """Draws an overlay on the image: fills OCR areas and writes translated text."""
    img_draw = original_image.copy()
    if img_draw.mode != "RGBA":
        img_draw = img_draw.convert("RGBA")
    draw = ImageDraw.Draw(img_draw)
    img_width, img_height = img_draw.size

    if not ocr_boxes_norm:
        return img_draw

    for norm_x1, norm_y1, norm_x2, norm_y2 in ocr_boxes_norm:
        draw.rectangle(
            (
                int(norm_x1 * img_width),
                int(norm_y1 * img_height),
                int(norm_x2 * img_width),
                int(norm_y2 * img_height),
            ),
            fill=fill_color,
        )

    if not translated_text:
        return img_draw

    overall_ocr_min_x = min(b[0] for b in ocr_boxes_norm)
    overall_ocr_min_y = min(b[1] for b in ocr_boxes_norm)
    overall_ocr_max_x = max(b[2] for b in ocr_boxes_norm)
    overall_ocr_max_y = max(b[3] for b in ocr_boxes_norm)

    px_overall_x1 = int(overall_ocr_min_x * img_width)
    px_overall_y1 = int(overall_ocr_min_y * img_height)
    px_overall_x2 = int(overall_ocr_max_x * img_width)
    px_overall_y2 = int(overall_ocr_max_y * img_height)

    overlay_width_px = px_overall_x2 - px_overall_x1
    if overlay_width_px <= 0:
        return img_draw

    padding = 4
    available_width_for_text = overlay_width_px - 2 * padding
    if available_width_for_text <= 0:
        return img_draw

    lines_to_draw = []
    current_line = ""
    for word in translated_text.split():
        test_line = f"{current_line} {word}".strip()
        try:
            line_width = draw.textlength(test_line, font=font)
        except AttributeError:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

        if line_width <= available_width_for_text:
            current_line = test_line
        else:
            if current_line:
                lines_to_draw.append(current_line)
            current_line = word
    if current_line:
        lines_to_draw.append(current_line)

    current_y: float = px_overall_y1 + padding
    line_spacing = 2
    for line_str in lines_to_draw:
        try:
            bbox = draw.textbbox((0, 0), line_str, font=font)
            line_height = bbox[3] - bbox[1]
            line_width = bbox[2] - bbox[0]

            if current_y + line_height > px_overall_y2 - padding:
                break

            pos_x = px_overall_x1 + (overlay_width_px - line_width) / 2
            draw.text(
                (pos_x, current_y),
                line_str,
                fill=text_color,
                font=font,
            )
            current_y += line_height + line_spacing
        except Exception as e:
            logger.warning("Could not draw line '%s': %s", line_str, e)
            fallback_height: float = getattr(font, "size", 12)
            current_y += fallback_height + line_spacing
            continue

    return img_draw
