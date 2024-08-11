# lens_api.py

from .request_handler import Lens
from .text_processing import simplify_output, extract_full_text, stitch_text_smart, stitch_text_sequential

class LensAPI:
    def __init__(self, config=None, sleep_time=1000):
        self.lens = Lens(config=config, sleep_time=sleep_time)

    def get_all_data(self, file_path):
        """Returns all data for the image"""
        result = self.lens.scan_by_file(file_path)
        return simplify_output(result)

    def get_full_text(self, file_path):
        """Returns the full text"""
        result = self.lens.scan_by_file(file_path)
        return extract_full_text(result['data'])

    def get_text_with_coordinates(self, file_path):
        """Returns text with coordinates in JSON format"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['text_with_coordinates']

    def get_stitched_text_smart(self, file_path):
        """Returns stitched text (smart method)"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['stitched_text_smart']

    def get_stitched_text_sequential(self, file_path):
        """Returns stitched text (sequential method)"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['stitched_text_sequential']
