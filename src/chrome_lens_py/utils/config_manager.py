"""Settings for the CLI: one typed dataclass, one place for the defaults.

Where a value comes from, highest priority first:

1. a flag given explicitly on the command line,
2. the JSON config file,
3. a ``LENS_*`` environment variable (``LENS_API_KEY``, ``LENS_PROXY``, ...),
4. the default declared on :class:`Settings`.

"Given explicitly" is the important part: the argparse parser in
``cli/main.py`` declares every settings flag with ``default=SUPPRESS``, so a flag
the user did not type is simply absent from the namespace instead of arriving
as a default that would override the config file.
"""

import json
import logging
import os
import shutil
import tempfile
import typing
from dataclasses import MISSING, dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..constants import (
    APP_NAME_FOR_CONFIG,
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_MAX_RETRIES,
)
from ..exceptions import LensConfigError

logger = logging.getLogger(__name__)

ENV_PREFIX = "LENS_"
MAX_CONCURRENCY = 30
LOGGING_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Fields whose value must not be echoed into logs.
SECRET_FIELDS = frozenset({"api_key", "proxy"})
# Never written back by --update-config: a key typed once on a command line
# should not end up lying around in a file nobody remembers editing.
NEVER_PERSISTED = frozenset({"api_key"})


@dataclass
class Settings:
    """Every persistent option of the CLI, with its default."""

    api_key: str = DEFAULT_API_KEY
    proxy: Optional[str] = None
    client_region: str = DEFAULT_CLIENT_REGION
    client_time_zone: str = DEFAULT_CLIENT_TIME_ZONE
    timeout: int = 60
    retries: int = DEFAULT_MAX_RETRIES
    concurrency: int = 5
    # False = ignore HTTP_PROXY/HTTPS_PROXY/ALL_PROXY (the --no-env-proxy flag).
    trust_env: bool = True
    font_path: Optional[str] = None
    font_size: Optional[int] = None
    logging_level: str = "WARNING"
    ocr_preserve_line_breaks: bool = True
    target_lang: Optional[str] = None
    overlay_mode: str = "chromium"
    vertical_text: str = "auto"
    erase_mode: str = "patch"
    hull_padding: float = 0.45
    outline_scale: float = 1.0
    min_readable_px: float = 0.0
    text_align: str = "auto"
    manga_mode: bool = False
    manga_box_growth: float = 1.45
    # Warm-process fast mode (see chrome_lens_py/client.py). "auto" uses a
    # background daemon when one is running and starts one for next time;
    # "on" waits for it; "off" never touches it.
    daemon: str = "auto"
    # Seconds without a request before an auto-started daemon exits (0 = never).
    daemon_idle_timeout: int = 600
    # Fixed TCP port for the persistent daemon (ShareX uploader mode, --serve).
    daemon_port: int = 8765

    # Bookkeeping, not options.
    sources: Dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    notes: List[str] = field(default_factory=list, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in SETTING_NAMES}


SETTING_NAMES: Tuple[str, ...] = tuple(
    f.name for f in fields(Settings) if f.name not in ("sources", "notes")
)

CHOICES: Dict[str, Tuple[str, ...]] = {
    "overlay_mode": ("chromium", "legacy"),
    "vertical_text": ("keep", "auto", "horizontal"),
    "erase_mode": ("patch", "hull"),
    "text_align": ("auto", "left", "center", "right"),
    "daemon": ("auto", "on", "off"),
}

# Names accepted in config.json besides the canonical field names: the CLI flag
# spellings people naturally copy over.
CONFIG_ALIASES: Dict[str, str] = {
    "translate": "target_lang",
    "font": "font_path",
    "outline": "outline_scale",
    "min_text_size": "min_readable_px",
    "manga": "manga_mode",
    "manga_growth": "manga_box_growth",
}
# ...and the one whose meaning is inverted.
INVERTED_ALIASES: Dict[str, str] = {"no_env_proxy": "trust_env"}


def default_value(name: str) -> Any:
    """The declared default of one setting (what ``--help`` should print)."""
    for f in fields(Settings):
        if f.name == name:
            return f.default if f.default is not MISSING else None
    raise KeyError(name)


def _kind(name: str) -> type:
    """bool / int / float / str for a setting, unwrapping Optional."""
    hint = typing.get_type_hints(Settings)[name]
    if typing.get_origin(hint) is typing.Union:
        hint = next(a for a in typing.get_args(hint) if a is not type(None))
    return hint


