import time
import logging
from http.cookies import SimpleCookie
import os
import pickle
from datetime import datetime
from .exceptions import LensCookieError
from .utils import get_default_config_dir

class CookiesManager:
    def __init__(self, config=None, cookie_file=None, logging_level=logging.WARNING):
        self.cookies = {}
        self.config = config or {}
        self.logging_level = logging_level
        logging.getLogger().setLevel(self.logging_level)
        self.imported_cookies = False  # Flag to check if cookies were imported directly

        # Get the cookie file path from config if not provided directly
        if cookie_file is None:
            cookie_file = self.config.get('cookie_file')

        if cookie_file is None:
            app_name = 'chrome-lens-py'  # Name of your application
            config_dir = get_default_config_dir(app_name)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            self.cookie_file = os.path.join(config_dir, 'cookies.pkl')
        else:
            self.cookie_file = os.path.abspath(cookie_file)

        logging.debug(f"Initialized CookiesManager with cookie file: {self.cookie_file}")

        # If cookies are specified in the config, import them
        cookies_from_config = self.config.get('cookies')
        if cookies_from_config:
            if isinstance(cookies_from_config, str):
                if os.path.isfile(cookies_from_config):
                    self.import_cookies_from_file(cookies_from_config)
                else:
                    self.import_cookies_from_string(cookies_from_config)
            elif isinstance(cookies_from_config, dict):
                self.parse_cookie_dict(cookies_from_config)
                self.save_cookies()
                self.imported_cookies = True
                logging.debug("Imported cookies from config dictionary.")

        # If cookies were not imported directly, load from the cookie_file
        if not self.imported_cookies:
            self.load_cookies()

    def load_cookies(self):
        """Loads cookies from a file or from config."""
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, 'rb') as f:
                    self.cookies = pickle.load(f)
                    logging.debug(f"Loaded cookies from file: {self.cookie_file}")
            except (FileNotFoundError, pickle.PickleError) as e:
                logging.warning(f"Error loading cookies from file: {e}")

    def import_cookies_from_file(self, cookie_file_path):
        """Imports cookies from a Netscape-format cookie file."""
        if os.path.isfile(cookie_file_path):
            self.parse_netscape_cookie_file(cookie_file_path)
            self.save_cookies()
            self.imported_cookies = True
            logging.debug(f"Imported cookies from file: {cookie_file_path}")
        else:
            logging.warning(f"Cookie file not found: {cookie_file_path}")

    def import_cookies_from_string(self, cookie_string):
        """Imports cookies from a cookie string."""
        self.parse_cookie_string(cookie_string)
        self.save_cookies()
        self.imported_cookies = True
        logging.debug("Imported cookies from string.")

    def parse_cookie_string(self, cookie_string):
        """Parses a cookie string and stores it."""
        logging.debug(f"Parsing cookie string: {cookie_string}")
        cookie = SimpleCookie(cookie_string)
        for key, morsel in cookie.items():
            self.cookies[key] = {
                'name': key,
                'value': morsel.value,
                'expires': self.ensure_timestamp(morsel.get('expires'))
            }

    def parse_cookie_dict(self, cookie_dict):
        """Parses a cookie dictionary and stores it."""
        logging.debug("Parsing cookie dictionary.")
        for key, cookie_data in cookie_dict.items():
            self.cookies[key] = {
                'name': cookie_data.get('name', key),
                'value': cookie_data['value'],
                'expires': self.ensure_timestamp(cookie_data.get('expires'))
            }

    def parse_netscape_cookie_file(self, file_path):
        """Parses a Netscape-format cookie file and imports all cookies."""
        logging.debug(f"Parsing Netscape cookie file: {file_path}")
        try:
            with open(file_path, 'r') as file:
                for line in file:
                    if not line.startswith('#') and line.strip():
                        parts = line.strip().split('\t')
                        if len(parts) >= 7:
                            try:
                                domain, flag, path, secure, expires, name, value = parts
                                self.cookies[name] = {
                                    'name': name,
                                    'value': value,
                                    'expires': self.ensure_timestamp(expires)
                                }
                            except IndexError as e:
                                logging.error(f"Error parsing cookie line: {line.strip()} - {e}")
            self.save_cookies()
        except (FileNotFoundError, IOError) as e:
            raise LensCookieError(f"Error reading Netscape cookie file: {e}") from e

    def generate_cookie_header(self):
        """Generates a cookie header for requests."""
        self.filter_expired_cookies()
        cookie_header = '; '.join(
            [f"{cookie['name']}={cookie['value']}" for cookie in self.cookies.values()])
        logging.debug(f"Generated cookie header: {cookie_header}")
        return cookie_header

    def filter_expired_cookies(self):
        """Filters out expired cookies."""
        logging.debug("Filtering expired cookies.")
        current_time = time.time()
        try:
            self.cookies = {k: v for k, v in self.cookies.items()
                            if not v['expires'] or v['expires'] > current_time}
        except ValueError as e:
            logging.error(f"Error filtering cookies: {e}. Rewriting cookies.")
            self.rewrite_cookies()

    def update_cookies(self, set_cookie_header):
        """Updates cookies from the Set-Cookie header and saves them."""
        logging.debug(f"Updating cookies from Set-Cookie header: {set_cookie_header}")
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
            logging.debug(f"Cookies saved to file: {self.cookie_file}")

    def rewrite_cookies(self):
        """Rewrites cookies from the original config or file if an error occurs."""
        logging.warning("Rewriting cookies from config or original file.")
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
                logging.debug(f"Failed to convert expires '{expires}' to float. Trying to parse date string.")
                try:
                    dt = datetime.strptime(expires, '%a, %d-%b-%Y %H:%M:%S GMT')
                    timestamp = dt.timestamp()
                    return float(timestamp)
                except ValueError as e:
                    logging.error(f"Failed to parse expires '{expires}' as datetime: {e}")
                    raise LensCookieError(f"Failed to convert expires '{expires}' to timestamp: {e}")
        return expires
