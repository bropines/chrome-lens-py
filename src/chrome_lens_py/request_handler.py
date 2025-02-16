import httpx
import io
import os
import time
import lxml.html
import json5
import logging
import random
import string
import asyncio

from .constants import LENS_ENDPOINT, HEADERS_DEFAULT, HEADERS_CUSTOM, CHROME_HEADERS, MIME_TO_EXT
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
        self.session = httpx.AsyncClient()
        self.use_httpx = False
        self.setup_proxies()
        self.debug_out = self.config.get('debug_out')

        # Rate Limiting configuration
        self.rate_limit_config = self.config.get('rate_limiting', {})
        max_rpm_config = self.rate_limit_config.get('max_requests_per_minute')
        default_rpm = 30
        max_limit_rpm = 50

        if max_rpm_config is not None:
            try:
                self.max_requests_per_minute = int(max_rpm_config)
                if not 1 <= self.max_requests_per_minute <= max_limit_rpm:
                    logging.warning(
                        f"Configured rate_limit_rpm is out of range [1-50], using default value: {default_rpm}")
                    self.max_requests_per_minute = default_rpm
            except ValueError:
                logging.warning(
                    f"Configured rate_limit_rpm is not an integer, using default value: {default_rpm}")
                self.max_requests_per_minute = default_rpm
        else:
            self.max_requests_per_minute = default_rpm # Default RPM if not in config

        self.max_requests_per_minute = min(self.max_requests_per_minute, max_limit_rpm) # Hard cap at 50 RPM
        self.token_bucket = self.max_requests_per_minute
        self.last_refill_time = time.monotonic()
        logging.debug(f"Rate limiting enabled, max RPM: {self.max_requests_per_minute}")


    def setup_proxies(self):
        """Sets up proxies for the session if specified in the configuration."""
        proxy = self.config.get('proxy')

        if proxy:
            if proxy.startswith('socks'):
                self.use_httpx = True
                self.client = httpx.AsyncClient(proxies=proxy)
                logging.debug(f"Using HTTPX client with proxy: {proxy}")
            else:
                self.session.proxies = {
                    'http': proxy,
                    'https': proxy
                }
                self.client = httpx.AsyncClient(proxies=proxy)
                logging.debug(f"Using requests session with proxy: {proxy}")
        else:
            self.session.proxies = {'http': None, 'https': None}
            self.client = httpx.AsyncClient()
            logging.debug("Proxies explicitly disabled")

    def generate_cookie_header(self, headers):
        """Adds cookies to the request headers."""
        headers['Cookie'] = self.cookies_manager.generate_cookie_header()

    def get_headers(self):
        """Returns the selected set of headers based on the configuration."""
        header_type = self.config.get('header_type', 'default')
        if header_type == 'custom':
            headers = HEADERS_CUSTOM.copy()
            logging.debug("Using CUSTOM headers.")
        elif header_type == 'chrome':
            headers = CHROME_HEADERS.copy()
            logging.debug("Using CUSTOM headers.")
        else:
            headers = HEADERS_DEFAULT.copy()
            logging.debug("Using DEFAULT headers.")
        return headers

    async def _refill_token_bucket(self):
        """Refills the token bucket based on elapsed time."""
        now = time.monotonic()
        time_elapsed = now - self.last_refill_time
        tokens_to_add = (time_elapsed / 60) * self.max_requests_per_minute
        self.token_bucket = min(self.max_requests_per_minute, self.token_bucket + tokens_to_add)
        self.last_refill_time = now

    async def _acquire_token(self):
        """Acquires a token from the bucket, waiting if necessary."""
        while self.token_bucket < 1:
            await self._refill_token_bucket()
            await asyncio.sleep(1)  # Wait for 1 second before retrying
        self.token_bucket -= 1

    async def scan_by_data(self, data, mime, dimensions):
        """Sends image data to the Google Lens API for analysis."""
        await self._acquire_token()  # Acquire token before sending request

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
        params = {
            'ep': 'ccm',
            're': 'dcsp',
            's': '4',
            'st': str(time.time() * 1000),
            'sideimagesearch': '1',
            'vpw': str(dimensions[0]),
            'vph': str(dimensions[1])
        }

        if self.use_httpx:
            response = await self.client.post(
                LENS_ENDPOINT, headers=headers, files=files, params=params)
        else:
            response = await self.session.post(
                LENS_ENDPOINT, headers=headers, files=files, params=params)

        logging.info(f"Response code: {response.status_code}")

        # Update cookies based on the response
        if 'set-cookie' in response.headers:
            self.cookies_manager.update_cookies(response.headers['set-cookie'])

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

    async def scan_by_file(self, file_path):
        """Scans an image from the specified file path and returns the results."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError("Unsupported file type")
        logging.debug(f"Resizing image: {file_path}")
        img_data, dimensions, original_size = resize_image(file_path)
        logging.debug(
            f"Image resized to: {dimensions}, original size: {original_size}")
        result = await self.scan_by_data(img_data, 'image/jpeg', dimensions)
        return result, original_size

    async def scan_by_url(self, url):
        """Scans an image from the specified URL and returns the results."""
        try:
            logging.info("Downloading image from URL...")
            logging.debug(f"Downloading image from URL: {url}")
            async with httpx.AsyncClient() as client:
                response = await client.get(url, stream=True)
                if response.status_code != 200:
                    raise LensError(f"Failed to download image from URL: {url}")
                buffer = await response.aread()
                return await self.scan_by_buffer(buffer)
        except Exception as e:
            logging.error(
                f"Error downloading or processing image from URL: {e}")
            raise LensError(
                f"Error downloading or processing image from URL: {e}") from e

    async def scan_by_buffer(self, buffer):
        """Scans an image from the given buffer and returns the results."""
        try:
            logging.debug("Resizing image from buffer")
            img_data, dimensions, original_size = resize_image_from_buffer(
                buffer)
            logging.debug(
                f"Image resized to: {dimensions}, original size: {original_size}")
            result = await self.scan_by_data(img_data, 'image/jpeg', dimensions)
            return result, original_size
        except Exception as e:
            logging.error(f"Error processing image from buffer: {e}")
            raise LensError(f"Error processing image from buffer: {e}") from e