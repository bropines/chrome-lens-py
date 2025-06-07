import logging
import os
import sys
from typing import Optional

from PIL import ImageFont

from ..constants import (
    DEFAULT_FONT_SIZE_OVERLAY,
    DEFAULT_FONT_PATH_WINDOWS,
    DEFAULT_FONT_PATH_LINUX,
    DEFAULT_FONT_PATH_MACOS
)
from ..exceptions import LensFontError

logger = logging.getLogger(__name__)

def get_default_system_font_path() -> Optional[str]:
    """Пытается определить путь к системному шрифту по умолчанию."""
    if sys.platform.startswith("win"):
        # Проверяем наличие Arial в стандартной папке Fonts
        font_path = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", DEFAULT_FONT_PATH_WINDOWS)
        if os.path.exists(font_path):
            return font_path
    elif sys.platform == "darwin":
        # На macOS Arial обычно доступен, но пути могут варьироваться.
        # Это простой пример, может потребоваться более сложная логика поиска.
        # `/System/Library/Fonts/Supplemental/Arial.ttf` или просто `Arial.ttf` (Pillow может найти)
        potential_paths = [
            f"/System/Library/Fonts/Supplemental/{DEFAULT_FONT_PATH_MACOS}",
            f"/Library/Fonts/{DEFAULT_FONT_PATH_MACOS}",
            DEFAULT_FONT_PATH_MACOS # Pillow может сам найти по имени
        ]
        for path in potential_paths:
            try:
                ImageFont.truetype(path, DEFAULT_FONT_SIZE_OVERLAY) # Проверка доступности
                return path
            except IOError:
                continue
    else: # Linux и другие
        # На Linux ситуация сложнее, шрифты могут быть где угодно.
        # DejaVuSans часто установлен. Пользователь может указать путь в конфиге.
        # Попробуем найти через fc-match (если установлен) или просто вернем имя.
        try:
            import subprocess
            result = subprocess.run(['fc-match', '-f', '%{file}', DEFAULT_FONT_PATH_LINUX], capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except FileNotFoundError: # fc-match не найден
            pass
        except Exception as e:
            logger.debug(f"Error trying to find font with fc-match: {e}")
        # Если не нашли, вернем имя, Pillow попытается найти
        return DEFAULT_FONT_PATH_LINUX

    logger.warning("Could not automatically determine a default system font path. Please specify via config or --font.")
    return None


def get_font(
    font_path_override: Optional[str] = None,
    font_size_override: Optional[int] = None
) -> ImageFont.FreeTypeFont:
    """
    Загружает объект шрифта Pillow.
    Приоритет: override -> config (через build_app_config) -> системный по умолчанию.
    """
    # Значения по умолчанию для размера
    font_size = font_size_override if font_size_override is not None else DEFAULT_FONT_SIZE_OVERLAY

    # Определение пути к шрифту
    font_path = font_path_override
    if not font_path:
        # Если путь не передан напрямую, пытаемся получить системный по умолчанию
        font_path = get_default_system_font_path()
        if font_path:
            logger.debug(f"Using system default font: {font_path}")
        else:
            # Если и системный не нашелся, Pillow будет использовать свой встроенный шрифт
            logger.warning("No font path specified and system default not found. Pillow will use its built-in default font.")
            try:
                # Pillow's load_default() не принимает размер напрямую для FreeTypeFont
                # но мы можем попытаться загрузить его, а потом, если это простой шрифт, использовать font_size
                font = ImageFont.load_default()
                # Попытка создать FreeTypeFont из дефолтного с нужным размером (может не сработать для bitmap шрифтов)
                if hasattr(font, "path") and font.path: # если у дефолтного есть путь
                     return ImageFont.truetype(font.path, font_size)
                # Если дефолтный шрифт - это не FreeType или не имеет пути, вернем его как есть
                # Размер может не примениться
                logger.warning("Pillow's default font might not support custom size. Using its default size.")
                return font
            except Exception as e:
                logger.error(f"Error loading Pillow's default font: {e}")
                raise LensFontError(f"Ошибка загрузки шрифта Pillow по умолчанию: {e}")


    if not font_path: # Если все еще нет пути (например, get_default_system_font_path вернул None и override не было)
        logger.error("Font path is not defined. Cannot load font.")
        raise LensFontError("Путь к шрифту не определен.")

    try:
        logger.debug(f"Attempting to load font: '{font_path}' with size {font_size}")
        return ImageFont.truetype(font_path, font_size)
    except IOError:
        logger.error(f"Font file not found or cannot be read: {font_path}. Pillow will try its default.")
        try:
            return ImageFont.load_default() # Возвращаем дефолтный шрифт Pillow как fallback
        except Exception as e:
            logger.error(f"Critical: Could not load specified font '{font_path}' nor Pillow's default font: {e}")
            raise LensFontError(f"Не удалось загрузить шрифт '{font_path}' или шрифт Pillow по умолчанию: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading font '{font_path}': {e}", exc_info=True)
        raise LensFontError(f"Непредвиденная ошибка при загрузке шрифта '{font_path}': {e}")