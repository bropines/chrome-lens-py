import asyncio
import io
import logging
import math  # Added for degree conversion
import os
import random
import string
import time
from urllib.parse import parse_qs, urlparse

import httpx

# --- JSON Parsing Setup ---
try:
    import json5

    json_loader = json5.loads
    logging.debug("Using json5 for parsing Lens metadata.")
except ImportError:
    import json

    json_loader = json.loads
    logging.debug("json5 not found, using standard json module for Lens metadata.")


from .constants import (
    HEADERS_DEFAULT,
    LENS_METADATA_ENDPOINT,
    LENS_UPLOAD_ENDPOINT,
    MIME_TO_EXT,
)
from .cookies_manager import CookiesManager
from .exceptions import LensAPIError, LensError, LensParsingError
from .image_processing import resize_image, resize_image_from_buffer
from .utils import (  # sleep might be less relevant with async/rate limiting
    is_supported_mime,
    sleep,
)


class LensCore:
    """Base class for interacting with the Google Lens API (Updated Method)."""

    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        self.config = config if config else {}
        self.logging_level = logging_level
        # Ensure logging level is set early
        # logging.getLogger().setLevel(self.logging_level) # Setting level in main.py/LensAPI is better
        self.cookies_manager = CookiesManager(
            config=self.config, logging_level=logging_level
        )
        # self.sleep_time = sleep_time # Less relevant with async rate limiting
        self.client = None  # httpx.AsyncClient initialized later
        self.proxy = self.config.get("proxy")
        self.debug_out = self.config.get("debug_out")

        # Rate Limiting configuration
        self.rate_limit_config = self.config.get("rate_limiting", {})
        max_rpm_config = self.rate_limit_config.get("max_requests_per_minute")
        default_rpm = 30
        max_limit_rpm = 40  # Google's unofficial limit seems around 30-40

        if max_rpm_config is not None:
            try:
                self.max_requests_per_minute = int(max_rpm_config)
                if not 1 <= self.max_requests_per_minute <= max_limit_rpm:
                    logging.warning(
                        f"Configured rate_limit_rpm ({self.max_requests_per_minute}) is out of range [1-{max_limit_rpm}], using default value: {default_rpm}"
                    )
                    self.max_requests_per_minute = default_rpm
            except ValueError:
                logging.warning(
                    f"Configured rate_limit_rpm is not an integer ('{max_rpm_config}'), using default value: {default_rpm}"
                )
                self.max_requests_per_minute = default_rpm
        else:
            self.max_requests_per_minute = default_rpm  # Default RPM if not in config

        # Apply hard cap just in case
        self.max_requests_per_minute = min(self.max_requests_per_minute, max_limit_rpm)

        # Rate limiting state
        self.request_timestamps = []
        logging.debug(
            f"Rate limiting configured to max {self.max_requests_per_minute} RPM"
        )

        # Initialize httpx client
        self.setup_client()

    def setup_client(self):
        """Sets up the httpx.AsyncClient with proxy and cookie settings."""
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        timeout = httpx.Timeout(30.0, connect=10.0)  # Adjust timeouts as needed

        # Load cookies from manager into httpx-compatible dict
        initial_cookies = {}
        if self.cookies_manager.cookies:
            initial_cookies = {
                v["name"]: v["value"] for k, v in self.cookies_manager.cookies.items()
            }
            logging.debug("Loading initial cookies into httpx client.")

        try:
            if self.proxy:
                logging.debug(f"Setting up httpx client with proxy: {self.proxy}")
                self.client = httpx.AsyncClient(
                    proxy=self.proxy,
                    cookies=initial_cookies,
                    follow_redirects=True,
                    timeout=timeout,
                    limits=limits,
                    http2=True,  # Enable HTTP/2
                    verify=True,  # Enable SSL verification by default
                )
            else:
                logging.debug("Setting up httpx client without proxy.")
                self.client = httpx.AsyncClient(
                    cookies=initial_cookies,
                    follow_redirects=True,
                    timeout=timeout,
                    limits=limits,
                    http2=True,
                    verify=True,
                )
        except Exception as e:
            logging.error(f"Failed to initialize httpx client: {e}")
            raise LensError(f"Failed to initialize httpx client: {e}") from e

    def get_headers(self, step="upload", referer=None):
        """Returns the appropriate headers for the request step."""
        headers = HEADERS_DEFAULT.copy()
        if step == "metadata":
            metadata_headers = headers.copy()
            metadata_headers.update(
                {
                    "Accept": "*/*",  # As per new script
                    "Referer": (
                        referer if referer else HEADERS_DEFAULT.get("Referer")
                    ),  # Use dynamic referer
                    "Sec-Fetch-Site": "same-origin",  # Changed from same-site for metadata
                    "Sec-Fetch-Mode": "cors",  # As per new script
                    "Sec-Fetch-Dest": "empty",  # As per new script
                    "Priority": "u=1, i",  # Higher priority for metadata
                }
            )
            # Remove headers not needed for metadata fetch
            metadata_headers.pop("Upgrade-Insecure-Requests", None)
            metadata_headers.pop("Sec-Fetch-User", None)
            metadata_headers.pop("Cache-Control", None)
            # metadata_headers.pop('Origin', None) # Keep Origin? Script removes it, let's test keeping it.
            return metadata_headers
        # For upload step, just return the default
        return headers

    async def _rate_limit_wait(self):
        """Waits if necessary to comply with the rate limit."""
        now = time.monotonic()
        # Remove timestamps older than 60 seconds
        self.request_timestamps = [
            ts for ts in self.request_timestamps if now - ts < 60
        ]

        if len(self.request_timestamps) >= self.max_requests_per_minute:
            time_to_wait = (
                60 - (now - self.request_timestamps[0]) + 0.1
            )  # Wait until the oldest request expires + buffer
            logging.debug(
                f"Rate limit reached ({len(self.request_timestamps)}/{self.max_requests_per_minute} RPM). Waiting for {time_to_wait:.2f} seconds."
            )
            await asyncio.sleep(time_to_wait)
            # Re-check after waiting
            now = time.monotonic()
            self.request_timestamps = [
                ts for ts in self.request_timestamps if now - ts < 60
            ]

        self.request_timestamps.append(now)

    def _extract_ids_from_url(self, url_string):
        """Extracts vsrid and lsessionid from URL query parameters."""
        try:
            parsed_url = urlparse(url_string)
            query_params = parse_qs(parsed_url.query)
            vsrid = query_params.get("vsrid", [None])[0]
            lsessionid = query_params.get("lsessionid", [None])[0]
            logging.debug(
                f"Extracted vsrid: {vsrid}, lsessionid: {lsessionid} from URL."
            )
            return vsrid, lsessionid
        except Exception as e:
            logging.error(f"Error extracting IDs from URL {url_string}: {e}")
            return None, None

    def _adaptive_parse_text_and_language(self, metadata_json):
        """
        Adaptively parses JSON to extract language, text blocks, and word annotations.
        (Directly adapted from the provided new script)
        """
        language = None
        all_word_annotations = []
        reconstructed_blocks = []

        try:
            # Basic structure validation
            if not isinstance(metadata_json, list) or not metadata_json:
                logging.error(
                    "Invalid JSON structure: metadata_json is not a non-empty list."
                )
                raise LensParsingError(
                    "Invalid JSON structure: metadata_json is not a non-empty list."
                )

            # Find the main response container
            response_container = next(
                (
                    item
                    for item in metadata_json
                    if isinstance(item, list)
                    and item
                    and item[0] == "fetch_query_formulation_metadata_response"
                ),
                None,
            )
            if response_container is None:
                logging.error(
                    "Could not find 'fetch_query_formulation_metadata_response' container in metadata."
                )
                raise LensParsingError(
                    "Could not find 'fetch_query_formulation_metadata_response' container."
                )

            # --- Language Extraction ---
            try:
                # Path: Look within the second major element [2], usually a list containing language info
                if len(response_container) > 2 and isinstance(
                    response_container[2], list
                ):
                    lang_section = response_container[2]
                    # Language code is typically a 2-char string within this section
                    language = next(
                        (
                            element
                            for element in lang_section
                            if isinstance(element, str) and len(element) == 2
                        ),
                        None,
                    )
                    if language:
                        logging.debug(f"Found language code: '{language}'")
                    else:
                        logging.warning(
                            "Language code not found in expected format within lang_section."
                        )
                else:
                    logging.warning(
                        "Language section (index 2) not found or not a list."
                    )
            except (IndexError, TypeError, StopIteration):
                logging.warning(
                    "Error or structure mismatch during language code extraction."
                )

            # --- Text/Word Extraction ---
            segments_iterable = None
            # Define potential paths leading to the list of text segments/blocks
            # These paths are based on observed JSON structures and might need adjustment if the API changes.
            possible_paths_to_segments_list = [
                lambda rc: rc[2][0][0][0],  # Path observed in some responses
                lambda rc: rc[1][0][0][0],  # Another common path
                lambda rc: rc[2][0][0],  # A slightly shallower path
            ]
            path_names = ["[2][0][0][0]", "[1][0][0][0]", "[2][0][0]"]

            # Try each path until a valid-looking segments list is found
            for i, path_func in enumerate(possible_paths_to_segments_list):
                path_name = path_names[i]
                try:
                    candidate_iterable = path_func(response_container)
                    # Validate the structure: It should be a list, not empty, and contain lists (segments)
                    # Further check: first segment should be a list, have >1 elements,
                    # and its second element [1] should be the list containing word groups.
                    # Deep check: that word groups list [1] should contain lists (groups),
                    # and the first group [1][0] should contain lists (words),
                    # and the first word [1][0][0] should be a list (word details).
                    if (
                        isinstance(candidate_iterable, list)
                        and candidate_iterable
                        and isinstance(candidate_iterable[0], list)
                    ):
                        try:
                            first_segment = candidate_iterable[0]
                            if (
                                len(first_segment) > 1
                                and isinstance(first_segment[1], list)
                                and first_segment[1]
                                and isinstance(first_segment[1][0], list)
                                and len(first_segment[1][0]) > 0
                                and isinstance(first_segment[1][0][0], list)
                            ):
                                segments_iterable = candidate_iterable
                                logging.debug(
                                    f"Text segments list identified at path ending with {path_name}"
                                )
                                break  # Found a suitable path
                        except (IndexError, TypeError):
                            pass  # Structure doesn't match deep checks, try next path
                except (IndexError, TypeError):
                    logging.debug(
                        f"Path ending with {path_name} not found or invalid structure."
                    )
                    pass  # Path doesn't exist or structure is wrong, try next path

            if segments_iterable is None:
                logging.error(
                    f"Could not identify valid text segments list using common paths {path_names}."
                )
                # Don't raise error here, maybe there's no text? Return empty results.
                return language, [], []

            # Iterate through the identified segments list
            for segment_list in segments_iterable:
                current_block_word_annotations = []
                block_text_builder = io.StringIO()
                last_word_ends_with_space = (
                    True  # Assume start doesn't need leading space
                )

                if not isinstance(segment_list, list):
                    logging.warning(
                        f"Skipping segment: Expected list, got {type(segment_list)}."
                    )
                    continue

                try:
                    # Word groups are usually in the second element [1] of the segment list
                    if len(segment_list) > 1 and isinstance(segment_list[1], list):
                        word_groups_list = segment_list[1]

                        for group_count, word_group in enumerate(word_groups_list, 1):
                            try:
                                # Check if word_group structure is valid: list[list[list]] (group -> words -> word_details)
                                if (
                                    isinstance(word_group, list)
                                    and len(word_group) > 0
                                    and isinstance(word_group[0], list)
                                    and isinstance(word_group[0][0], list)
                                ):

                                    word_list = word_group[
                                        0
                                    ]  # Get the list of words in this group

                                    # Add space between groups if needed
                                    if (
                                        group_count > 1
                                        and block_text_builder.tell() > 0
                                        and not last_word_ends_with_space
                                    ):
                                        block_text_builder.write(" ")
                                        last_word_ends_with_space = True

                                    # Process each word in the word list
                                    for word_info in word_list:
                                        try:
                                            # Validate word_info structure: list with text[1], space_indicator[2], bbox_list[3]
                                            if (
                                                isinstance(word_info, list)
                                                and len(word_info) > 3
                                                and isinstance(
                                                    word_info[1], str
                                                )  # Text
                                                and isinstance(
                                                    word_info[2], str
                                                )  # Space indicator (" " or "")
                                                and isinstance(word_info[3], list)
                                                and word_info[3]  # Bbox container list
                                                and isinstance(word_info[3][0], list)
                                            ):  # Actual Bbox list

                                                text = word_info[1]
                                                space_indicator = word_info[
                                                    2
                                                ]  # Usually " " or ""
                                                bbox = word_info[3][
                                                    0
                                                ]  # Extract the bounding box list

                                                # --- Bounding Box Processing & Degree Conversion ---
                                                processed_bbox = bbox  # Keep original bbox structure for now
                                                # Check if angle (expected at index 4) exists and is numeric
                                                if len(bbox) > 4 and isinstance(
                                                    bbox[4], (int, float)
                                                ):
                                                    try:
                                                        degrees = math.degrees(bbox[4])
                                                        # Create a new list or modify a copy if you need both rad/deg
                                                        # For now, let's store it separately in the annotation dict
                                                        annotation = {
                                                            "text": text,
                                                            "bbox": processed_bbox,
                                                            "angle_degrees": degrees,
                                                        }
                                                    except TypeError:
                                                        logging.warning(
                                                            f"Could not convert angle {bbox[4]} to degrees for word '{text}'. Skipping degree conversion."
                                                        )
                                                        annotation = {
                                                            "text": text,
                                                            "bbox": processed_bbox,
                                                        }
                                                else:
                                                    annotation = {
                                                        "text": text,
                                                        "bbox": processed_bbox,
                                                    }  # No angle or invalid

                                                current_block_word_annotations.append(
                                                    annotation
                                                )

                                                # Reconstruct text block
                                                block_text_builder.write(text)
                                                block_text_builder.write(
                                                    space_indicator
                                                )
                                                last_word_ends_with_space = (
                                                    space_indicator == " "
                                                )

                                        except (IndexError, TypeError) as e_word:
                                            logging.warning(
                                                f"Skipping word due to structure error or missing elements: {e_word} in word_info: {word_info}"
                                            )
                                            pass  # Skip malformed word info
                            except (IndexError, TypeError) as e_group:
                                logging.warning(
                                    f"Skipping word group due to structure error: {e_group} in word_group: {word_group}"
                                )
                                pass  # Skip malformed word group
                    else:
                        logging.warning(
                            f"Word groups list (index 1) not found or invalid in segment: {segment_list}"
                        )
                except (IndexError, TypeError) as e_segment:
                    logging.error(
                        f"Error processing segment structure: {e_segment} in segment_list: {segment_list}"
                    )
                except Exception as e_seg_generic:
                    logging.error(
                        f"Unexpected error processing segment: {e_seg_generic}",
                        exc_info=True,
                    )

                reconstructed_text = block_text_builder.getvalue().rstrip(
                    " "
                )  # Remove trailing space if any
                block_text_builder.close()

                # Add the reconstructed block and its annotations if text was found
                if reconstructed_text or current_block_word_annotations:
                    reconstructed_blocks.append(reconstructed_text)
                    all_word_annotations.extend(
                        current_block_word_annotations
                    )  # Collect annotations from all blocks

        except LensParsingError:
            raise  # Propagate specific parsing errors
        except Exception as e_main:
            logging.error(
                f"Critical error during adaptive text extraction: {e_main}",
                exc_info=True,
            )
            # Raise a generic parsing error if something unexpected happened
            raise LensParsingError(
                f"Unexpected error during metadata parsing: {e_main}"
            ) from e_main

        logging.info(
            f"Adaptive parsing complete. Language: '{language}'. Text blocks found: {len(reconstructed_blocks)}. Total word annotations: {len(all_word_annotations)}."
        )
        # Return the structured data
        return {
            "language": (
                language if language else "und"
            ),  # Default to 'undetermined' if not found
            "reconstructed_blocks": reconstructed_blocks,
            "word_annotations": all_word_annotations,
        }

    async def _perform_scan(self, image_data, mime_type, dimensions):
        """Performs the two-step Lens scan: upload image, then fetch metadata."""
        if not self.client:
            logging.error("HTTPX client not initialized.")
            raise LensError("HTTPX client not initialized.")

        await self._rate_limit_wait()  # Check rate limit before starting requests

        # --- 1. Upload Image ---
        upload_headers = self.get_headers(step="upload")
        # Cookies are handled by the client instance now, no need to manually add header

        filename = (
            "".join(random.choices(string.ascii_letters, k=8))
            + "."
            + MIME_TO_EXT.get(mime_type, "jpg")
        )
        files = {"encoded_image": (filename, image_data, mime_type)}
        params_upload = {
            "hl": "en",  # Make configurable?
            "vpw": str(dimensions[0]),  # Use resized dimensions
            "vph": str(dimensions[1]),
            "ep": "gsbubb",
            "st": str(int(time.time() * 1000)),
        }

        upload_url_obj = httpx.URL(LENS_UPLOAD_ENDPOINT, params=params_upload)
        logging.info(f"Step 1: Uploading image to {LENS_UPLOAD_ENDPOINT}...")
        logging.debug(f"POST request to {str(upload_url_obj)}")

        try:
            response_upload = await self.client.post(
                upload_url_obj, headers=upload_headers, files=files
            )
            logging.debug(f"Upload Response Status: {response_upload.status_code}")
            logging.debug(
                f"Upload Response URL (final after redirects): {response_upload.url}"
            )

            # Update cookies after the first request
            self.cookies_manager.update_cookies(response_upload.cookies)

            response_upload.raise_for_status()  # Raise exception for 4xx/5xx errors

        except httpx.HTTPStatusError as e:
            logging.error(
                f"HTTP error during image upload: {e.response.status_code} for URL {e.request.url}"
            )
            logging.debug(f"Response Headers: {e.response.headers}")
            logging.debug(f"Response Body: {await e.response.aread()}")
            self.cookies_manager.save_cookies()  # Save cookies even on error
            raise LensAPIError(
                f"Image upload failed with status {e.response.status_code}",
                e.response.status_code,
                e.response.headers,
                await e.response.aread(),
            ) from e
        except httpx.RequestError as e:
            logging.error(f"Request error during image upload: {e}")
            self.cookies_manager.save_cookies()
            raise LensAPIError(f"Image upload request failed: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error during image upload: {e}", exc_info=True)
            self.cookies_manager.save_cookies()
            raise LensError(f"Unexpected error during upload: {e}") from e

        # --- 2. Extract Session IDs ---
        final_url = str(response_upload.url)
        vsrid, lsessionid = self._extract_ids_from_url(final_url)
        if not vsrid or not lsessionid:
            logging.error(
                "Failed to extract vsrid or lsessionid from upload redirect URL."
            )
            self.cookies_manager.save_cookies()  # Save cookies obtained so far
            raise LensParsingError(
                "Failed to get session IDs from upload response URL.", body=final_url
            )

        # --- 3. Fetch Metadata ---
        metadata_params = {
            "vsrid": vsrid,
            "lsessionid": lsessionid,
            "hl": params_upload["hl"],
            "st": str(int(time.time() * 1000)),
            "vpw": params_upload["vpw"],
            "vph": params_upload["vph"],
            "source": "lens",
        }
        # Use the final URL from upload as the Referer for the metadata request
        metadata_headers = self.get_headers(step="metadata", referer=final_url)

        metadata_url_obj = httpx.URL(LENS_METADATA_ENDPOINT, params=metadata_params)
        logging.info("Step 2: Fetching metadata...")
        logging.debug(f"GET request to {str(metadata_url_obj)}")

        try:
            response_metadata = await self.client.get(
                metadata_url_obj, headers=metadata_headers
            )
            logging.debug(f"Metadata Response Status: {response_metadata.status_code}")

            # Update cookies after the second request
            self.cookies_manager.update_cookies(response_metadata.cookies)
            self.cookies_manager.save_cookies()  # Save updated cookies

            response_metadata.raise_for_status()

        except httpx.HTTPStatusError as e:
            logging.error(
                f"HTTP error during metadata fetch: {e.response.status_code} for URL {e.request.url}"
            )
            logging.debug(f"Response Headers: {e.response.headers}")
            logging.debug(f"Response Body: {await e.response.aread()}")
            raise LensAPIError(
                f"Metadata fetch failed with status {e.response.status_code}",
                e.response.status_code,
                e.response.headers,
                await e.response.aread(),
            ) from e
        except httpx.RequestError as e:
            logging.error(f"Request error during metadata fetch: {e}")
            raise LensAPIError(f"Metadata fetch request failed: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error during metadata fetch: {e}", exc_info=True)
            raise LensError(f"Unexpected error during metadata fetch: {e}") from e

        # --- 4. Parse Metadata Response ---
        response_text = response_metadata.text
        # Remove potential XSSI prefix like )]}' or )]}'\n
        if response_text.startswith(")]}'\n"):
            response_text = response_text[5:]
        elif response_text.startswith(")]}'"):
            response_text = response_text[4:]

        # Save debug output if enabled
        if self.debug_out:
            try:
                debug_file_path = os.path.abspath(self.debug_out)
                with open(debug_file_path, "w", encoding="utf-8") as f:
                    f.write(response_text)
                logging.debug(f"Raw metadata response saved to {debug_file_path}")
            except Exception as e_debug:
                logging.warning(
                    f"Could not save debug output to {self.debug_out}: {e_debug}"
                )

        try:
            metadata_json = json_loader(response_text)
            parsed_data = self._adaptive_parse_text_and_language(metadata_json)
            return parsed_data  # Return the structured dictionary

        except (
            json.JSONDecodeError,
            json5.JSONDecodeError,
            LensParsingError,
        ) as e_parse:
            logging.error(
                f"Error parsing JSON or extracting text from metadata: {e_parse}",
                exc_info=True,
            )
            raise LensParsingError(
                f"Failed to parse metadata response: {e_parse}", body=response_text
            ) from e_parse
        except Exception as e_generic:
            logging.error(
                f"Unexpected error processing metadata: {e_generic}", exc_info=True
            )
            raise LensError(
                f"Unexpected error processing metadata: {e_generic}"
            ) from e_generic


