import io
import logging
import math
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFont

from ..constants import DEFAULT_IMAGE_MAX_DIMENSION
from ..exceptions import LensImageError
from ..utils.font_manager import FontType
from ..utils.general import is_url

if TYPE_CHECKING:
    from ..utils.lens_betterproto import CenterRotatedBox, CoordinateType
else:
    from ..utils.lens_betterproto import CenterRotatedBox, CoordinateType

ImageFile.LOAD_TRUNCATED_IMAGES = True
logger = logging.getLogger(__name__)


async def _get_pil_from_source(image_source: Any) -> Image.Image:
    """
    Takes any supported source and returns a PIL.Image object.
    Raises LensImageError if the source is unsupported or an error occurs.
    """
    if isinstance(image_source, Image.Image):
        logger.debug("Processing PIL.Image object source.")
        return image_source.copy()

    if isinstance(image_source, str):
        if is_url(image_source):
            logger.debug(f"Processing URL source: {image_source}")
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(image_source, follow_redirects=True)
                    response.raise_for_status()
                return Image.open(io.BytesIO(response.content))
            except httpx.RequestError as e:
                raise LensImageError(
                    f"Network error downloading URL '{image_source}': {e}"
                ) from e
            except Exception as e:
                raise LensImageError(
                    f"Error processing URL '{image_source}': {e}"
                ) from e
        else:  # It's a file path
            logger.debug(f"Processing file path source: {image_source}")
            try:
                return Image.open(image_source)
            except FileNotFoundError:
                raise LensImageError(f"File not found at path: {image_source}")
            except Exception as e:
                raise LensImageError(
                    f"Error opening file path '{image_source}': {e}"
                ) from e

    if isinstance(image_source, np.ndarray):
        logger.debug("Processing NumPy array source.")
        try:
            return Image.fromarray(image_source)
        except Exception as e:
            raise LensImageError(f"Error converting NumPy array to image: {e}") from e

    if isinstance(image_source, bytes):
        logger.debug("Processing bytes source.")
        try:
            return Image.open(io.BytesIO(image_source))
        except Exception as e:
            raise LensImageError(f"Error opening image from bytes: {e}") from e

    raise LensImageError(f"Unsupported image source type: {type(image_source)}")


def _resize_and_serialize_pil_image(pil_image: Image.Image) -> Tuple[bytes, int, int]:
    """Resizes (if necessary) and serializes a PIL.Image to PNG bytes."""
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")

    if (
        pil_image.width > DEFAULT_IMAGE_MAX_DIMENSION
        or pil_image.height > DEFAULT_IMAGE_MAX_DIMENSION
    ):
        pil_image.thumbnail(
            (DEFAULT_IMAGE_MAX_DIMENSION, DEFAULT_IMAGE_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )

    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="PNG")

    return img_byte_arr.getvalue(), pil_image.width, pil_image.height


async def prepare_image_for_api(
    image_source: Any,
) -> Tuple[bytes, int, int, Image.Image]:
    """
    Main preparation function. Takes any source, processes it, and returns API-ready data and the original image.
    """
    try:
        pil_image = await _get_pil_from_source(image_source)
        original_pil_image = pil_image.copy()
        img_bytes, width, height = _resize_and_serialize_pil_image(pil_image)
        return img_bytes, width, height, original_pil_image
    except LensImageError as e:
        raise e
    except Exception as e:
        raise LensImageError(
            f"An unexpected error occurred during image preparation: {e}"
        ) from e


def get_word_geometry_data(box: "CenterRotatedBox") -> Optional[Dict[str, Any]]:
    """Extracts detailed, user-friendly geometry data from a CenterRotatedBox object."""
    if not (hasattr(box, "center_x") and hasattr(box, "center_y")):
        return None

    angle_rad = getattr(box, "rotation_z", 0.0)
    angle_deg = math.degrees(angle_rad)

    coord_type_enum = getattr(box, "coordinate_type", 0)
    coord_type_str = "NORMALIZED" if coord_type_enum == 1 else "IMAGE"

    return {
        "center_x": box.center_x,
        "center_y": box.center_y,
        "width": getattr(box, "width", 0.0),
        "height": getattr(box, "height", 0.0),
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
            logger.warning(f"Could not draw line '{line_str}': {e}")
            if hasattr(font, "size"):
                line_height = font.size  # type: ignore [attr-defined]
            else:
                line_height = 12
            current_y += line_height + line_spacing
            continue

    return img_draw
