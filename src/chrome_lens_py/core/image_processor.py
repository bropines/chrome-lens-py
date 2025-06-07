import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFile

from ..constants import DEFAULT_IMAGE_MAX_DIMENSION
from ..exceptions import LensImageError
# Импортируем типы Protobuf напрямую для аннотаций, если lens_betterproto доступен глобально,
# иначе можно использовать строковые аннотации или typing.TYPE_CHECKING
try:
    from ..lens_betterproto import CenterRotatedBox, CoordinateType
except ImportError:
    # Оставляем типы как строки, если lens_betterproto.py не найден на этапе статического анализа
    # Это не повлияет на исполнение, если файл будет доступен в рантайме.
    CenterRotatedBox = "CenterRotatedBox" # type: ignore
    CoordinateType = "CoordinateType" # type: ignore


ImageFile.LOAD_TRUNCATED_IMAGES = True
logger = logging.getLogger(__name__)

def prepare_image_for_api(
    image_path: str, max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION
) -> Tuple[bytes, int, int, Image.Image]:
    """
    Подготавливает изображение для отправки в API.
    Читает, конвертирует в RGBA, изменяет размер (если необходимо) и сериализует в PNG байты.
    Возвращает байты изображения, его ширину, высоту и оригинальный PIL Image объект.
    """
    try:
        pil_image = Image.open(image_path)
        original_pil_image = pil_image.copy() # Сохраняем копию для наложения

        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')

        current_width, current_height = pil_image.size

        if current_width > max_dimension or current_height > max_dimension:
            pil_image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            logger.debug(f"Image resized from {current_width}x{current_height} to {pil_image.size[0]}x{pil_image.size[1]}")
            current_width, current_height = pil_image.size
        else:
            logger.debug(f"Image size {current_width}x{current_height} is within limits, no resize needed.")

        img_byte_arr = io.BytesIO()
        pil_image.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()

        return img_bytes, current_width, current_height, original_pil_image
    except FileNotFoundError:
        logger.error(f"Image file not found: {image_path}")
        raise LensImageError(f"Файл изображения не найден: {image_path}")
    except Exception as e:
        logger.error(f"Error preparing image '{image_path}': {e}", exc_info=True)
        raise LensImageError(f"Ошибка при подготовке изображения '{image_path}': {e}")


def get_normalized_rect_from_box(box: CenterRotatedBox) -> Optional[Tuple[float, float, float, float]]:
    """Извлекает нормализованные координаты (x1, y1, x2, y2) из CenterRotatedBox."""
    if box.coordinate_type == CoordinateType.NORMALIZED:
        center_x, center_y, norm_width, norm_height = box.center_x, box.center_y, box.width, box.height
        x1 = center_x - norm_width / 2
        y1 = center_y - norm_height / 2
        x2 = center_x + norm_width / 2
        y2 = center_y + norm_height / 2
        return (x1, y1, x2, y2)
    logger.warning(f"Bounding box has unexpected coordinate type: {box.coordinate_type}. Expected NORMALIZED.")
    return None

