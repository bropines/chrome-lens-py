# lens_api.py

from .request_handler import Lens
from .text_processing import simplify_output, extract_full_text, stitch_text_smart, stitch_text_sequential

class LensAPI:
    def __init__(self, config=None, sleep_time=1000):
        self.lens = Lens(config=config, sleep_time=sleep_time)

    def get_all_data(self, file_path):
        """Возвращает все данные для изображения"""
        result = self.lens.scan_by_file(file_path)
        return simplify_output(result)

    def get_full_text(self, file_path):
        """Возвращает полный текст"""
        result = self.lens.scan_by_file(file_path)
        return extract_full_text(result['data'])

    def get_text_with_coordinates(self, file_path):
        """Возвращает текст с координатами в формате JSON"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['text_with_coordinates']

    def get_stitched_text_smart(self, file_path):
        """Возвращает сшитый текст (умный метод)"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['stitched_text_smart']

    def get_stitched_text_sequential(self, file_path):
        """Возвращает сшитый текст (последовательный метод)"""
        result = self.lens.scan_by_file(file_path)
        simplified_result = simplify_output(result)
        return simplified_result['stitched_text_sequential']
