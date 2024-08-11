import requests
import io
import os
import time
import http.cookiejar as cookielib
import lxml.html
import json5
import filetype
from http.cookies import SimpleCookie
from PIL import Image
from .constants import LENS_ENDPOINT, HEADERS, MIME_TO_EXT, SUPPORTED_MIMES
from .utils import sleep, is_supported_mime
from .image_processing import resize_image


class LensError(Exception):
    """Class for error handling."""
    def __init__(self, message, code=None, headers=None, body=None):
        super().__init__(message)
        self.code = code
        self.headers = headers
        self.body = body


class LensCore:
    """Base class for working with the Google Lens API."""
    def __init__(self, config=None, sleep_time=1000):
        self.config = config if config else {}
        self.cookies = {}
        self.sleep_time = sleep_time
        self.parse_cookies()

    def parse_cookies(self):
        """Initialize cookies if they are passed in the config."""
        if 'headers' in self.config and 'cookie' in self.config['headers']:
            cookie_string = self.config['headers']['cookie']
            cookie = SimpleCookie(cookie_string)
            for key, morsel in cookie.items():
                self.cookies[key] = {
                    'name': key,
                    'value': morsel.value,
                    'expires': morsel['expires'] if morsel['expires'] else None
                }

    def generate_cookie_header(self, headers):
        """Adds cookies to request headers."""
        if self.cookies:
            # Filtering expired cookies
            self.cookies = {k: v for k, v in self.cookies.items() if not v['expires'] or v['expires'] > time.time()}
            headers['Cookie'] = '; '.join([f"{cookie['name']}={cookie['value']}" for cookie in self.cookies.values()])

    def update_cookies(self, set_cookie_header):
        """Updates the cookie from the Set-Cookie header."""
        if set_cookie_header:
            cookie = SimpleCookie(set_cookie_header)
            for key, morsel in cookie.items():
                self.cookies[key] = {
                    'name': key,
                    'value': morsel.value,
                    'expires': time.mktime(time.strptime(morsel['expires'], "%a, %d-%b-%Y %H:%M:%S %Z")) if morsel['expires'] else None
                }

    def scan_by_data(self, data, mime, dimensions):
        """Submits an image to the Google Lens API for analysis."""
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
        
        sleep(self.sleep_time)

        response = session.post(LENS_ENDPOINT, headers=headers, files=files)
        print(f"Response code: {response.status_code}")

        # Update cookies based on response
        if 'set-cookie' in response.headers:
            self.update_cookies(response.headers['set-cookie'])

        if response.status_code != 200:
            print(f"Response headers: {response.headers}")
            print(f"Response body: {response.text}")
            raise LensError("Failed to load image", response.status_code, response.headers, response.text)

        buffer_text = io.StringIO(response.text)
        tree = lxml.html.parse(buffer_text)

        r = tree.xpath("//script[@class='ds:1']")
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
