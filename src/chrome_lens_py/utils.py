# utils.py

import filetype
import time

from .constants import SUPPORTED_MIMES

def is_supported_mime(file_path):
    """Проверяет, поддерживается ли MIME-тип файла."""
    kind = filetype.guess(file_path)
    return kind and kind.mime in SUPPORTED_MIMES

def sleep(ms):
    """Функция ожидания."""
    time.sleep(ms / 1000)
