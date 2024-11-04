import os
import sys  # Добавили импорт модуля sys
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

def get_default_config_dir(app_name):
    """Returns the default configuration directory path for the application."""
    home_dir = os.path.expanduser('~')
    if sys.platform.startswith('win'):
        # Windows - use ~/.config directory in the user's home directory
        config_dir = os.path.join(home_dir, '.config', app_name)
    elif sys.platform == 'darwin':
        # macOS - use ~/Library/Application Support
        config_dir = os.path.expanduser(f'~/Library/Application Support/{app_name}')
    else:
        # Unix/Linux - use XDG_CONFIG_HOME or default to ~/.config
        config_dir = os.path.join(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), app_name)
    return config_dir
