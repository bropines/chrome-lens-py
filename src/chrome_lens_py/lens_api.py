from .request_handler import Lens
from .text_processing import simplify_output, extract_full_text
from .exceptions import LensAPIError, LensParsingError
from .utils import is_url
import logging

class LensAPI:
    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        self.lens = Lens(config=config, sleep_time=sleep_time, logging_level=logging_level)

    def get_all_data(self, image_source, coordinate_format='percent'):
        """Returns all data for the image, accepting either a file path or a URL."""
        try:
            if is_url(image_source):
                result, original_size = self.lens.scan_by_url(image_source)
            else:
                result, original_size = self.lens.scan_by_file(image_source)
            return simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
        except (LensAPIError, LensParsingError) as e:
            raise LensAPIError(f"Error getting all data from image: {e}") from e

    def get_full_text(self, image_source):
        """Returns the full text from the image."""
        try:
            if is_url(image_source):
                result, _ = self.lens.scan_by_url(image_source)
            else:
                result, _ = self.lens.scan_by_file(image_source)
            return extract_full_text(result['data'])
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(f"Error getting full text from image: {e}") from e

    def get_text_with_coordinates(self, image_source, coordinate_format='percent'):
        """Returns text with coordinates from the image."""
        try:
            if is_url(image_source):
                result, original_size = self.lens.scan_by_url(image_source)
            else:
                result, original_size = self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['text_with_coordinates']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(f"Error getting text with coordinates from image: {e}") from e

    def get_stitched_text_smart(self, image_source, coordinate_format='percent'):
        """Returns stitched text using the smart method from the image."""
        try:
            if is_url(image_source):
                result, original_size = self.lens.scan_by_url(image_source)
            else:
                result, original_size = self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['stitched_text_smart']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(f"Error getting stitched text (smart method) from image: {e}") from e

    def get_stitched_text_sequential(self, image_source, coordinate_format='percent'):
        """Returns stitched text using the sequential method from the image."""
        try:
            if is_url(image_source):
                result, original_size = self.lens.scan_by_url(image_source)
            else:
                result, original_size = self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['stitched_text_sequential']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(f"Error getting stitched text (sequential method) from image: {e}") from e
