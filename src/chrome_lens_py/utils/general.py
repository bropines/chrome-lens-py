import os
import logging
from typing import Optional

# filetype используется для определения MIME по содержимому, но для prepare_image_for_api мы больше полагаемся на Pillow.
# Оставим его для возможного использования в CLI для быстрой проверки перед передачей в Pillow.
import filetype

from ..constants import SUPPORTED_MIMES_FOR_PREPARE

logger = logging.getLogger(__name__)

def is_image_file_supported(file_path: str) -> bool:
    """
    Проверяет, является ли файл изображением, которое Pillow вероятно сможет открыть.
    Использует filetype для быстрой проверки MIME.
    """
    if not os.path.isfile(file_path):
        return False
    try:
        kind = filetype.guess(file_path)
        if kind and kind.mime in SUPPORTED_MIMES_FOR_PREPARE:
            return True
        # Если filetype не определил, или MIME не в нашем списке,
        # можно дополнительно проверить по расширению как fallback
        ext = os.path.splitext(file_path)[1].lower()
        # Простые проверки расширений, которые Pillow обычно поддерживает
        pillow_common_exts = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff']
        if ext in pillow_common_exts:
            logger.debug(f"File '{file_path}' has a common Pillow extension '{ext}', assuming supported.")
            return True

    except Exception as e:
        logger.warning(f"Error guessing file type for '{file_path}': {e}")
    return False