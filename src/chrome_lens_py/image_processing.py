import io
from PIL import Image
from .utils import is_supported_mime
from .constants import MIME_TO_EXT
from .exceptions import LensImageError


def resize_image(image_path, max_size=(1000, 1000)):
    """Resizes the image and converts it to a format without an alpha channel."""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(max_size)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            return buffer.getvalue(), img.size
    except (IOError, OSError, ValueError) as e:
        raise LensImageError(f"Error resizing image: {e}") from e
