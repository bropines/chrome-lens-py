import logging
import os
from urllib.parse import urlparse

import filetype  # type: ignore

from ..constants import SUPPORTED_MIMES_FOR_PREPARE

logger = logging.getLogger(__name__)


def is_url(string: str) -> bool:
    """Проверяет, является ли строка валидным URL."""
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except (ValueError, AttributeError):
        return False


def is_image_file_supported(path_or_url: str) -> bool:
    """
    Checks if the string is a URL or a supported image file.
    Used in the CLI for quick validation before passing to the API.
    """
    if is_url(path_or_url):
        logger.debug(
            f"'{path_or_url}' is a URL, assuming it's a valid image source for the API."
        )
        return True

    if not os.path.isfile(path_or_url):
        return False

    try:
        kind = filetype.guess(path_or_url)
        if kind and kind.mime in SUPPORTED_MIMES_FOR_PREPARE:
            return True

        ext = os.path.splitext(path_or_url)[1].lower()
        pillow_common_exts = [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".webp",
            ".tif",
            ".tiff",
        ]
        if ext in pillow_common_exts:
            logger.debug(
                f"File '{path_or_url}' has a common Pillow extension '{ext}', assuming supported."
            )
            return True

    except Exception as e:
        logger.warning(f"Could not guess file type for '{path_or_url}': {e}")
        return True

    return False
