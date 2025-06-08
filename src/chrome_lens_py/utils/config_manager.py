import json
import logging
import os
from typing import Any, Dict, Optional

from ..constants import APP_NAME_FOR_CONFIG, DEFAULT_CONFIG_FILENAME
from ..exceptions import LensConfigError

logger = logging.getLogger(__name__)


def get_default_config_dir(app_name: str = APP_NAME_FOR_CONFIG) -> str:
    """Returns the default configuration directory path for the application."""
    home_dir = os.path.expanduser("~")
    # This structure is a common convention
    config_dir_base = os.getenv("XDG_CONFIG_HOME", os.path.join(home_dir, ".config"))
    return os.path.join(config_dir_base, app_name)


def load_config(config_file_path: str) -> Dict[str, Any]:
    """
    Loads configuration from a JSON file.
    Returns an empty dictionary if the file is not found.
    Raises LensConfigError on parsing or I/O errors.
    """
    if os.path.isfile(config_file_path):
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise LensConfigError(
                f"Error decoding JSON from config file '{config_file_path}': {e}"
            )
        except IOError as e:
            raise LensConfigError(
                f"I/O error reading config file '{config_file_path}': {e}"
            )
    return {}


def get_effective_config_value(
    cli_arg_value: Optional[Any], config_file_value: Optional[Any], default_value: Any
) -> Any:
    """Determines the effective configuration value. Priority: CLI > Config File > Default."""
    if cli_arg_value is not None:
        return cli_arg_value
    if config_file_value is not None:
        return config_file_value
    return default_value


def build_app_config(
    cli_args: Optional[Dict[str, Any]] = None, config_file_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Builds the final application config by merging values from CLI args and a config file.
    """
    cli = cli_args or {}
    loaded_config = load_config(config_file_path) if config_file_path else {}

    if loaded_config:
        logging.info("Applying settings from config file:")
        for key, value in loaded_config.items():
            if key.lower() not in ["api_key", "proxy"]:
                logging.info(f"  - {key}: {value}")

    # Priority: CLI > Config File > Default (handled by get_effective_config_value)
    # Defaults are defined in constants.py or as literals here.
    from ..constants import (
        DEFAULT_API_KEY,
        DEFAULT_CLIENT_REGION,
        DEFAULT_CLIENT_TIME_ZONE,
    )

    final_config = {
        "api_key": get_effective_config_value(
            cli.get("api_key"), loaded_config.get("api_key"), DEFAULT_API_KEY
        ),
        "client_region": get_effective_config_value(
            cli.get("client_region"),
            loaded_config.get("client_region"),
            DEFAULT_CLIENT_REGION,
        ),
        "client_time_zone": get_effective_config_value(
            cli.get("client_time_zone"),
            loaded_config.get("client_time_zone"),
            DEFAULT_CLIENT_TIME_ZONE,
        ),
        "proxy": get_effective_config_value(
            cli.get("proxy"), loaded_config.get("proxy"), None
        ),
        "timeout": int(
            get_effective_config_value(
                cli.get("timeout"), loaded_config.get("timeout"), 60
            )
        ),
        "font_path": get_effective_config_value(
            cli.get("font_path"), loaded_config.get("font_path"), None
        ),
        "font_size": (
            int(
                get_effective_config_value(
                    cli.get("font_size"), loaded_config.get("font_size"), 20
                )
            )
            if get_effective_config_value(
                cli.get("font_size"), loaded_config.get("font_size"), None
            )
            is not None
            else None
        ),
        "logging_level": get_effective_config_value(
            cli.get("logging_level"), loaded_config.get("logging_level"), "WARNING"
        ).upper(),
        "ocr_preserve_line_breaks": get_effective_config_value(
            cli.get("ocr_preserve_line_breaks"),
            loaded_config.get("ocr_preserve_line_breaks"),
            True,
        ),
    }
    return final_config


def update_config_file_from_cli(cli_args: Dict[str, Any], config_file_path: str):
    """Updates the config file with values from CLI args (only safe fields)."""
    current_config = load_config(config_file_path)

    fields_to_update = [
        "client_region",
        "client_time_zone",
        "proxy",
        "timeout",
        "font_path",
        "font_size",
        "logging_level",
        "ocr_preserve_line_breaks",
    ]
    updated = False
    for field in fields_to_update:
        cli_value = cli_args.get(field)
        if cli_value is not None and current_config.get(field) != cli_value:
            current_config[field] = cli_value
            updated = True

    if not updated:
        logging.info("No configuration changes to save from CLI arguments.")
        return

    config_dir = os.path.dirname(config_file_path)
    try:
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        with open(config_file_path, "w", encoding="utf-8") as f:
            json.dump(current_config, f, indent=4, ensure_ascii=False)
        logging.info(f"Configuration file updated: {config_file_path}")
    except (IOError, TypeError) as e:
        raise LensConfigError(f"Error saving config file '{config_file_path}': {e}")
