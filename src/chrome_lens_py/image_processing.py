# image_processing.py

import io
from PIL import Image
from .utils import is_supported_mime
from .constants import MIME_TO_EXT

def resize_image(image_path, max_size=(1000, 1000)):
    """Изменяет размер изображения и конвертирует его в формат без альфа-канала."""
    with Image.open(image_path) as img:
        img.thumbnail(max_size)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return buffer.getvalue(), img.size
