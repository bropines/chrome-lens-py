import filetype
import time
from urllib.parse import urlparse

from .constants import SUPPORTED_MIMES

def is_supported_mime(file_path):
    """Checks if the file's MIME type is supported."""
    kind = filetype.guess(file_path)
    return kind and kind.mime in SUPPORTED_MIMES

def sleep(ms):
    """Sleep function."""
    time.sleep(ms / 1000)

def is_url(string):
    """Checks if the provided string is a URL."""
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False