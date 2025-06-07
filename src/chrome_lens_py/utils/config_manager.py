import json
import os
import logging
import sys
from typing import Dict, Any, Optional

from ..constants import APP_NAME_FOR_CONFIG, DEFAULT_CONFIG_FILENAME, \
                        DEFAULT_CLIENT_REGION, DEFAULT_CLIENT_TIME_ZONE, \
                        DEFAULT_API_KEY
from ..exceptions import LensConfigError

logger = logging.getLogger(__name__)

def get_default_config_dir(app_name: str = APP_NAME_FOR_CONFIG) -> str:
    """Возвращает путь к директории конфигурации по умолчанию для приложения."""
    home_dir = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        config_dir = os.path.join(home_dir, ".config", app_name)
    elif sys.platform == "darwin":
        config_dir = os.path.expanduser(f"~/Library/Application Support/{app_name}")
    else: # Unix/Linux
        config_dir = os.path.join(
            os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), app_name
        )
    return config_dir

def get_config_file_path(config_file_override: Optional[str] = None) -> str:
    """
    Определяет путь к файлу конфигурации.
    Приоритет: override -> env LENS_CONFIG_PATH -> default location.
    """
    if config_file_override:
        if os.path.isfile(config_file_override):
            logger.debug(f"Using config file override: {config_file_override}")
            return config_file_override
        else:
            logger.warning(f"Config file override '{config_file_override}' not found. Falling back.")

    env_config_path = os.getenv("LENS_CONFIG_PATH")
    if env_config_path and os.path.isfile(env_config_path):
        logger.debug(f"Using config file from LENS_CONFIG_PATH: {env_config_path}")
        return env_config_path

    default_dir = get_default_config_dir()
    default_path = os.path.join(default_dir, DEFAULT_CONFIG_FILENAME)
    logger.debug(f"Using default config file path: {default_path}")
    return default_path


