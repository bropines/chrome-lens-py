import asyncio
import logging
import os
import time

import numpy as np
from PIL import Image

from .exceptions import (
    LensAPIError,
    LensCookieError,
    LensError,
    LensImageError,
    LensParsingError,
)
from .image_processing import image_to_jpeg_buffer, numpy_array_to_jpeg_buffer
from .request_handler import Lens
from .text_processing import (
    simplify_output,
)  # stitch_* functions are used within simplify_output
from .utils import is_supported_mime, is_url  # Keep utils


class LensAPI:
    def __init__(
        self,
        config=None,
        sleep_time=1000,
        logging_level=logging.WARNING,
        rate_limit_rpm=None,
    ):
        # sleep_time is less critical with new request_handler rate limiter, but keep for config compatibility
        self.config = config or {}
        self.logging_level = logging_level
        # Set logging level for the entire application if needed
        logging.getLogger().setLevel(self.logging_level)

        # --- Rate Limiting Configuration ---
        # Rate limit is now primarily handled *inside* LensCore (request_handler)
        # based on the config passed to it. We still process the CLI/param override here
        # to put it into the config dict passed down.
        effective_config = self.config.copy()  # Work on a copy

        if rate_limit_rpm is not None:
            try:
                rate_limit_rpm_int = int(rate_limit_rpm)
                # Validation (1-40) is done inside LensCore, but basic check here is ok
                if (
                    1 <= rate_limit_rpm_int <= 60
                ):  # Allow slightly wider range here, LensCore caps at 40
                    effective_config.setdefault("rate_limiting", {})[
                        "max_requests_per_minute"
                    ] = rate_limit_rpm_int
                    logging.info(
                        f"API level rate limit override set to {rate_limit_rpm_int} RPM."
                    )
                else:
                    logging.warning(
                        f"Provided rate_limit_rpm ({rate_limit_rpm}) is out of typical range [1-40]. Check config/value."
                    )
                    # Still pass it down, LensCore will handle validation/defaulting
                    effective_config.setdefault("rate_limiting", {})[
                        "max_requests_per_minute"
                    ] = rate_limit_rpm_int
            except ValueError:
                logging.warning(
                    f"Invalid rate_limit_rpm value provided ('{rate_limit_rpm}'). Using config or default."
                )
                # Don't modify config if value is invalid

        # Initialize the updated Lens class (from request_handler)
        # Pass the potentially updated config down
        try:
            self.lens = Lens(
                config=effective_config,
                sleep_time=sleep_time,
                logging_level=logging_level,
            )
        except Exception as e:
            logging.error(f"Fatal error initializing Lens backend: {e}", exc_info=True)
            # Re-raise as a specific API error to halt execution if Lens can't start
            raise LensAPIError(f"Failed to initialize Lens backend: {e}") from e

        # sleep_between_requests is handled by the internal rate limiter now
        # self.sleep_between_requests = sleep_time / 1000.0

    # Batch processing logic removed as it was commented out and not requested.
    # Focus on robust single image processing.

    # --- Core Methods (Now Async) ---

    async def _process_single_source(self, image_source):
        """Internal helper to call the correct Lens scan method based on source type."""
        original_size = None
        parsed_data = None

        try:
            if isinstance(image_source, Image.Image):
                logging.debug("Processing Pillow Image object")
                image_buffer = image_to_jpeg_buffer(
                    image_source
                )  # Can raise LensImageError
                parsed_data, original_size = await self.lens.scan_by_buffer(
                    image_buffer
                )  # Await async call
            elif isinstance(image_source, np.ndarray):
                logging.debug("Processing NumPy array")
                image_buffer = numpy_array_to_jpeg_buffer(
                    image_source
                )  # Can raise LensImageError
                parsed_data, original_size = await self.lens.scan_by_buffer(
                    image_buffer
                )  # Await async call
            elif isinstance(image_source, str) and is_url(image_source):
                logging.debug(f"Processing URL: {image_source}")
                parsed_data, original_size = await self.lens.scan_by_url(
                    image_source
                )  # Await async call
            elif isinstance(image_source, str) and os.path.isfile(image_source):
                logging.debug(f"Processing file path: {image_source}")
                parsed_data, original_size = await self.lens.scan_by_file(
                    image_source
                )  # Await async call
            elif isinstance(image_source, bytes):
                logging.debug("Processing raw bytes buffer")
                # Assume JPEG or let scan_by_buffer handle it
                parsed_data, original_size = await self.lens.scan_by_buffer(
                    image_source
                )  # Await async call
            else:
                raise LensAPIError(
                    f"Unsupported image source type: {type(image_source)}"
                )

        # Catch specific errors from Lens or image processing
        except (LensError, LensAPIError, LensParsingError, LensCookieError) as e:
            logging.error(f"Error scanning image source: {e}")
            # Re-raise to be handled by the calling method
            raise
        except FileNotFoundError as e:
            logging.error(f"Image file not found: {e}")
            raise LensAPIError(f"Image file not found: {e}") from e
        except ValueError as e:  # e.g., unsupported mime type from scan_by_file
            logging.error(f"Value error during processing: {e}")
            raise LensAPIError(f"Processing error: {e}") from e
        except Exception as e:
            # Catch unexpected errors during processing
            logging.error(
                f"Unexpected error processing image source: {e}", exc_info=True
            )
            raise LensAPIError(f"An unexpected error occurred: {e}") from e

        if parsed_data is None:
            # This case might occur if scan_* methods return None unexpectedly
            raise LensAPIError(
                "Failed to get parsed data from Lens scan, received None."
            )

        return parsed_data, original_size

    # --- Public API Methods (Now Async) ---

    async def get_all_data(self, image_source, coordinate_format="percent"):
        """Gets all available data (text, coords, language, stitched) for the image."""
        logging.debug(f"get_all_data called for source type: {type(image_source)}")
        try:
            # Process the source to get parsed data and original size
            parsed_data, original_size = await self._process_single_source(image_source)

            # Simplify the output using the updated function
            simplified_result = simplify_output(
                parsed_data,
                image_dimensions=original_size,
                coordinate_format=coordinate_format,
            )
            return simplified_result
        except (LensAPIError, LensParsingError, LensCookieError) as e:
            # Log the error specific to this API call context
            logging.error(f"Error getting all data from image: {e}")
            # Re-raise the caught exception for the caller (e.g., main.py) to handle
            raise  # No need to wrap it again unless adding more context

    async def get_full_text(self, image_source):
        """Gets the primary reconstructed full text."""
        logging.debug(f"get_full_text called for source type: {type(image_source)}")
        try:
            # Process the source
            parsed_data, _ = await self._process_single_source(
                image_source
            )  # Don't need original_size here

            # The full text is now directly available after parsing
            full_text = "\n".join(parsed_data.get("reconstructed_blocks", []))
            if not full_text:
                logging.warning("No reconstructed text blocks found in parsed data.")
                # Return empty string or specific message? Empty string is safer.
                return ""
            return full_text
        except (LensAPIError, LensParsingError, LensCookieError) as e:
            logging.error(f"Error getting full text from image: {e}")
            raise
        except KeyError as e:
            logging.error(f"Missing expected key in parsed data for full text: {e}")
            raise LensParsingError(
                f"Parsed data structure missing key for full text: {e}"
            )

    async def get_text_with_coordinates(
        self, image_source, coordinate_format="percent"
    ):
        """Gets text annotations with coordinates (and angle)."""
        logging.debug(
            f"get_text_with_coordinates called for source type: {type(image_source)}"
        )
        try:
            # Process source
            parsed_data, original_size = await self._process_single_source(image_source)

            # Extract using the updated function within simplify_output
            simplified_result = simplify_output(
                parsed_data,
                image_dimensions=original_size,
                coordinate_format=coordinate_format,
            )

            # Check if coordinates were successfully extracted
            if "text_with_coordinates" not in simplified_result:
                logging.error(
                    "Failed to extract 'text_with_coordinates' during simplification."
                )
                # Check for underlying error in simplified_result
                if "error" in simplified_result:
                    raise LensParsingError(
                        f"Error during simplification: {simplified_result['error']}"
                    )
                else:
                    raise LensParsingError(
                        "Unknown error: 'text_with_coordinates' key missing after simplification."
                    )

            return simplified_result["text_with_coordinates"]
        except (LensAPIError, LensParsingError, LensCookieError) as e:
            logging.error(f"Error getting text with coordinates: {e}")
            raise
        except KeyError as e:  # Catch potential key errors during simplification access
            logging.error(f"Missing expected key when accessing simplified result: {e}")
            raise LensParsingError(
                f"Simplified data structure missing expected key: {e}"
            )

    async def get_stitched_text_smart(self, image_source):
        """Gets text stitched using the 'smart' (line reconstruction) method."""
        logging.debug(
            f"get_stitched_text_smart called for source type: {type(image_source)}"
        )
        try:
            # Process source
            parsed_data, original_size = await self._process_single_source(
                image_source
            )  # Need original size for simplify

            # Simplify (which calls the stitching function)
            simplified_result = simplify_output(
                parsed_data,
                image_dimensions=original_size,
                coordinate_format="percent",  # Stitching usually works on relative coords
            )

            if "stitched_text_smart" not in simplified_result:
                logging.error(
                    "Failed to extract 'stitched_text_smart' during simplification."
                )
                if "error" in simplified_result:
                    raise LensParsingError(
                        f"Error during simplification: {simplified_result['error']}"
                    )
                else:
                    raise LensParsingError(
                        "Unknown error: 'stitched_text_smart' key missing after simplification."
                    )

            return simplified_result["stitched_text_smart"]
        except (LensAPIError, LensParsingError, LensCookieError) as e:
            logging.error(f"Error getting stitched text (smart): {e}")
            raise
        except KeyError as e:
            logging.error(f"Missing expected key when accessing simplified result: {e}")
            raise LensParsingError(
                f"Simplified data structure missing expected key: {e}"
            )

    async def get_stitched_text_sequential(self, image_source):
        """Gets text stitched using the sequential order method."""
        logging.debug(
            f"get_stitched_text_sequential called for source type: {type(image_source)}"
        )
        try:
            # Process source
            parsed_data, original_size = await self._process_single_source(
                image_source
            )  # Need original size for simplify

            # Simplify (which calls the stitching function)
            simplified_result = simplify_output(
                parsed_data,
                image_dimensions=original_size,
                coordinate_format="percent",  # Stitching usually works on relative coords
            )

            if "stitched_text_sequential" not in simplified_result:
                logging.error(
                    "Failed to extract 'stitched_text_sequential' during simplification."
                )
                if "error" in simplified_result:
                    raise LensParsingError(
                        f"Error during simplification: {simplified_result['error']}"
                    )
                else:
                    raise LensParsingError(
                        "Unknown error: 'stitched_text_sequential' key missing after simplification."
                    )

            return simplified_result["stitched_text_sequential"]
        except (LensAPIError, LensParsingError, LensCookieError) as e:
            logging.error(f"Error getting stitched text (sequential): {e}")
            raise
        except KeyError as e:
            logging.error(f"Missing expected key when accessing simplified result: {e}")
            raise LensParsingError(
                f"Simplified data structure missing expected key: {e}"
            )

    async def close_session(self):
        """Closes the underlying httpx client session managed by the Lens instance."""
        logging.debug("Closing Lens API session...")
        if self.lens and hasattr(self.lens, "close"):
            await self.lens.close()
        else:
            logging.debug("Lens instance or close method not found.")
