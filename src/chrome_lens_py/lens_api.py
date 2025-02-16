from .request_handler import Lens
from .text_processing import simplify_output, extract_full_text
from .exceptions import LensAPIError, LensParsingError
from .utils import is_url, is_supported_mime
from .image_processing import image_to_jpeg_buffer, numpy_array_to_jpeg_buffer
import logging
import os
import time
from PIL import Image
import numpy as np


class LensAPI:
    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING, rate_limit_rpm=None):
        self.lens = Lens(config=config, sleep_time=sleep_time, logging_level=logging_level)
        self.logging_level = logging_level
        self.sleep_time = sleep_time
        self.sleep_between_requests = sleep_time / 1000.0

        # Rate Limiting configuration from API parameter
        if rate_limit_rpm is not None:
            try:
                rate_limit_rpm = int(rate_limit_rpm)
                if not 1 <= rate_limit_rpm <= 40:
                    logging.warning(
                        f"rate_limit_rpm must be between 1 and 40, using default value instead of: {rate_limit_rpm}")
                    rate_limit_rpm = None  # Use default if out of range
            except ValueError:
                logging.warning(
                    f"rate_limit_rpm must be an integer, using default value instead of: {rate_limit_rpm}")
                rate_limit_rpm = None  # Use default if not an integer

            if rate_limit_rpm:
                config = config or {}
                config.setdefault('rate_limiting', {})['max_requests_per_minute'] = rate_limit_rpm

        self.lens = Lens(config=config, sleep_time=sleep_time, logging_level=logging_level)


    def process_batch(self, image_source, method_name, coordinate_format='percent'):
        results = {}
        for filename in os.listdir(image_source):
            file_path = os.path.join(image_source, filename)
            if os.path.isfile(file_path) and is_supported_mime(file_path):
                try:
                    logging.info(f"Processing batch file: {file_path}")
                    method = getattr(self, '_' + method_name + '_single')
                    # Call the method with appropriate arguments
                    result = method(file_path, coordinate_format) # file_path is still a string here
                    results[filename] = result
                    logging.debug(f"Result for {filename}: {result}")
                    time.sleep(self.sleep_between_requests)  # Sleep between requests
                except (LensAPIError, LensParsingError, KeyError) as e:
                    logging.error(f"Error processing {file_path}: {e}")
                    results[filename] = {'error': str(e)}
            else:
                logging.debug(f"Skipping non-image file: {file_path}")
        return results

    def get_all_data(self, image_source, coordinate_format='percent'):
        # if os.path.isdir(image_source):
        #     return self.process_batch(image_source, 'get_all_data', coordinate_format)
        # else:
        return self._get_all_data_single(image_source, coordinate_format)

    async def _get_all_data_single(self, image_source, coordinate_format='percent'):
        try:
            original_size = None
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif is_url(image_source):
                result, original_size = await self.lens.scan_by_url(image_source)
            else: # Assume file path
                result, original_size = await self.lens.scan_by_file(image_source)
            return simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
        except (LensAPIError, LensParsingError) as e:
            logging.error(f"Error getting all data from image: {e}")
            raise LensAPIError(f"Error getting all data from image: {e}") from e

    def get_full_text(self, image_source, coordinate_format='percent'):
        # if os.path.isdir(image_source):
        #     return self.process_batch(image_source, 'get_full_text', coordinate_format)
        # else:
        return self._get_full_text_single(image_source, coordinate_format)

    async def _get_full_text_single(self, image_source, coordinate_format='percent'):
        try:
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(image_source)
                result, _ = await self.lens.scan_by_buffer(image_buffer)
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(image_source)
                result, _ = await self.lens.scan_by_buffer(image_buffer)
            elif is_url(image_source):
                result, _ = await self.lens.scan_by_url(image_source)
            else: # Assume file path
                result, _ = await self.lens.scan_by_file(image_source)
            return extract_full_text(result['data'])
        except (LensAPIError, LensParsingError, KeyError) as e:
            logging.error(f"Error getting full text from image: {e}")
            raise LensAPIError(f"Error getting full text from image: {e}") from e

    def get_text_with_coordinates(self, image_source, coordinate_format='percent'):
        # if os.path.isdir(image_source):
        #     return self.process_batch(image_source, 'get_text_with_coordinates', coordinate_format)
        # else:
        return self._get_text_with_coordinates_single(image_source, coordinate_format)

    async def _get_text_with_coordinates_single(self, image_source, coordinate_format='percent'):
        try:
            original_size = None
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif is_url(image_source):
                result, original_size = await self.lens.scan_by_url(image_source)
            else: # Assume file path
                result, original_size = await self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['text_with_coordinates']
        except (LensAPIError, LensParsingError, KeyError) as e:
            logging.error(f"Error getting text with coordinates from image: {e}")
            raise LensAPIError(f"Error getting text with coordinates from image: {e}") from e

    def get_stitched_text_smart(self, image_source, coordinate_format='percent'):
        # if os.path.isdir(image_source):
        #     return self.process_batch(image_source, 'get_stitched_text_smart', coordinate_format)
        # else:
        return self._get_stitched_text_smart_single(image_source, coordinate_format)

    async def _get_stitched_text_smart_single(self, image_source, coordinate_format='percent'):
        try:
            original_size = None
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif is_url(image_source):
                result, original_size = await self.lens.scan_by_url(image_source)
            else: # Assume file path
                result, original_size = await self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['stitched_text_smart']
        except (LensAPIError, LensParsingError, KeyError) as e:
            logging.error(f"Error getting stitched text (smart method) from image: {e}")
            raise LensAPIError(f"Error getting stitched text (smart method) from image: {e}") from e

    def get_stitched_text_sequential(self, image_source, coordinate_format='percent'):
        # if os.path.isdir(image_source):
        #     return self.process_batch(image_source, 'get_stitched_text_sequential', coordinate_format)
        # else:
        return self._get_stitched_text_sequential_single(image_source, coordinate_format)

    async def _get_stitched_text_sequential_single(self, image_source, coordinate_format='percent'):
        try:
            original_size = None
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(image_source)
                result, original_size = await self.lens.scan_by_buffer(image_buffer)
            elif is_url(image_source):
                result, original_size = await self.lens.scan_by_url(image_source)
            else: # Assume file path
                result, original_size = await self.lens.scan_by_file(image_source)
            simplified_result = simplify_output(result, image_dimensions=original_size, coordinate_format=coordinate_format)
            return simplified_result['stitched_text_sequential']
        except (LensAPIError, LensParsingError, KeyError) as e:
            logging.error(f"Error getting stitched text (sequential method) from image: {e}")
            raise LensAPIError(f"Error getting stitched text (sequential method) from image: {e}") from e