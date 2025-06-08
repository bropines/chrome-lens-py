# API
LENS_CRUPLOAD_ENDPOINT = "https://lensfrontend-pa.googleapis.com/v1/crupload"
DEFAULT_API_KEY = "AIzaSyDr2UxVnv_U85AbhhY8XSHSIavUW0DC-sY"
# https://github.com/AuroraWright/owocr


# headers
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_HEADERS = {
    "Content-Type": "application/x-protobuf",
    "X-Goog-Api-Key": DEFAULT_API_KEY,
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "*/*",
}

# img types
SUPPORTED_MIMES_FOR_PREPARE = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/gif",
    "image/tiff",
]
DEFAULT_IMAGE_MAX_DIMENSION = 1500

# region and time zone
DEFAULT_CLIENT_REGION = "US"
DEFAULT_CLIENT_TIME_ZONE = "America/New_York"
DEFAULT_OCR_LANG = ""

# Fonts
DEFAULT_FONT_SIZE_OVERLAY = 20
DEFAULT_FONT_PATH_WINDOWS = "arial.ttf"
DEFAULT_FONT_PATH_LINUX = "DejaVuSans.ttf"
DEFAULT_FONT_PATH_MACOS = "Arial.ttf"

# Configuration
APP_NAME_FOR_CONFIG = "chrome-lens-py"
DEFAULT_CONFIG_FILENAME = "config.json"
