# utils.py

import filetype
import time

from .constants import SUPPORTED_MIMES

def is_supported_mime(file_path):
    """Checks if the file's MIME type is supported."""
    kind = filetype.guess(file_path)
    return kind and kind.mime in SUPPORTED_MIMES

def sleep(ms):
    """Wait function."""
    time.sleep(ms / 1000)
