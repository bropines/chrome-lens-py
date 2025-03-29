import logging
import os
import pickle  # nosec
import time
from datetime import datetime
from http.cookies import SimpleCookie  # Keep for parsing string/dict formats if needed

import httpx  # Import httpx to check cookie object type

from .exceptions import LensCookieError
from .utils import get_default_config_dir


class CookiesManager:
    def __init__(self, config=None, cookie_file=None, logging_level=logging.WARNING):
        self.cookies = {}
        self.config = config or {}
        self.logging_level = logging_level
        # Setting level here might be overwritten; prefer setting it in the main entry point
        # logging.getLogger().setLevel(self.logging_level)
        self.imported_cookies = False  # Flag to check if cookies were imported directly

        # Get the cookie file path from config if not provided directly
        if cookie_file is None:
            cookie_file = self.config.get("cookie_file")

        # Determine default cookie file path
        if cookie_file is None:
            app_name = "chrome-lens-py"  # Name of your application
            config_dir = get_default_config_dir(app_name)
            if not os.path.exists(config_dir):
                try:
                    os.makedirs(config_dir)
                except OSError as e:
                    logging.error(
                        f"Failed to create config directory {config_dir}: {e}"
                    )
                    # Fallback to current directory if config dir creation fails
                    self.cookie_file = os.path.abspath("cookies.pkl")
            else:
                self.cookie_file = os.path.join(config_dir, "cookies.pkl")
        else:
            self.cookie_file = os.path.abspath(cookie_file)

        logging.debug(
            f"Initialized CookiesManager with cookie file: {self.cookie_file}"
        )

        # Load existing cookies first
        self.load_cookies()

        # If cookies are specified in the config (overrides loaded file), import them
        cookies_from_config = self.config.get("cookies")
        if cookies_from_config:
            self.cookies = (
                {}
            )  # Clear previously loaded cookies if new ones are provided
            if isinstance(cookies_from_config, str):
                if os.path.isfile(cookies_from_config):
                    self.import_cookies_from_file(
                        cookies_from_config
                    )  # Assumes Netscape format for file path in config
                else:
                    # Assume it's a cookie string header format if not a file
                    self.import_cookies_from_string(cookies_from_config)
            elif isinstance(cookies_from_config, dict):
                self.parse_cookie_dict(cookies_from_config)

            # Save the newly imported cookies from config immediately
            self.save_cookies()
            self.imported_cookies = True
            logging.debug(
                "Imported cookies specified in config, overwriting any loaded from file."
            )

    def load_cookies(self):
        """Loads cookies from the pickle file."""
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, "rb") as f:
                    loaded_cookies = pickle.load(f)  # nosec
                    if isinstance(loaded_cookies, dict):
                        self.cookies = loaded_cookies
                        logging.debug(
                            f"Loaded {len(self.cookies)} cookies from file: {self.cookie_file}"
                        )
                    else:
                        logging.warning(
                            f"Invalid cookie data type found in {self.cookie_file}, expected dict. Ignoring."
                        )
                        self.cookies = {}
            except (FileNotFoundError, pickle.PickleError, EOFError) as e:
                logging.warning(
                    f"Error loading cookies from file {self.cookie_file}: {e}. Starting with empty cookies."
                )
                self.cookies = {}
            except Exception as e:
                logging.error(
                    f"Unexpected error loading cookies from {self.cookie_file}: {e}. Starting with empty cookies.",
                    exc_info=True,
                )
                self.cookies = {}
        else:
            logging.debug(
                f"Cookie file not found: {self.cookie_file}. Starting with empty cookies."
            )
            self.cookies = {}

    def import_cookies_from_file(self, cookie_file_path):
        """Imports cookies from a Netscape-format cookie file."""
        logging.debug(f"Importing cookies from Netscape file: {cookie_file_path}")
        if os.path.isfile(cookie_file_path):
            self.parse_netscape_cookie_file(cookie_file_path)
            # Save happens in the __init__ after this call if needed
        else:
            logging.warning(f"Cookie file not found during import: {cookie_file_path}")

    def import_cookies_from_string(self, cookie_string):
        """Imports cookies from a 'Cookie: name=value; name2=value2' string."""
        logging.debug("Importing cookies from string.")
        self.parse_cookie_string(cookie_string)
        # Save happens in the __init__ after this call if needed

    def parse_cookie_string(self, cookie_string):
        """Parses a 'Cookie: name=value; name2=value2' string."""
        logging.debug(f"Parsing cookie string: '{cookie_string[:50]}...'")
        try:
            cookie = SimpleCookie(cookie_string)
            for key, morsel in cookie.items():
                self.cookies[key] = {
                    "name": key,
                    "value": morsel.value,
                    "expires": self._parse_expires(morsel.get("expires")),
                    # Storing domain/path might be useful if httpx needs them later,
                    # but httpx usually manages this itself based on request URL.
                    "domain": morsel.get("domain"),
                    "path": morsel.get("path"),
                }
        except Exception as e:
            logging.error(f"Failed to parse cookie string: {e}")
            raise LensCookieError(f"Failed to parse cookie string: {e}") from e

    def parse_cookie_dict(self, cookie_dict):
        """Parses a dictionary of cookies (e.g., from JSON)."""
        logging.debug("Parsing cookie dictionary.")
        if not isinstance(cookie_dict, dict):
            logging.error("Failed to parse cookie dict: input is not a dictionary.")
            raise LensCookieError("Invalid input: cookie_dict must be a dictionary.")
        for key, cookie_data in cookie_dict.items():
            if isinstance(cookie_data, dict) and "value" in cookie_data:
                self.cookies[key] = {
                    "name": cookie_data.get("name", key),
                    "value": cookie_data["value"],
                    "expires": self._parse_expires(cookie_data.get("expires")),
                    "domain": cookie_data.get("domain"),
                    "path": cookie_data.get("path"),
                }
            elif isinstance(cookie_data, str):  # Allow simple key: value dict
                self.cookies[key] = {
                    "name": key,
                    "value": cookie_data,
                    "expires": None,
                    "domain": None,
                    "path": None,
                }
            else:
                logging.warning(
                    f"Skipping invalid cookie entry for key '{key}': {cookie_data}"
                )

    def parse_netscape_cookie_file(self, file_path):
        """Parses a Netscape-format cookie file and updates self.cookies."""
        logging.debug(f"Parsing Netscape cookie file: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        parts = line.split("\t")
                        if len(parts) == 7:
                            domain, flag, path, secure, expires_str, name, value = parts
                            self.cookies[name] = {
                                "name": name,
                                "value": value,
                                "expires": self._parse_expires(expires_str),
                                "domain": domain,
                                "path": path,
                                "secure": secure.upper() == "TRUE",
                            }
                        elif (
                            len(parts) == 6
                        ):  # Handle files without the initial domain flag correctly
                            # domain_implicit = parts[0]
                            path = parts[2]
                            secure = parts[3].upper() == "TRUE"
                            expires_str = parts[4]
                            name = parts[5]
                            value = parts[6]  # IndexError here if parts==6
                            logging.warning(
                                f"Cookie line has 6 parts, check format: {line}"
                            )
                            # Attempt to parse anyway if possible, might be incorrect
                            # self.cookies[name] = { ... } # Decide if you want to handle 6-part lines
                        else:
                            logging.warning(
                                f"Skipping malformed cookie line (expected 7 tab-separated parts): {line}"
                            )
                    except IndexError as e:
                        logging.error(
                            f"Error parsing cookie line elements: {line.strip()} - {e}"
                        )
                    except ValueError as e:
                        logging.error(
                            f"Error converting expires timestamp on line: {line.strip()} - {e}"
                        )
        except (FileNotFoundError, IOError) as e:
            raise LensCookieError(
                f"Error reading Netscape cookie file {file_path}: {e}"
            ) from e
        except Exception as e:
            raise LensCookieError(
                f"Unexpected error parsing Netscape cookie file {file_path}: {e}"
            ) from e

    def generate_cookie_header(self):
        """
        Generates a 'Cookie: name=value; name2=value2' string for potential external use.
        Less critical now as httpx manages cookies internally for requests.
        """
        self.filter_expired_cookies()
        if not self.cookies:
            return ""
        header_parts = []
        for cookie in self.cookies.values():
            # Basic check if value exists
            if "name" in cookie and "value" in cookie and cookie["value"] is not None:
                header_parts.append(f"{cookie['name']}={cookie['value']}")
            else:
                logging.warning(
                    f"Skipping cookie with missing name or value: {cookie.get('name', 'N/A')}"
                )

        cookie_header = "; ".join(header_parts)
        logging.debug(f"Generated cookie header string: {cookie_header[:100]}...")
        return cookie_header

    def filter_expired_cookies(self):
        """Filters out expired cookies from self.cookies based on the 'expires' timestamp."""
        logging.debug("Filtering expired cookies.")
        current_time = time.time()
        try:
            initial_count = len(self.cookies)
            self.cookies = {
                k: v
                for k, v in self.cookies.items()
                if v.get("expires") is None
                or v["expires"] == 0
                or v["expires"] > current_time
            }
            filtered_count = len(self.cookies)
            if initial_count != filtered_count:
                logging.debug(
                    f"Filtered {initial_count - filtered_count} expired cookies."
                )
        except TypeError as e:
            # This might happen if 'expires' is not a comparable type (e.g., unexpected string)
            logging.error(
                f"Error filtering cookies due to invalid 'expires' data: {e}. Attempting rewrite."
            )
            # Consider resetting or trying to fix cookies instead of just rewriting
            # For now, let's log the problematic cookies
            for k, v in self.cookies.items():
                if v.get("expires") is not None and not isinstance(
                    v["expires"], (int, float, type(None))
                ):
                    logging.error(
                        f"Problematic cookie expires value for key '{k}': {v['expires']} (type: {type(v['expires'])})"
                    )
            # Optional: self.rewrite_cookies() # Or maybe just clear them: self.cookies = {}
            # Let's try removing only the bad ones
            fixed_cookies = {}
            for k, v in self.cookies.items():
                expires = v.get("expires")
                if (
                    expires is None
                    or expires == 0
                    or isinstance(expires, (int, float))
                    and expires > current_time
                ):
                    fixed_cookies[k] = v
                else:
                    logging.warning(
                        f"Removing cookie '{k}' due to invalid or expired 'expires' value: {expires}"
                    )
            self.cookies = fixed_cookies

    def update_cookies(self, cookie_jar):
        """
        Updates self.cookies from an external cookie jar (e.g., httpx.Cookies)
        and saves the updated cookies.
        """
        logging.debug(
            f"Attempting to update cookies from object of type: {type(cookie_jar)}"
        )
        updated = False
        if isinstance(cookie_jar, httpx.Cookies):
            # Iterate through httpx.Cookies jar
            for cookie in cookie_jar:
                # httpx cookie attributes: name, value, domain, path, expires (timestamp), secure, _rest
                expires_timestamp = None
                if cookie.expires is not None:
                    # httpx stores expires as seconds since epoch directly
                    try:
                        expires_timestamp = float(cookie.expires)
                    except (ValueError, TypeError):
                        logging.warning(
                            f"Could not parse expires timestamp '{cookie.expires}' for cookie '{cookie.name}'. Setting to None."
                        )

                # Check if cookie changed or is new
                current_cookie = self.cookies.get(cookie.name)
                new_value = cookie.value
                if (
                    not current_cookie
                    or current_cookie.get("value") != new_value
                    or current_cookie.get("expires") != expires_timestamp
                ):
                    self.cookies[cookie.name] = {
                        "name": cookie.name,
                        "value": new_value,
                        "expires": expires_timestamp,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "secure": cookie.secure,
                        # Add other relevant attributes if needed from cookie._rest
                    }
                    updated = True
                    logging.debug(f"Updated/added cookie: {cookie.name}")

        elif isinstance(
            cookie_jar, str
        ):  # Handle Set-Cookie header string (less likely now)
            logging.debug(
                f"Updating cookies from Set-Cookie header string: {cookie_jar[:100]}..."
            )
            try:
                cookie = SimpleCookie(cookie_jar)
                for key, morsel in cookie.items():
                    expires_timestamp = self._parse_expires(morsel.get("expires"))
                    # Check if cookie changed or is new
                    current_cookie = self.cookies.get(key)
                    new_value = morsel.value
                    if (
                        not current_cookie
                        or current_cookie.get("value") != new_value
                        or current_cookie.get("expires") != expires_timestamp
                    ):
                        self.cookies[key] = {
                            "name": key,
                            "value": new_value,
                            "expires": expires_timestamp,
                            "domain": morsel.get("domain"),
                            "path": morsel.get("path"),
                            "secure": morsel.get("secure"),
                        }
                        updated = True
                        logging.debug(f"Updated/added cookie from string: {key}")
            except Exception as e:
                logging.error(f"Failed to parse Set-Cookie string: {e}")

        else:
            logging.warning(
                f"Unsupported cookie_jar type for update: {type(cookie_jar)}"
            )

        if updated:
            self.filter_expired_cookies()  # Clean up before saving
            self.save_cookies()
        else:
            logging.debug("No cookie updates detected.")

    def save_cookies(self):
        """Saves the current state of self.cookies to the pickle file."""
        # Ensure the directory exists before trying to save
        cookie_dir = os.path.dirname(self.cookie_file)
        if not os.path.exists(cookie_dir):
            try:
                os.makedirs(cookie_dir)
                logging.debug(f"Created directory for cookie file: {cookie_dir}")
            except OSError as e:
                logging.error(
                    f"Failed to create directory {cookie_dir} for saving cookies: {e}. Cannot save cookies."
                )
                return  # Abort saving

        try:
            with open(self.cookie_file, "wb") as f:
                pickle.dump(self.cookies, f)
                logging.debug(
                    f"Saved {len(self.cookies)} cookies to file: {self.cookie_file}"
                )
        except (IOError, pickle.PickleError) as e:
            logging.error(f"Error saving cookies to file {self.cookie_file}: {e}")
        except Exception as e:
            logging.error(
                f"Unexpected error saving cookies to {self.cookie_file}: {e}",
                exc_info=True,
            )

    def rewrite_cookies(self):
        """
        Clears current cookies and reloads from the original config or file.
        Use cautiously, might lose session cookies.
        """
        logging.warning(
            "Rewriting cookies: Clearing current state and reloading from config/file."
        )
        self.cookies = {}
        self.imported_cookies = False  # Reset flag to allow reloading
        # Re-run the initialization logic for loading/importing
        self.__init__(
            config=self.config,
            cookie_file=self.cookie_file,
            logging_level=self.logging_level,
        )
        # Save the reloaded state
        self.save_cookies()

    def _parse_expires(self, expires_input):
        """Internal helper to parse various expires formats into a Unix timestamp (float or None)."""
        if expires_input is None or expires_input == "":
            return None
        if isinstance(expires_input, (int, float)):
            # Assume it's already a timestamp if numeric
            # Check for '0' which might mean session cookie or invalid Netscape format
            return float(expires_input) if expires_input != 0 else None
        if isinstance(expires_input, str):
            try:
                # Try direct float conversion (common in Netscape files)
                ts = float(expires_input)
                return ts if ts != 0 else None
            except ValueError:
                # Try parsing common date formats (e.g., from Set-Cookie headers)
                # Format: Wdy, DD Mon YYYY HH:MM:SS GMT
                common_formats = [
                    "%a, %d %b %Y %H:%M:%S %Z",  # Standard GMT format
                    "%a, %d-%b-%Y %H:%M:%S %Z",  # Variation with hyphen
                    "%A, %d-%b-%y %H:%M:%S %Z",  # Older format
                    # Add other formats if needed
                ]
                # Attempt to parse with GMT timezone awareness
                expires_input_gmt = expires_input.replace(
                    "GMT", ""
                ).strip()  # Remove GMT for strptime
                if not expires_input_gmt.endswith(
                    "Z"
                ):  # Ensure timezone info consistency if needed
                    expires_input_gmt += " GMT"  # Assume GMT if not specified? Risky.

                for fmt in common_formats:
                    try:
                        # Ensure the timezone part matches exactly or handle it
                        # For simplicity, let's assume GMT if %Z is used
                        dt = datetime.strptime(
                            expires_input_gmt, fmt.replace("%Z", "GMT")
                        )
                        # Convert naive datetime assumed to be GMT to timestamp
                        timestamp = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
                        logging.debug(
                            f"Parsed date string '{expires_input}' to timestamp: {timestamp}"
                        )
                        return float(timestamp)
                    except ValueError:
                        continue  # Try next format
                # If all formats fail
                logging.warning(
                    f"Failed to parse expires string '{expires_input}' into a known date format or timestamp."
                )
                return None
        # If input is not a recognized type
        logging.warning(
            f"Unparseable expires value type: {type(expires_input)}, value: {expires_input}"
        )
        return None
