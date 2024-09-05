import requests
import httpx  # Используем httpx только для работы с прокси
import io
import os
import time
import lxml.html
import json5
import filetype
from http.cookies import SimpleCookie
from PIL import Image
from .constants import LENS_ENDPOINT, HEADERS, MIME_TO_EXT, SUPPORTED_MIMES
from .utils import sleep, is_supported_mime
from .image_processing import resize_image
from .cookies_manager import CookiesManager  # Импортируем CookiesManager
from .exceptions import LensError


class LensCore:
    """Base class for working with the Google Lens API."""

    def __init__(self, config=None, sleep_time=1000):
        self.config = config if config else {}
        self.cookies_manager = CookiesManager(
            config=self.config)  # Инициализируем CookiesManager
        self.sleep_time = sleep_time
        self.session = requests.Session()  # Используем requests для стандартных запросов
        self.use_httpx = False
        self.setup_proxies()

    def setup_proxies(self):
        """Sets up proxies for the session if provided in config."""
        proxy = self.config.get('proxy')
        if proxy:
            # Если указан SOCKS5 прокси, используем httpx
            if proxy.startswith('socks'):
                self.use_httpx = True
                self.client = httpx.Client(proxies={
                    'http://': proxy,
                    'https://': proxy
                })
            else:
                # Для HTTP/HTTPS прокси используем requests
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

        print(f"Sending data to {LENS_ENDPOINT} via {
              'httpx' if self.use_httpx else 'requests'} with proxy: {self.config.get('proxy')}")

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

        print(f"Response code: {response.status_code}")

        # Update cookies based on response
        if 'set-cookie' in response.headers:
            self.cookies_manager.update_cookies(
                response.headers['set-cookie'])  # Обновляем куки

        if response.status_code != 200:
            print(f"Response headers: {response.headers}")
            print(f"Response body: {response.text}")
            raise LensError("Failed to load image",
                            response.status_code, response.headers, response.text)

        # Сохраняем полный текст ответа в файл для отладки
        response_file_path = "response_debug.txt"
        with open(response_file_path, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"Response saved to {response_file_path}")

        buffer_text = io.StringIO(response.text)
        tree = lxml.html.parse(buffer_text)

        r = tree.xpath("//script[@class='ds:1']")

        if not r:  # Если список пустой, возвращаем сообщение об ошибке
            print("Error: Expected data not found in response.")
            raise LensError("Failed to parse expected data from response",
                            response.status_code, response.headers, response.text)

        return json5.loads(r[0].text[len("AF_initDataCallback("):-2])


class Lens(LensCore):
    """A class for working with the Google Lens API, providing convenience methods."""

    def __init__(self, config=None, sleep_time=1000):
        super().__init__(config, sleep_time)

    def scan_by_file(self, file_path):
        """Scans an image at the specified path and returns the results."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError("Unsupported file type")
        img_data, dimensions = resize_image(file_path)
        return self.scan_by_data(img_data, 'image/jpeg', dimensions)

    def scan_by_buffer(self, buffer):
        """Scans an image from the buffer and returns the results."""
        kind = filetype.guess(buffer)
        if not kind or kind.mime not in SUPPORTED_MIMES:
            raise ValueError("Unsupported file type")
        img = Image.open(io.BytesIO(buffer))
        img.thumbnail((1000, 1000))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="JPEG")
        img_data = img_buffer.getvalue()
        return self.scan_by_data(img_data, 'image/jpeg', img.size)
