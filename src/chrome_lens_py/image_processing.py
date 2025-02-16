import io
from PIL import Image
from .exceptions import LensImageError
import numpy as np

def resize_image(image_path, max_size=(1000, 1000)):
    """Resizes the image from a file path and converts it to a format without an alpha channel."""
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise LensImageError(f"Error opening image {image_path}: {e}") from e
    return _resize_and_convert_image(img, image_path, max_size)

def resize_image_from_buffer(buffer, max_size=(1000, 1000)):
    """Resizes the image from a bytes buffer and converts it to a format without an alpha channel."""
    try:
        img = Image.open(io.BytesIO(buffer))
    except Exception as e:
        raise LensImageError(f"Error opening image from buffer: {e}") from e
    return _resize_and_convert_image(img, "buffer", max_size)

def _resize_and_convert_image(img, image_source_name, max_size):
    """Internal function to resize and convert image, used by both file and buffer methods."""
    original_size = img.size
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        img = img.convert('RGB')  # Convert to RGB to remove alpha channel

    img.thumbnail(max_size, Image.Resampling.LANCZOS) # Use LANCZOS for high-quality downsampling
    resized_dimensions = img.size

    img_byte_arr = io.BytesIO()
    try:
        img.save(img_byte_arr, format='JPEG', optimize=True) # Optimize JPEG
    except Exception as e:
        raise LensImageError(f"Error saving resized image {image_source_name} to buffer: {e}") from e

    img_data = img_byte_arr.getvalue()
    return img_data, resized_dimensions, original_size


def image_to_jpeg_buffer(image: Image.Image) -> bytes:
    """Converts a PIL Image object to JPEG bytes buffer."""
    try:
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", optimize=True) # Optimize JPEG here as well
        return buffer.getvalue()
    except Exception as e:
        raise LensImageError(f"Error converting PIL Image to JPEG buffer: {e}") from e

def numpy_array_to_jpeg_buffer(numpy_array: np.ndarray) -> bytes:
    """Converts a NumPy array to JPEG bytes buffer."""
    try:
        image = Image.fromarray(numpy_array) # Convert numpy array to PIL Image
        return image_to_jpeg_buffer(image)   # Reuse image_to_jpeg_buffer
    except Exception as e:
        raise LensImageError(f"Error converting NumPy array to JPEG buffer: {e}") from e