class Lens(LensCore):
    """Class for interacting with the Google Lens API using the updated method."""

    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        # sleep_time is less relevant now, but keep for potential compatibility?
        super().__init__(config, sleep_time, logging_level)
        logging.getLogger().setLevel(
            self.logging_level
        )  # Ensure level is set in this higher class too

    async def scan_by_file(self, file_path):
        """Scans an image from a file path using the new two-step method."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError(f"Unsupported file type: {file_path}")

        logging.debug(f"Resizing image: {file_path}")
        try:
            # Resize image first (still necessary)
            img_data, dimensions, original_size = resize_image(file_path)
            logging.debug(
                f"Image resized to: {dimensions}, original size: {original_size}"
            )
        except Exception as e:
            logging.error(f"Error resizing image {file_path}: {e}")
            raise LensError(f"Error resizing image {file_path}: {e}") from e

        # Determine MIME type for upload
        filename = os.path.basename(file_path)
        _, ext = os.path.splitext(filename.lower())
        # Default to jpeg as resize usually outputs jpeg
        content_type = "image/jpeg"
        if ext == ".png":
            content_type = "image/png"
        elif ext == ".webp":
            content_type = "image/webp"
        elif ext == ".gif":
            content_type = "image/gif"
        # Add more specific types if needed, but resize often converts
        logging.debug(f"Using content type: {content_type} for upload")

        # Perform the actual scan using the core method
        result_data = await self._perform_scan(img_data, content_type, dimensions)
        # Return the parsed data dictionary and the original image size
        return result_data, original_size

    async def scan_by_url(self, url):
        """Scans an image from a URL using the new two-step method."""
        logging.info(f"Downloading image from URL: {url}")
        try:
            # Use the same client instance to download the image
            # This respects proxy settings and potentially cookies if needed for the URL
            async with self.client as client_for_download:  # Use existing client configuration
                response = await client_for_download.get(url)
                response.raise_for_status()  # Check if download was successful
                buffer = await response.aread()
                content_type = response.headers.get(
                    "Content-Type", "image/jpeg"
                )  # Get content type if available
                logging.debug(
                    f"Image downloaded from {url}, content type: {content_type}"
                )
                # Now scan the downloaded buffer
                return await self.scan_by_buffer(buffer, content_type_hint=content_type)
        except httpx.HTTPStatusError as e:
            logging.error(
                f"Failed to download image from URL {url}: {e.response.status_code}"
            )
            raise LensError(
                f"Failed to download image from URL: {url} (Status: {e.response.status_code})"
            ) from e
        except httpx.RequestError as e:
            logging.error(f"Network error downloading image from URL {url}: {e}")
            raise LensError(
                f"Network error downloading image from URL: {url}: {e}"
            ) from e
        except Exception as e:
            logging.error(f"Error downloading or processing image from URL {url}: {e}")
            raise LensError(
                f"Error downloading or processing image from URL: {e}"
            ) from e

    async def scan_by_buffer(self, buffer, content_type_hint="image/jpeg"):
        """Scans an image from a bytes buffer using the new two-step method."""
        logging.debug("Processing image from buffer")
        try:
            # Resize image from buffer
            img_data, dimensions, original_size = resize_image_from_buffer(buffer)
            logging.debug(
                f"Image from buffer resized to: {dimensions}, original size: {original_size}"
            )
        except Exception as e:
            logging.error(f"Error resizing image from buffer: {e}")
            raise LensError(f"Error resizing image from buffer: {e}") from e

        # Use the hint or default to jpeg (since resize often outputs jpeg)
        content_type = (
            content_type_hint if content_type_hint in MIME_TO_EXT else "image/jpeg"
        )
        logging.debug(f"Using content type: {content_type} for buffer upload")

        # Perform the actual scan
        result_data = await self._perform_scan(img_data, content_type, dimensions)
        # Return the parsed data dictionary and original size
        return result_data, original_size

    async def close(self):
        """Closes the underlying httpx client."""
        if self.client:
            await self.client.aclose()
            logging.debug("HTTPX client closed.")
