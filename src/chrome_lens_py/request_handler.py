# request_handler.py

import requests
import io
import os
import time
import http.cookiejar as cookielib
import lxml.html
import json5
import filetype
from PIL import Image
from .constants import LENS_ENDPOINT, HEADERS, MIME_TO_EXT, SUPPORTED_MIMES
from .utils import sleep, is_supported_mime
from .image_processing import resize_image

class LensError(Exception):
    """Класс для обработки ошибок."""
    def __init__(self, message, code=None, headers=None, body=None):
        super().__init__(message)
        self.code = code
        self.headers = headers
        self.body = body

class LensCore:
    """Базовый класс для работы с Google Lens API."""
    def __init__(self, config=None, sleep_time=1000):
        self.config = config if config else {}
        self.cookies = {}
        self.sleep_time = sleep_time
        self.parse_cookies()

    def parse_cookies(self):
        """Инициализирует куки."""
        self.cookies = {
            'NID': {
                'name': 'NID',
                'value': '511=b-iPvznEQOKO1rDvyj7vkLrfe9i-PQiN0z_nhNv7lg-3_0YpQf2ZSKikTrlpu4W3mko4n2RAfYMho9NJqDEsmO-4BZG_iOqmufFZIzW4jiGJMmnaE1S3crNWwUL1HNnDqVUZZjRYkK_S-wsDWCuVul3Q_sCjucSvJ-CTN63GSjY',
                'expires': 1707050670000
            }
        }

    def generate_cookie_header(self, headers):
        """Добавляет куки в заголовки запроса."""
        if self.cookies:
            self.cookies = {k: v for k, v in self.cookies.items() if v['expires'] > time.time() * 1000}
            headers['Cookie'] = '; '.join([f"{cookie['name']}={cookie['value']}" for cookie in self.cookies.values()])

    def scan_by_data(self, data, mime, dimensions):
        """Отправляет изображение на анализ в Google Lens API."""
        headers = HEADERS.copy()
        self.generate_cookie_header(headers)

        session = requests.Session()
        session.cookies = cookielib.CookieJar()
        print(f"Sending data to {LENS_ENDPOINT}")

        file_name = f"image.{MIME_TO_EXT[mime]}"
        files = {
            'encoded_image': (file_name, data, mime),
            'original_width': (None, str(dimensions[0])),
            'original_height': (None, str(dimensions[1])),
            'processed_image_dimensions': (None, f"{dimensions[0]},{dimensions[1]}")
        }

        # Используем кастомное время задержки
        sleep(self.sleep_time)

        response = session.post(LENS_ENDPOINT, headers=headers, files=files)
        print(f"Response status code: {response.status_code}")

        if response.status_code != 200:
            print(f"Response headers: {response.headers}")
            print(f"Response body: {response.text}")
            raise LensError("Failed to upload image", response.status_code, response.headers, response.text)

        buffer_text = io.StringIO(response.text)
        tree = lxml.html.parse(buffer_text)

        r = tree.xpath("//script[@class='ds:1']")
        return json5.loads(r[0].text[len("AF_initDataCallback("):-2])

class Lens(LensCore):
    """Класс для работы с Google Lens API, предоставляющий удобные методы."""
    def __init__(self, config=None, sleep_time=1000):
        super().__init__(config, sleep_time)

    def scan_by_file(self, file_path):
        """Сканирует изображение по пути к файлу и возвращает результаты."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not is_supported_mime(file_path):
            raise ValueError("Unsupported file type")
        img_data, dimensions = resize_image(file_path)
        return self.scan_by_data(img_data, 'image/jpeg', dimensions)

    def scan_by_buffer(self, buffer):
        """Сканирует изображение из буфера и возвращает результаты."""
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
