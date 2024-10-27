import io
from PIL import Image
from .exceptions import LensImageError

def resize_image(image_path, max_size=(1000, 1000)):
    """Resizes the image from a file path and converts it to a format without an alpha channel."""
    try:
        with Image.open(image_path) as img:
            original_size = img.size  # Сохраняем размеры исходного изображения
            img.thumbnail(max_size)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            return buffer.getvalue(), img.size, original_size  # Возвращаем также original_size
    except (IOError, OSError, ValueError) as e:
        raise LensImageError(f"Error resizing image: {e}") from e

def resize_image_from_buffer(buffer, max_size=(1000, 1000)):
    """Resizes the image from a bytes buffer and converts it to a format without an alpha channel."""
    try:
        img = Image.open(io.BytesIO(buffer))  # Open image from bytes buffer
        original_size = img.size  # Сохраняем размеры исходного изображения
        img.thumbnail(max_size)
        if img.mode == 'RGBA':
            img = img.convert('RGB')  # Convert to RGB to remove alpha channel
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG")  # Save processed image to buffer
        return output_buffer.getvalue(), img.size, original_size  # Возвращаем также original_size
    except (IOError, OSError, ValueError) as e:
        raise LensImageError(f"Error resizing image from buffer: {e}") from e
