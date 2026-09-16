import contextlib
import io
import logging
import math
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import httpx
from PIL import Image, ImageDraw, ImageFile, ImageFont

from ..constants import (
    DEFAULT_IMAGE_JPEG_QUALITY,
    DEFAULT_IMAGE_MAX_AREA,
    DEFAULT_IMAGE_MAX_HEIGHT,
    DEFAULT_IMAGE_MAX_WIDTH,
)
from ..exceptions import LensImageError
from ..utils.font_manager import FontType
from ..utils.general import is_url

if TYPE_CHECKING:
    from ..utils.lens_betterproto import CenterRotatedBox, CoordinateType

logger = logging.getLogger(__name__)


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


async def _get_pil_from_source(
    image_source: Any, client: Optional[httpx.AsyncClient] = None
) -> Image.Image:
    """
    Takes any supported source and returns a PIL.Image object.
    Raises LensImageError if the source is unsupported or an error occurs.
    """
    if isinstance(image_source, Image.Image):
        logger.debug("Processing PIL.Image object source.")
        return image_source.copy()

    if isinstance(image_source, str):
        if is_url(image_source):
            logger.debug("Processing URL source: %s", image_source)
            try:
                if client is not None:
                    # Reuse the API client so --proxy / trust_env apply here too.
                    response = await client.get(image_source, follow_redirects=True)
                    response.raise_for_status()
                    content = response.content
                else:
                    async with httpx.AsyncClient(timeout=30) as fallback:
                        response = await fallback.get(
                            image_source, follow_redirects=True
                        )
                        response.raise_for_status()
                        content = response.content
                return _open_and_load(io.BytesIO(content))
            except httpx.RequestError as e:
                raise LensImageError(
                    f"Network error downloading URL '{image_source}': {e}"
                ) from e
            except Exception as e:
                raise LensImageError(
                    f"Error processing URL '{image_source}': {e}"
                ) from e
        else:  # It's a file path
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


def _resize_and_serialize_pil_image(
    pil_image: Image.Image, jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY
) -> Tuple[bytes, int, int]:
    """Downscale if needed and encode as JPEG, the way Chromium does.

    Chromium sends JPEG at quality 40 (kLensOverlayImageCompressionQuality).
    The old PNG-of-RGBA path produced roughly 2x larger payloads on a typical
    screenshot for no accuracy gain.
    """
    if should_downscale(pil_image.width, pil_image.height):
        target = _preferred_size(pil_image.width, pil_image.height)
        pil_image = pil_image.resize(target, Image.Resampling.LANCZOS)

    if pil_image.mode in ("RGBA", "LA", "PA") or (
        pil_image.mode == "P" and "transparency" in pil_image.info
    ):
        # JPEG has no alpha; flatten onto white, which is what a browser would
        # have shown behind the image anyway.
        rgba = pil_image.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.split()[-1])
        pil_image = flattened
    elif pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")

    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="JPEG", quality=jpeg_quality, optimize=True)

    return img_byte_arr.getvalue(), pil_image.width, pil_image.height


async def prepare_image_for_api(
    image_source: Any,
    client: Optional[httpx.AsyncClient] = None,
    keep_original: bool = True,
    jpeg_quality: int = DEFAULT_IMAGE_JPEG_QUALITY,
) -> Tuple[bytes, int, int, Optional[Image.Image]]:
    """
    Main preparation function. Takes any source, processes it, and returns
    API-ready data plus (optionally) the original image for overlay rendering.
    """
    try:
        pil_image = await _get_pil_from_source(image_source, client=client)
        original_pil_image = pil_image.copy() if keep_original else None
        img_bytes, width, height = _resize_and_serialize_pil_image(
            pil_image, jpeg_quality=jpeg_quality
        )
        return img_bytes, width, height, original_pil_image
    except LensImageError:
        raise
    except Exception as e:
        raise LensImageError(
            f"An unexpected error occurred during image preparation: {e}"
        ) from e


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

    current_y = px_overall_y1 + padding
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
            if hasattr(font, "size"):
                line_height = font.size  # type: ignore [attr-defined]
            else:
                line_height = 12
            current_y += line_height + line_spacing
            continue

    return img_draw
