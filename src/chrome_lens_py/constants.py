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
# Image encoding. These mirror Chromium's lens overlay so payloads match what
# the server is tuned for. See components/lens/lens_features.cc and
# components/lens/lens_bitmap_processing.cc.
#   - JPEG quality 40 (kLensOverlayImageCompressionQuality)
#   - downscale only when area > max_area AND (width > max_w OR height > max_h)
DEFAULT_IMAGE_MAX_AREA = 1500000
DEFAULT_IMAGE_MAX_WIDTH = 1600
DEFAULT_IMAGE_MAX_HEIGHT = 1600
DEFAULT_IMAGE_JPEG_QUALITY = 40

# Retained for backwards compatibility with older configs/callers.
DEFAULT_IMAGE_MAX_DIMENSION = 1500

# Transport
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_POOL_TIMEOUT = 10
DEFAULT_MAX_RETRIES = 2
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# region and time zone
DEFAULT_CLIENT_REGION = "US"
DEFAULT_CLIENT_TIME_ZONE = "America/New_York"
DEFAULT_OCR_LANG = ""

# Translation overlay rendering (mirrors chrome/browser/resources/lens/overlay)
RENDER_MIN_FONT_SIZE = 3
RENDER_MAX_FONT_SIZE = 150
RENDER_OUTLINE_RATIO = 0.02

# Languages Lens treats as right-to-left (RTL_LANGUAGES in text_layer.ts).
RTL_LANGUAGES = frozenset(
    {
        "ar",  # Arabic
        "bal",  # Baluchi
        "ckb",  # Kurdish (Sorani)
        "dv",  # Divehi
        "fa",  # Persian / Dari
        "he",  # Hebrew
        "iw",  # Hebrew (legacy code)
        "ji",  # Yiddish (legacy code)
        "ks",  # Kashmiri
        "ps",  # Pashto
        "sd",  # Sindhi
        "ug",  # Uyghur
        "ur",  # Urdu
        "yi",  # Yiddish
    }
)

# Fonts
DEFAULT_FONT_SIZE_OVERLAY = 20
DEFAULT_FONT_PATH_WINDOWS = "arial.ttf"
DEFAULT_FONT_PATH_LINUX = "DejaVuSans.ttf"
DEFAULT_FONT_PATH_MACOS = "Arial.ttf"

# Configuration
APP_NAME_FOR_CONFIG = "chrome-lens-py"
DEFAULT_CONFIG_FILENAME = "config.json"