def load_config(config_file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Загружает конфигурацию из JSON файла.
    Если файл не указан, пытается загрузить из пути по умолчанию.
    Возвращает пустой словарь, если файл не найден или ошибка парсинга.
    """
    effective_path = config_file_path or get_config_file_path()
    config: Dict[str, Any] = {}

    if os.path.isfile(effective_path):
        try:
            with open(effective_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from: {effective_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from config file '{effective_path}': {e}")
            raise LensConfigError(f"Ошибка декодирования JSON в файле конфигурации '{effective_path}': {e}")
        except IOError as e:
            logger.error(f"IOError reading config file '{effective_path}': {e}")
            raise LensConfigError(f"Ошибка ввода-вывода при чтении файла конфигурации '{effective_path}': {e}")
    else:
        logger.info(f"Config file not found at '{effective_path}'. Using default/CLI values.")
        # Возвращаем пустой конфиг, чтобы потом можно было смержить с дефолтами
    return config

def save_config(config_data: Dict[str, Any], config_file_path: Optional[str] = None) -> None:
    """Сохраняет конфигурацию в JSON файл."""
    effective_path = config_file_path or get_config_file_path()
    config_dir = os.path.dirname(effective_path)

    try:
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            logger.info(f"Created config directory: {config_dir}")
    except OSError as e:
        logger.error(f"Error creating config directory '{config_dir}': {e}")
        raise LensConfigError(f"Ошибка создания директории конфигурации '{config_dir}': {e}")

    try:
        with open(effective_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        logger.info(f"Configuration saved to: {effective_path}")
    except (IOError, TypeError) as e:
        logger.error(f"Error saving config to file '{effective_path}': {e}")
        raise LensConfigError(f"Ошибка сохранения конфигурации в файл '{effective_path}': {e}")


def get_effective_config_value(
    cli_arg_value: Optional[Any],
    config_file_value: Optional[Any],
    env_var_name: Optional[str],
    default_value: Any
) -> Any:
    """
    Определяет эффективное значение параметра конфигурации.
    Приоритет: CLI > Environment Variable > Config File > Default.
    """
    if cli_arg_value is not None:
        return cli_arg_value

    if env_var_name:
        env_value_str = os.getenv(env_var_name)
        if env_value_str is not None:
            # Пытаемся преобразовать к типу default_value, если он есть
            if default_value is not None and not isinstance(default_value, type(None)):
                try:
                    if isinstance(default_value, bool): # bool("False") is True
                        if env_value_str.lower() in ["false", "0", "no", "n"]: return False
                        if env_value_str.lower() in ["true", "1", "yes", "y"]: return True
                    return type(default_value)(env_value_str)
                except ValueError:
                    logger.warning(f"Could not cast env var {env_var_name} ('{env_value_str}') to type {type(default_value)}. Using as string.")
            return env_value_str # Возвращаем как строку, если тип не определен или ошибка каста

    if config_file_value is not None:
        return config_file_value

    return default_value


def build_app_config(
    cli_args: Optional[Dict[str, Any]] = None,
    config_file_path_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Собирает итоговую конфигурацию приложения, объединяя значения из
    CLI, переменных окружения, файла конфигурации и значений по умолчанию.
    """
    loaded_config_from_file = load_config(config_file_path_override)
    cli = cli_args or {}

    # Порядок: CLI > ENV > File > Default
    # Для API ключа не делаем ENV переменную по умолчанию из соображений безопасности,
    # но если очень нужно, можно добавить LENS_API_KEY
    final_config = {
        "api_key": get_effective_config_value(
            cli.get("api_key"), loaded_config_from_file.get("api_key"), None, DEFAULT_API_KEY
        ),
        "client_region": get_effective_config_value(
            cli.get("client_region"), loaded_config_from_file.get("client_region"), "LENS_CLIENT_REGION", DEFAULT_CLIENT_REGION
        ),
        "client_time_zone": get_effective_config_value(
            cli.get("client_time_zone"), loaded_config_from_file.get("client_time_zone"), "LENS_CLIENT_TIME_ZONE", DEFAULT_CLIENT_TIME_ZONE
        ),
        "proxy": get_effective_config_value(
            cli.get("proxy"), loaded_config_from_file.get("proxy"), "LENS_PROXY", None
        ),
        "timeout": get_effective_config_value(
            cli.get("timeout"), loaded_config_from_file.get("timeout"), "LENS_TIMEOUT", 60
        ),
        "font_path": get_effective_config_value(
            cli.get("font_path"), loaded_config_from_file.get("font_path"), "LENS_FONT_PATH", None # Default будет определен в font_manager
        ),
        "font_size": get_effective_config_value(
            cli.get("font_size"), loaded_config_from_file.get("font_size"), "LENS_FONT_SIZE", None # Default будет определен в font_manager
        ),
        "logging_level": get_effective_config_value(
            cli.get("logging_level"), loaded_config_from_file.get("logging_level"), "LENS_LOGGING_LEVEL", "WARNING"
        ).upper(),
         # Поля специфичные для CLI, не хранятся в файле по умолчанию, но могут быть добавлены при --update-config
        "ocr_lang": cli.get("ocr_lang"), # Извлекаем из CLI, если есть
        "target_lang": cli.get("target_lang"),
        "source_lang": cli.get("source_lang"),
        "output_overlay_path": cli.get("output_overlay_path"),
        "image_path": cli.get("image_path")
    }

    # Преобразование timeout и font_size в int, если они строки
    if isinstance(final_config["timeout"], str):
        try:
            final_config["timeout"] = int(final_config["timeout"])
        except ValueError:
            logger.warning(f"Invalid timeout value '{final_config['timeout']}'. Using default 60.")
            final_config["timeout"] = 60
    if isinstance(final_config["font_size"], str):
        try:
            final_config["font_size"] = int(final_config["font_size"])
        except ValueError:
            logger.warning(f"Invalid font_size value '{final_config['font_size']}'. Using None.")
            final_config["font_size"] = None


    logger.debug(f"Final configuration built: { {k:v for k,v in final_config.items() if k != 'api_key'} }") # Не логируем API ключ
    return final_config

def update_config_file_from_cli(cli_args: Dict[str, Any], config_file_path: Optional[str] = None):
    """Обновляет файл конфигурации значениями из CLI (только безопасные поля)."""
    effective_path = config_file_path or get_config_file_path()
    current_config = load_config(effective_path) # Загружаем текущий конфиг, чтобы не перезаписать все

    fields_to_update = [
        "client_region", "client_time_zone", "proxy", "timeout",
        "font_path", "font_size", "logging_level"
    ]
    updated = False
    for field in fields_to_update:
        cli_value = cli_args.get(field)
        if cli_value is not None and current_config.get(field) != cli_value:
            current_config[field] = cli_value
            updated = True
            logger.debug(f"Config field '{field}' will be updated to '{cli_value}'.")

    if updated:
        save_config(current_config, effective_path)
        logger.info(f"Configuration file '{effective_path}' updated with CLI arguments.")
    else:
        logger.info("No configuration changes to save from CLI arguments.")