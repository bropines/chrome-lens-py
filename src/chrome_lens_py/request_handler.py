import requests
import httpx
import io
import os
import time
import lxml.html
import json5
import logging
from datetime import datetime
from .constants import LENS_ENDPOINT, HEADERS, MIME_TO_EXT
from .utils import sleep, is_supported_mime
from .image_processing import resize_image, resize_image_from_buffer
from .cookies_manager import CookiesManager
from .exceptions import LensError

class LensCore:
    """Base class for working with the Google Lens API."""

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

    def setup_proxies(self):
        """Sets up proxies for the session if provided in config."""
        proxy = self.config.get('proxy')
        if proxy:
            if proxy.startswith('socks'):
                self.use_httpx = True
                self.client = httpx.Client(proxies={
                    'http://': proxy,
                    'https://': proxy
                })
            else:
                self.session.proxies = {
                    'http': proxy,
                    'https': proxy
                }

    def generate_cookie_header(self, headers):
        """Adds cookies to request headers."""
        headers['Cookie'] = self.cookies_manager.generate_cookie_header()

    def scan_by_data(self, data, mime, dimensions):
        """Submits an image to the Google Lens API for analysis."""
        headers = HEADERS.copy()
        self.generate_cookie_header(headers)

        logging.info(f"Sending data to {LENS_ENDPOINT} via {'httpx' if self.use_httpx else 'requests'} with proxy: {self.config.get('proxy')}")

        file_name = f"image.{MIME_TO_EXT[mime]}"
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

        # Обновляем куки на основе ответа
        if 'set-cookie' in response.headers:
            self.cookies_manager.update_cookies(
                response.headers['set-cookie'])

        if response.status_code != 200:
            logging.error(f"Failed to load image. Response code: {response.status_code}")
            logging.debug(f"Response headers: {response.headers}")
            logging.debug(f"Response body: {response.text}")
            raise LensError("Failed to load image",
                            response.status_code, response.headers, response.text)

        # Сохраняем полный текст ответа в файл для отладки, только если уровень логирования DEBUG
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            response_file_path = os.path.join(os.getcwd(), "response_debug.txt")
            with open(response_file_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            logging.debug(f"Response saved to {response_file_path}")

        buffer_text = io.StringIO(response.text)
        tree = lxml.html.parse(buffer_text)

        r = tree.xpath("//script[@class='ds:1']")

        if not r:
            logging.error("Error: Expected data not found in response.")
            raise LensError("Failed to parse expected data from response",
                            response.status_code, response.headers, response.text)

        result = json5.loads(r[0].text[len("AF_initDataCallback("):-2])
        return result  # Возвращаем результат без размеров

class Lens(LensCore):
    """A class for working with the Google Lens API, providing convenience methods."""

    def __init__(self, config=None, sleep_time=1000, logging_level=logging.WARNING):
        super().__init__(config, sleep_time, logging_level)

    def scan_by_file(self, file_path):
        """Scans an image at the specified path and returns the results."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError("Unsupported file type")
        img_data, dimensions, original_size = resize_image(file_path)
        result = self.scan_by_data(img_data, 'image/jpeg', dimensions)
        return result, original_size  # Возвращаем оригинальные размеры

    def scan_by_url(self, url):
        """Scans an image from a URL and returns the results."""
        try:
            response = self.session.get(url, stream=True)
            if response.status_code != 200:
                raise LensError(f"Failed to download image from URL: {url}")
            buffer = response.content  # Get image bytes
            return self.scan_by_buffer(buffer)
        except Exception as e:
            raise LensError(f"Error downloading or processing image from URL: {e}") from e

    def scan_by_buffer(self, buffer):
        """Scans an image from the buffer and returns the results."""
        try:
            img_data, dimensions, original_size = resize_image_from_buffer(buffer)
            result = self.scan_by_data(img_data, 'image/jpeg', dimensions)
            return result, original_size  # Возвращаем оригинальные размеры
        except Exception as e:
            raise LensError(f"Error processing image from buffer: {e}") from e
