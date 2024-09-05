import time
import logging  # Импортируем модуль логирования
from http.cookies import SimpleCookie
import os
import pickle
from email.utils import parsedate_to_datetime
from .exceptions import LensCookieError


class CookiesManager:
    def __init__(self, config=None, cookie_file='cookies.pkl', enable_logging=False):
        self.cookies = {}
        self.config = config or {}
        self.cookie_file = os.path.join(os.path.dirname(__file__), cookie_file)
        # Получаем информацию о том, нужно ли логировать
        self.enable_logging = enable_logging
        self.load_cookies()

        if self.enable_logging:
            logging.info(f"Initialized CookiesManager with cookie file: {
                         self.cookie_file}")

    def log(self, message, level=logging.INFO):
        """Вспомогательный метод для логирования, который учитывает флаг enable_logging.
            Logs a message if logging is enabled.
        """
        if self.enable_logging:
            logging.log(level, message)

    def load_cookies(self):
        """Loads cookies from a file or from config."""
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, 'rb') as f:
                    self.cookies = pickle.load(f)
                    self.log(f"Loaded cookies from file: {self.cookie_file}")
            except (FileNotFoundError, pickle.PickleError) as e:
                self.log(f"Error loading cookies from file: {
                    e}", level=logging.WARNING)

        if 'headers' in self.config and 'cookie' in self.config['headers']:
            cookie_data = self.config['headers']['cookie']

            if isinstance(cookie_data, str) and os.path.isfile(cookie_data):
                self.parse_netscape_cookie_file(cookie_data)
            elif isinstance(cookie_data, str):
                self.parse_cookie_string(cookie_data)
            elif isinstance(cookie_data, dict):
                self.parse_cookie_dict(cookie_data)
            else:
                self.log(f"Unexpected cookie data type in config: {type(cookie_data)}",
                         level=logging.WARNING)
            self.save_cookies()

    def parse_cookie_string(self, cookie_string):
        """Parses cookie string and stores it."""
        self.log(f"Parsing cookie string: {cookie_string}", logging.DEBUG)
        cookie = SimpleCookie(cookie_string)
        for key, morsel in cookie.items():
            self.cookies[key] = {
                'name': key,
                'value': morsel.value,
                'expires': self.ensure_timestamp(morsel.get('expires'))
            }

    def parse_cookie_dict(self, cookie_dict):
        """Parses cookie dict and stores it."""
        self.log("Parsing cookie dictionary.", logging.DEBUG)
        for key, cookie_data in cookie_dict.items():
            self.cookies[key] = {
                'name': cookie_data.get('name', key),
                'value': cookie_data['value'],
                'expires': self.ensure_timestamp(cookie_data.get('expires'))
            }

    def parse_netscape_cookie_file(self, file_path):
        """Parses a Netscape format cookie file and imports all cookies."""
        self.log(f"Parsing Netscape cookie file: {file_path}")
        try:
            with open(file_path, 'r') as file:
                for line in file:
                    if not line.startswith('#') and line.strip():
                        parts = line.split('\t')
                        if len(parts) >= 7:
                            try:
                                domain, _, _, _, expires, name, value = parts
                                self.cookies[name] = {
                                    'name': name,
                                    'value': value.strip(),
                                    'expires': self.ensure_timestamp(expires)
                                }
                            except IndexError as e:
                                self.log(f"Error parsing cookie line: {
                                         line.strip()} - {e}", logging.ERROR)

            self.save_cookies()
        except (FileNotFoundError, IOError) as e:
            raise LensCookieError(
                f"Error reading Netscape cookie file: {e}") from e

    def generate_cookie_header(self):
        """Generates a cookie header for requests."""
        self.filter_expired_cookies()
        cookie_header = '; '.join(
            [f"{cookie['name']}={cookie['value']}" for cookie in self.cookies.values()])
        self.log(f"Generated cookie header: {cookie_header}", logging.DEBUG)
        return cookie_header

    def filter_expired_cookies(self):
        """Filters out expired cookies."""
        self.log("Filtering expired cookies.")
        current_time = time.time()
        try:
            self.cookies = {k: v for k, v in self.cookies.items(
            ) if not v['expires'] or v['expires'] > current_time}
        except ValueError as e:
            self.log(f"Error filtering cookies: {
                     e}. Rewriting cookies.", logging.ERROR)
            self.rewrite_cookies()

    def update_cookies(self, set_cookie_header):
        """Updates cookies from the Set-Cookie header and saves them."""
        self.log(
            f"Updating cookies from Set-Cookie header: {set_cookie_header}")
        if set_cookie_header:
            cookie = SimpleCookie(set_cookie_header)
            for key, morsel in cookie.items():
                self.cookies[key] = {
                    'name': key,
                    'value': morsel.value,
                    'expires': self.ensure_timestamp(morsel['expires']) if morsel['expires'] else None
                }
        self.save_cookies()

    def save_cookies(self):
        """Saves cookies to a file."""
        with open(self.cookie_file, 'wb') as f:
            pickle.dump(self.cookies, f)
            self.log(f"Cookies saved to file: {self.cookie_file}")

    def rewrite_cookies(self):
        """Rewrites cookies from the original config or file if an error occurs."""
        self.log("Rewriting cookies from config or original file.",
                 logging.WARNING)
        self.cookies = {}
        self.load_cookies()
        self.save_cookies()

    @staticmethod
    def ensure_timestamp(expires):
        """Ensures that the expires value is a Unix timestamp."""
        if isinstance(expires, (int, float)):
            return expires
        if isinstance(expires, str):
            try:
                return float(expires)
            except ValueError:
                raise LensCookieError(
                    f"Failed to convert expires '{expires}' to timestamp: Invalid date value or format")
        return expires