def _coerce(name: str, value: Any, origin: str) -> Any:
    """Turn a raw value (JSON, environment string) into the setting's type."""
    kind = _kind(name)
    problem = f"{origin}: '{name}' "

    if kind is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("1", "true", "yes", "on"):
                return True
            if lowered in ("0", "false", "no", "off"):
                return False
        raise LensConfigError(f"{problem}must be true or false, got {value!r}.")

    if kind is int:
        if isinstance(value, bool):
            raise LensConfigError(f"{problem}must be a whole number, got {value!r}.")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        raise LensConfigError(f"{problem}must be a whole number, got {value!r}.")

    if kind is float:
        if isinstance(value, bool):
            raise LensConfigError(f"{problem}must be a number, got {value!r}.")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise LensConfigError(f"{problem}must be a number, got {value!r}.")

    # str
    if name == "daemon" and isinstance(value, bool):
        return "on" if value else "off"
    if not isinstance(value, str):
        raise LensConfigError(f"{problem}must be a string, got {value!r}.")
    if name == "logging_level":
        value = value.strip().upper()
    elif name in CHOICES:
        value = value.strip().lower()
    return value


def _validate(settings: Settings) -> None:
    def bad(name: str, why: str) -> LensConfigError:
        origin = settings.sources.get(name, "default")
        return LensConfigError(f"Invalid {name} ({origin}): {why}.")

    if settings.timeout <= 0:
        raise bad("timeout", "must be greater than 0")
    if settings.retries < 0:
        raise bad("retries", "must not be negative")
    if settings.concurrency < 1:
        raise bad("concurrency", "must be at least 1")
    if settings.concurrency > MAX_CONCURRENCY:
        raise bad(
            "concurrency",
            f"cannot be greater than {MAX_CONCURRENCY}. "
            "This is a security measure to prevent IP blocking",
        )
    if settings.font_size is not None and settings.font_size <= 0:
        raise bad("font_size", "must be greater than 0")
    if settings.logging_level not in LOGGING_LEVELS:
        raise bad("logging_level", f"must be one of {', '.join(LOGGING_LEVELS)}")
    for name, allowed in CHOICES.items():
        if getattr(settings, name) not in allowed:
            raise bad(name, f"must be one of {', '.join(allowed)}")
    for name in ("hull_padding", "outline_scale", "min_readable_px"):
        if getattr(settings, name) < 0:
            raise bad(name, "must not be negative")
    if settings.manga_box_growth <= 0:
        raise bad("manga_box_growth", "must be greater than 0")
    if settings.daemon_idle_timeout < 0:
        raise bad("daemon_idle_timeout", "must not be negative (0 = never)")
    if not 0 <= settings.daemon_port <= 65535:
        raise bad("daemon_port", "must be between 0 and 65535")


# --------------------------------------------------------------------- files


def get_default_config_dir(
    app_name: str = APP_NAME_FOR_CONFIG, environ: Optional[Mapping[str, str]] = None
) -> str:
    """Returns the default configuration directory path for the application.

    `environ` lets the daemon answer for a client whose XDG_CONFIG_HOME it does
    not share.
    """
    home_dir = os.path.expanduser("~")
    environ = os.environ if environ is None else environ
    # This structure is a common convention
    config_dir_base = environ.get("XDG_CONFIG_HOME") or os.path.join(
        home_dir, ".config"
    )
    return os.path.join(config_dir_base, app_name)


