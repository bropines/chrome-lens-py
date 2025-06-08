import os
import logging
from urllib.parse import urlparse
import filetype # type: ignore

from ..constants import SUPPORTED_MIMES_FOR_PREPARE

logger = logging.getLogger(__name__)

def is_url(string: str) -> bool:
    """Проверяет, является ли строка валидным URL."""
    try:
        result = urlparse(string)
        # Проверяем наличие схемы (http, https) и сетевой локации (домена)
        return all([result.scheme, result.netloc])
    except (ValueError, AttributeError):
        return False

def is_image_file_supported(path_or_url: str) -> bool:
    """
    Проверяет, является ли строка URL или поддерживаемым файлом изображения.
    Используется в CLI для быстрой проверки перед передачей в API.
    """
    if is_url(path_or_url):
        # Для URL мы просто предполагаем, что он ведет на изображение.
        logger.debug(f"'{path_or_url}' is a URL, assuming it's a valid image source for the API.")
        return True

    if not os.path.isfile(path_or_url):
        # Если это не URL и не существующий файл, то источник не поддерживается
        return False
        
    # Если это путь к файлу, проверяем его тип
    try:
        kind = filetype.guess(path_or_url)
        if kind and kind.mime in SUPPORTED_MIMES_FOR_PREPARE:
            return True
        
        # Fallback на расширение, если filetype не справился
        ext = os.path.splitext(path_or_url)[1].lower()
        pillow_common_exts = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff']
        if ext in pillow_common_exts:
            logger.debug(f"File '{path_or_url}' has a common Pillow extension '{ext}', assuming supported.")
            return True
            
    except Exception as e:
        logger.warning(f"Could not guess file type for '{path_or_url}': {e}")
        # Если filetype падает, все равно можем положиться на Pillow, возвращаем True, если это файл
        return True # Pillow может быть умнее
        
    return False