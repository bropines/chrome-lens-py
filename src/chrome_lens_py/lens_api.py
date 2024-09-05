from .request_handler import Lens
from .text_processing import simplify_output, extract_full_text, stitch_text_smart, stitch_text_sequential
from .exceptions import LensAPIError, LensParsingError


class LensAPI:
    def __init__(self, config=None, sleep_time=1000):
        self.lens = Lens(config=config, sleep_time=sleep_time)

    def get_all_data(self, file_path):
        """Returns all data for the image."""
        try:
            result = self.lens.scan_by_file(file_path)
            return simplify_output(result)
        except (LensAPIError, LensParsingError) as e:
            raise LensAPIError(
                f"Error getting all data from image: {e}") from e

    def get_full_text(self, file_path):
        """Returns the full text from the image."""
        try:
            result = self.lens.scan_by_file(file_path)
            return extract_full_text(result['data'])
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(
                f"Error getting full text from image: {e}") from e

    def get_text_with_coordinates(self, file_path):
        """Returns text with coordinates in JSON format."""
        try:
            result = self.lens.scan_by_file(file_path)
            simplified_result = simplify_output(result)
            return simplified_result['text_with_coordinates']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(
                f"Error getting text with coordinates from image: {e}") from e

    def get_stitched_text_smart(self, file_path):
        """Returns stitched text using the smart method."""
        try:
            result = self.lens.scan_by_file(file_path)
            simplified_result = simplify_output(result)
            return simplified_result['stitched_text_smart']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(
                f"Error getting stitched text (smart method) from image: {e}") from e

    def get_stitched_text_sequential(self, file_path):
        """Returns stitched text using the sequential method."""
        try:
            result = self.lens.scan_by_file(file_path)
            simplified_result = simplify_output(result)
            return simplified_result['stitched_text_sequential']
        except (LensAPIError, LensParsingError, KeyError) as e:
            raise LensAPIError(
                f"Error getting stitched text (sequential method) from image: {e}") from e