def load_config(config_file_path: str) -> Dict[str, Any]:
    """Load a JSON config file.

    Returns an empty dict when the file does not exist. Raises LensConfigError
    for anything that is there but unusable: unreadable, not JSON, or JSON that
    is not an object.
    """
    if not os.path.isfile(config_file_path):
        return {}
    try:
        # utf-8-sig: Notepad likes to prepend a BOM, which json.load rejects.
        with open(config_file_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise LensConfigError(
            f"Error decoding JSON from config file '{config_file_path}': {e}"
        ) from e
    except (OSError, UnicodeDecodeError) as e:
        raise LensConfigError(
            f"I/O error reading config file '{config_file_path}': {e}"
        ) from e
    if not isinstance(data, dict):
        raise LensConfigError(
            f"Config file '{config_file_path}' must contain a JSON object "
            f'(like {{"timeout": 90}}), not {type(data).__name__}.'
        )
    return data


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """Write a file so that a crash leaves either the old or the new content.

    The text goes to a temp file in the same directory first (same filesystem,
    so os.replace is atomic), then replaces the target in one step.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_config(config_file_path: str, data: Mapping[str, Any]) -> None:
    """Atomically save the config, keeping the previous version as ``.bak``."""
    try:
        text = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
        if os.path.isfile(config_file_path):
            shutil.copy2(config_file_path, config_file_path + ".bak")
        atomic_write_text(config_file_path, text)
    except (OSError, TypeError, ValueError) as e:
        raise LensConfigError(f"Error saving config file '{config_file_path}': {e}")


# ------------------------------------------------------------------ resolving


def _normalise_config(
    raw: Mapping[str, Any], origin: str
) -> Tuple[Dict[str, Any], List[str]]:
    """(canonical name -> coerced value with aliases folded in, unknown keys)."""
    found: Dict[str, Any] = {}
    unknown: List[str] = []
    for key, value in raw.items():
        name = str(key).strip().lower().replace("-", "_")
        if value is None:
            continue  # null means "not set", as it always has
        if name in INVERTED_ALIASES:
            target = INVERTED_ALIASES[name]
            found.setdefault(target, not _coerce_alias_bool(name, value, origin))
            continue
        name = CONFIG_ALIASES.get(name, name)
        if name not in SETTING_NAMES:
            unknown.append(str(key))
            continue
        is_alias = str(key).strip().lower().replace("-", "_") != name
        if is_alias and name in found:
            continue  # the canonical spelling wins
        found[name] = value
    coerced = {name: _coerce(name, value, origin) for name, value in found.items()}
    return coerced, unknown


def _coerce_alias_bool(name: str, value: Any, origin: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise LensConfigError(f"{origin}: '{name}' must be true or false, got {value!r}.")


def resolve_settings(
    cli_args: Optional[Mapping[str, Any]] = None,
    config_file_path: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Settings:
    """Merge defaults, environment, config file and explicit CLI values."""
    env = os.environ if env is None else env
    settings = Settings()
    for name in SETTING_NAMES:
        settings.sources[name] = "default"

    def apply(name: str, value: Any, source: str) -> None:
        setattr(settings, name, value)
        settings.sources[name] = source

    # 3. environment
    for name in SETTING_NAMES:
        var = ENV_PREFIX + name.upper()
        raw = env.get(var)
        if raw is None or raw.strip() == "":
            continue
        apply(name, _coerce(name, raw, f"environment variable {var}"), f"env {var}")

    # 2. config file
    if config_file_path:
        file_values, unknown_keys = _normalise_config(
            load_config(config_file_path), f"config file '{config_file_path}'"
        )
        for key in unknown_keys:
            settings.notes.append(
                f"Ignoring unknown key '{key}' in config file '{config_file_path}'."
            )
        for name, value in file_values.items():
            apply(name, value, f"config file {config_file_path}")

    # 1. explicit CLI values (None = not given)
    for name in SETTING_NAMES:
        value = (cli_args or {}).get(name)
        if value is not None:
            apply(name, _coerce(name, value, "command line"), "command line")

    _validate(settings)
    return settings


# ---------------------------------------------------------------- compat API


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
    """Settings as a plain dict (kept for callers of the pre-Settings API)."""
    return resolve_settings(cli_args, config_file_path).to_dict()


def update_config_file_from_cli(cli_args: Mapping[str, Any], config_file_path: str):
    """Save the settings given explicitly on the command line into the config file.

    Everything except the API key is persisted. Unknown keys already in the
    file are left alone. The previous file is kept as ``<file>.bak``.
    """
    current_config = load_config(config_file_path)

    updated = False
    for name in SETTING_NAMES:
        if name in NEVER_PERSISTED:
            continue
        cli_value = cli_args.get(name)
        if cli_value is None:
            continue
        cli_value = _coerce(name, cli_value, "command line")
        if current_config.get(name) != cli_value:
            current_config[name] = cli_value
            updated = True

    if not updated:
        logger.info("No configuration changes to save from CLI arguments.")
        return

    write_config(config_file_path, current_config)
    logger.info("Configuration file updated: %s", config_file_path)
