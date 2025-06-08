import logging
import os
import sys
from typing import Optional, Union

from PIL import ImageFont

from ..constants import (
    DEFAULT_FONT_PATH_LINUX,
    DEFAULT_FONT_PATH_MACOS,
    DEFAULT_FONT_PATH_WINDOWS,
    DEFAULT_FONT_SIZE_OVERLAY,
)
from ..exceptions import LensFontError

logger = logging.getLogger(__name__)

FontType = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]


def get_default_system_font_path() -> Optional[str]:
    if sys.platform.startswith("win"):
        font_path = os.path.join(
            os.environ.get("SystemRoot", "C:\\Windows"),
            "Fonts",
            DEFAULT_FONT_PATH_WINDOWS,
        )
        if os.path.exists(font_path):
            return font_path
    elif sys.platform == "darwin":
        potential_paths = [
            f"/System/Library/Fonts/Supplemental/{DEFAULT_FONT_PATH_MACOS}",
            f"/Library/Fonts/{DEFAULT_FONT_PATH_MACOS}",
            DEFAULT_FONT_PATH_MACOS,
        ]
        for path in potential_paths:
            try:
                ImageFont.truetype(path, DEFAULT_FONT_SIZE_OVERLAY)
                return path
            except IOError:
                continue
    else:  # Linux
        try:
            import subprocess

            result = subprocess.run(
                ["fc-match", "-f", "%{file}", DEFAULT_FONT_PATH_LINUX],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, Exception) as e:
            logger.debug(f"Could not find font via fc-match: {e}")
        return DEFAULT_FONT_PATH_LINUX

    logger.warning(
        "Could not automatically determine a default system font path. Please specify via config or --font."
    )
    return None


def get_font(
    font_path_override: Optional[str] = None, font_size_override: Optional[int] = None
) -> FontType:
    font_size = (
        font_size_override
        if font_size_override is not None
        else DEFAULT_FONT_SIZE_OVERLAY
    )
    font_path = font_path_override

    if not font_path:
        font_path = get_default_system_font_path()
        if font_path:
            logger.debug(f"Using system default font: {font_path}")
        else:
            logger.warning(
                "No font path specified and system default not found. Pillow will use its built-in default font."
            )
            try:
                return ImageFont.load_default()
            except Exception as e:
                logger.error(f"Error loading Pillow's default font: {e}")
                raise LensFontError(f"Error loading Pillow's default font: {e}")

    if not font_path:
        logger.error("Font path is not defined. Cannot load font.")
        raise LensFontError("The path to the font is not defined.")

    try:
        logger.debug(f"Attempting to load font: '{font_path}' with size {font_size}")
        return ImageFont.truetype(font_path, font_size)
    except IOError:
        logger.error(
            f"Font file not found or cannot be read: {font_path}. Pillow will try its default."
        )
        try:
            return ImageFont.load_default()
        except Exception as e:
            logger.error(
                f"Critical: Could not load specified font '{font_path}' nor Pillow's default font: {e}"
            )
            raise LensFontError(
                f"Failed to load the '{font_path}' font or the default Pillow font: {e}"
            )
    except Exception as e:
        logger.error(f"Unexpected error loading font '{font_path}': {e}", exc_info=True)
        raise LensFontError(f"Unexpected error while loading font '{font_path}': {e}")