def draw_overlay_on_image(
    original_image: Image.Image,
    ocr_boxes_norm: list[Tuple[float, float, float, float]],
    translated_text: Optional[str],
    font: ImageFont.FreeTypeFont,
    fill_color: str = "white",
    text_color: str = "black"
) -> Image.Image:
    """
    Рисует наложение на изображение: закрашивает OCR области и пишет переведенный текст.
    """
    img_draw = original_image.copy()
    if img_draw.mode != 'RGBA':
        img_draw = img_draw.convert('RGBA')
    draw = ImageDraw.Draw(img_draw)
    img_width, img_height = img_draw.size

    if not ocr_boxes_norm:
        logger.info("No OCR boxes provided for overlay, returning original image.")
        return img_draw

    # Закрашивание OCR областей
    for norm_x1, norm_y1, norm_x2, norm_y2 in ocr_boxes_norm:
        px_x1, px_y1 = int(norm_x1 * img_width), int(norm_y1 * img_height)
        px_x2, px_y2 = int(norm_x2 * img_width), int(norm_y2 * img_height)
        draw.rectangle([px_x1, px_y1, px_x2, px_y2], fill=fill_color)
    logger.debug(f"Filled {len(ocr_boxes_norm)} OCR boxes with color '{fill_color}'.")

    if not translated_text:
        logger.info("No translated text provided for overlay.")
        return img_draw

    # Определение общей области OCR для наложения текста
    overall_ocr_min_x = min(b[0] for b in ocr_boxes_norm)
    overall_ocr_min_y = min(b[1] for b in ocr_boxes_norm)
    overall_ocr_max_x = max(b[2] for b in ocr_boxes_norm)
    overall_ocr_max_y = max(b[3] for b in ocr_boxes_norm)

    px_overall_x1 = int(overall_ocr_min_x * img_width)
    px_overall_y1 = int(overall_ocr_min_y * img_height)
    px_overall_x2 = int(overall_ocr_max_x * img_width)
    px_overall_y2 = int(overall_ocr_max_y * img_height)

    overlay_width_px = px_overall_x2 - px_overall_x1
    overlay_height_px = px_overall_y2 - px_overall_y1

    if overlay_width_px <= 0 or overlay_height_px <= 0:
        logger.warning("Could not determine overall OCR area for text overlay. Text will not be drawn.")
        return img_draw

    # Адаптивная логика для переноса текста и отрисовки (упрощенная)
    # Используем возможности textbbox для более точного расчета
    import textwrap
    padding = 2 # Небольшой отступ от краев

    # Попытка оценить количество символов на строку
    try:
        # Пытаемся получить ширину одного символа для грубой оценки
        # (может быть неточно для пропорциональных шрифтов)
        if hasattr(font, "getbbox"): # Новый Pillow
            char_width_approx = font.getbbox("A")[2] - font.getbbox("A")[0]
        elif hasattr(font, "getsize"): # Старый Pillow
            char_width_approx = font.getsize("A")[0]
        else: # Очень старый Pillow
             char_width_approx = font.size * 0.6
        if char_width_approx <= 0: char_width_approx = font.size * 0.6 # fallback

        chars_per_line_approx = max(1, int((overlay_width_px - 2 * padding) / char_width_approx))
    except Exception:
        chars_per_line_approx = 30 # Безопасное значение по умолчанию

    wrapped_text_lines = textwrap.wrap(translated_text, width=chars_per_line_approx, replace_whitespace=False)

    current_y = px_overall_y1 + padding
    for line_str in wrapped_text_lines:
        if not line_str.strip(): # Пропускаем пустые строки после textwrap
            continue
        try:
            if hasattr(draw, "textbbox"): # Новый Pillow
                text_bbox = draw.textbbox((0, 0), line_str, font=font)
                line_width_px = text_bbox[2] - text_bbox[0]
                line_height_px = text_bbox[3] - text_bbox[1]
            elif hasattr(font, "getsize"): # Старый Pillow
                size = font.getsize(line_str)
                line_width_px = size[0]
                line_height_px = size[1]
            else: # Очень старый Pillow
                 line_width_px = len(line_str) * font.size * 0.6
                 line_height_px = font.size


            if current_y + line_height_px > px_overall_y2 - padding:
                logger.warning(f"Text line '{line_str[:20]}...' does not fit in overlay area. Stopping draw.")
                break

            pos_x = px_overall_x1 + padding
            if line_width_px < overlay_width_px - 2 * padding: # Центрирование
                pos_x = px_overall_x1 + (overlay_width_px - line_width_px) / 2

            draw.text((pos_x, current_y), line_str, fill=text_color, font=font)
            current_y += line_height_px # + небольшой межстрочный интервал если нужно
        except Exception as e:
            logger.error(f"Error drawing text line '{line_str}': {e}", exc_info=True)
            # Продолжаем со следующей строкой, если одна не удалась

    logger.debug(f"Overlayed translated text onto image.")
    return img_draw