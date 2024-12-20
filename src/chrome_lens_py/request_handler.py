
import requests
import httpx
import io
import os
import time
import lxml.html
import json5
import logging
import random
import string

from .constants import LENS_ENDPOINT, HEADERS_DEFAULT, HEADERS_CUSTOM, MIME_TO_EXT
from .utils import sleep, is_supported_mime
from .image_processing import resize_image, resize_image_from_buffer
from .cookies_manager import CookiesManager
from .exceptions import LensError


class LensCore:
    """Base class for interacting with the Google Lens API."""

    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        self.config = config if config else {}
        self.logging_level = logging_level
        logging.getLogger().setLevel(self.logging_level)
        self.cookies_manager = CookiesManager(
            config=self.config, logging_level=logging_level)
        self.sleep_time = sleep_time
        self.session = requests.Session()
        self.use_httpx = False
        self.setup_proxies()
        self.debug_out = self.config.get('debug_out')  # Added for debug output

    def setup_proxies(self):
        """Sets up proxies for the session if specified in the configuration."""
        proxy = self.config.get('proxy')
        if proxy:
            if proxy.startswith('socks'):
                self.use_httpx = True
                self.client = httpx.Client(proxies={
                    'http://': proxy,
                    'https://': proxy
                })
                logging.debug(f"Using HTTPX client with proxy: {proxy}")
            else:
                self.session.proxies = {
                    'http': proxy,
                    'https': proxy
                }
                logging.debug(f"Using requests session with proxy: {proxy}")

    def generate_cookie_header(self, headers):
        """Adds cookies to the request headers."""
        headers['Cookie'] = self.cookies_manager.generate_cookie_header()

    def get_headers(self):
        """Returns the selected set of headers based on the configuration."""
        header_type = self.config.get('header_type', 'default')
        if header_type == 'custom':
            headers = HEADERS_CUSTOM.copy()
            logging.debug("Using CUSTOM headers.")
        else:
            headers = HEADERS_DEFAULT.copy()
            logging.debug("Using DEFAULT headers.")
        return headers

    def scan_by_data(self, data, mime, dimensions):
        """Sends image data to the Google Lens API for analysis."""
        headers = self.get_headers()
        self.generate_cookie_header(headers)

        logging.info("Sending data to Google Lens API...")
        logging.debug(
            f"Sending data to {LENS_ENDPOINT} using {'httpx' if self.use_httpx else 'requests'} with proxy: {self.config.get('proxy')}"
        )

        # Generate a random filename
        random_filename = ''.join(random.choices(string.ascii_letters, k=8))
        file_extension = MIME_TO_EXT.get(mime, 'jpg')  # Default to 'jpg'
        file_name = f"{random_filename}.{file_extension}"

        files = {
            'encoded_image': (file_name, data, mime),
            'original_width': (None, str(dimensions[0])),
            'original_height': (None, str(dimensions[1])),
            'processed_image_dimensions': (None, f"{dimensions[0]},{dimensions[1]}")
        }

        sleep(self.sleep_time)

        if self.use_httpx:
            response = self.client.post(
                LENS_ENDPOINT, headers=headers, files=files)
        else:
            response = self.session.post(
                LENS_ENDPOINT, headers=headers, files=files)

        logging.info(f"Response code: {response.status_code}")

        # Update cookies based on the response
        if 'set-cookie' in response.headers:
            self.cookies_manager.update_cookies(
                response.headers['set-cookie'])

        if response.status_code != 200:
            logging.error(
                f"Failed to upload image. Response code: {response.status_code}")
            logging.debug(f"Response headers: {response.headers}")
            logging.debug(f"Response body: {response.text}")
            raise LensError("Failed to upload image",
                            response.status_code, response.headers, response.text)

        # Save the full response text to a file for debugging if DEBUG level is enabled
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            if self.debug_out:
                response_file_path = os.path.abspath(self.debug_out)
            else:
                response_file_path = os.path.join(
                    os.getcwd(), "response_debug.txt")
            with open(response_file_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            logging.debug(f"Response saved to {response_file_path}")

        buffer_text = io.StringIO(response.text)
        tree = lxml.html.parse(buffer_text)

        r = tree.xpath("//script[@class='ds:1']")

        if not r:
            logging.error("Error: Expected data not found in the response.")
            raise LensError("Failed to parse expected data from the response",
                            response.status_code, response.headers, response.text)

        result = json5.loads(r[0].text[len("AF_initDataCallback("):-2])
        return result  # Return the result without dimensions


class Lens(LensCore):
    """Class for interacting with the Google Lens API, providing convenient methods."""

    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        super().__init__(config, sleep_time, logging_level)

    def scan_by_file(self, file_path):
        """Scans an image from the specified file path and returns the results."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError("Unsupported file type")
        logging.debug(f"Resizing image: {file_path}")
        img_data, dimensions, original_size = resize_image(file_path)
        logging.debug(
            f"Image resized to: {dimensions}, original size: {original_size}")
        result = self.scan_by_data(img_data, 'image/jpeg', dimensions)
        return result, original_size

    def scan_by_url(self, url):
        """Scans an image from the specified URL and returns the results."""
        try:
            logging.info("Downloading image from URL...")
            logging.debug(f"Downloading image from URL: {url}")
            response = self.session.get(url, stream=True)
            if response.status_code != 200:
                raise LensError(f"Failed to download image from URL: {url}")
            buffer = response.content  # Get image bytes
            return self.scan_by_buffer(buffer)
        except Exception as e:
            logging.error(
                f"Error downloading or processing image from URL: {e}")
            raise LensError(
                f"Error downloading or processing image from URL: {e}") from e

    def scan_by_buffer(self, buffer):
        """Scans an image from the given buffer and returns the results."""
        try:
            logging.debug("Resizing image from buffer")
            img_data, dimensions, original_size = resize_image_from_buffer(
                buffer)
            logging.debug(
                f"Image resized to: {dimensions}, original size: {original_size}")
            result = self.scan_by_data(img_data, 'image/jpeg', dimensions)
            return result, original_size
        except Exception as e:
            logging.error(f"Error processing image from buffer: {e}")
            raise LensError(f"Error processing image from buffer: {e}") from e
