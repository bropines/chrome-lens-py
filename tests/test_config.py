"""Offline tests for the unified settings (utils/config_manager.py)."""

import json
import os

import pytest

from chrome_lens_py.cli.main import build_parser
from chrome_lens_py.constants import DEFAULT_API_KEY
from chrome_lens_py.exceptions import LensConfigError
from chrome_lens_py.utils.config_manager import (
    Settings,
    atomic_write_text,
    build_app_config,
    load_config,
    resolve_settings,
    update_config_file_from_cli,
)


def write(path, data):
    path.write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )
    return str(path)


# ------------------------------------------------------------------ defaults


def test_defaults_come_from_the_dataclass(tmp_path):
    settings = resolve_settings({}, str(tmp_path / "missing.json"), env={})
    assert settings.to_dict() == Settings().to_dict()
    assert settings.api_key == DEFAULT_API_KEY
    assert settings.timeout == 60 and settings.concurrency == 5
    assert settings.trust_env is True


def test_argparse_leaves_unset_settings_out_of_the_namespace():
    args = vars(build_parser().parse_args(["img.png"]))
    for name in (
        "timeout",
        "concurrency",
        "overlay_mode",
        "vertical_text",
        "erase_mode",
        "hull_padding",
        "outline_scale",
        "min_readable_px",
        "text_align",
        "manga_mode",
        "manga_box_growth",
        "trust_env",
        "target_lang",
        "retries",
        "ocr_preserve_line_breaks",
    ):
        assert name not in args, name


def test_argparse_records_explicit_values():
    args = vars(
        build_parser().parse_args(
            ["img.png", "--manga", "--no-env-proxy", "--ocr-single-line", "-t", "ru"]
        )
    )
    assert args["manga_mode"] is True
    assert args["trust_env"] is False
    assert args["ocr_preserve_line_breaks"] is False
    assert args["target_lang"] == "ru"


# ---------------------------------------------------------------- precedence


def test_precedence_cli_over_file_over_env_over_default(tmp_path):
    config = write(tmp_path / "c.json", {"timeout": 30, "retries": 4, "proxy": "p:1"})
    env = {"LENS_TIMEOUT": "10", "LENS_RETRIES": "9", "LENS_CONCURRENCY": "7"}
    settings = resolve_settings({"timeout": 99}, config, env=env)

    assert settings.timeout == 99  # CLI beats file and env
    assert settings.retries == 4  # file beats env
    assert settings.concurrency == 7  # env beats default
    assert settings.proxy == "p:1"  # file only
    assert settings.overlay_mode == "chromium"  # default
    assert settings.sources["timeout"] == "command line"
    assert settings.sources["concurrency"].startswith("env")


def test_env_api_key_and_proxy(tmp_path):
    settings = resolve_settings(
        {},
        None,
        env={"LENS_API_KEY": "k", "LENS_PROXY": "socks5://x:1", "LENS_TRUST_ENV": "no"},
    )
    assert settings.api_key == "k"
    assert settings.proxy == "socks5://x:1"
    assert settings.trust_env is False


def test_empty_env_value_is_ignored():
    assert resolve_settings({}, None, env={"LENS_TIMEOUT": " "}).timeout == 60


def test_new_keys_can_be_set_in_the_config_file(tmp_path):
    config = write(
        tmp_path / "c.json",
        {
            "overlay_mode": "legacy",
            "vertical_text": "horizontal",
            "erase_mode": "hull",
            "hull_padding": 0.7,
            "outline_scale": 2,
            "min_readable_px": 12,
            "text_align": "center",
            "manga_mode": True,
            "manga_box_growth": 1.6,
            "concurrency": 3,
            "target_lang": "ru",
            "retries": 0,
            "trust_env": False,
        },
    )
    s = resolve_settings({}, config, env={})
    assert (s.overlay_mode, s.vertical_text, s.erase_mode) == (
        "legacy",
        "horizontal",
        "hull",
    )
    assert (s.hull_padding, s.outline_scale, s.min_readable_px) == (0.7, 2.0, 12.0)
    assert (s.text_align, s.manga_mode, s.manga_box_growth) == ("center", True, 1.6)
    assert (s.concurrency, s.target_lang, s.retries, s.trust_env) == (3, "ru", 0, False)


def test_cli_flag_spellings_work_as_config_keys(tmp_path):
    config = write(
        tmp_path / "c.json",
        {"translate": "de", "outline": 3, "manga": True, "no_env_proxy": True},
    )
    s = resolve_settings({}, config, env={})
    assert (s.target_lang, s.outline_scale, s.manga_mode, s.trust_env) == (
        "de",
        3.0,
        True,
        False,
    )


def test_old_config_files_still_load(tmp_path):
    config = write(
        tmp_path / "c.json",
        {
            "api_key": "k",
            "proxy": "socks5://127.0.0.1:9050",
            "client_region": "DE",
            "client_time_zone": "Europe/Berlin",
            "timeout": "90",  # the old code int()'d strings
            "font_path": "/f.ttf",
            "font_size": 24,
            "logging_level": "debug",
            "ocr_preserve_line_breaks": False,
            "something_unknown": 1,
        },
    )
    s = resolve_settings({}, config, env={})
    assert s.timeout == 90 and s.logging_level == "DEBUG" and s.font_size == 24
    assert s.client_region == "DE" and s.ocr_preserve_line_breaks is False
    assert any("something_unknown" in n for n in s.notes)
    assert build_app_config({}, config)["client_time_zone"] == "Europe/Berlin"


def test_null_in_config_means_unset(tmp_path):
    config = write(tmp_path / "c.json", {"timeout": None})
    assert resolve_settings({}, config, env={}).timeout == 60


# ---------------------------------------------------------------- robustness


@pytest.mark.parametrize("content", ["[1, 2]", '"text"', "42", "null"])
def test_config_that_is_not_an_object_is_rejected(tmp_path, content):
    path = write(tmp_path / "c.json", content)
    with pytest.raises(LensConfigError, match="JSON object"):
        load_config(path)


def test_invalid_json_is_a_config_error(tmp_path):
    with pytest.raises(LensConfigError, match="decoding JSON"):
        load_config(write(tmp_path / "c.json", "{nope"))


@pytest.mark.parametrize(
    "data,fragment",
    [
        ({"timeout": "abc"}, "timeout"),
        ({"timeout": True}, "timeout"),
        ({"manga_mode": "maybe"}, "manga_mode"),
        ({"proxy": 5}, "proxy"),
        ({"hull_padding": [1]}, "hull_padding"),
        ({"overlay_mode": "sideways"}, "overlay_mode"),
        ({"concurrency": 99}, "concurrency"),
        ({"timeout": 0}, "timeout"),
        ({"logging_level": "LOUD"}, "logging_level"),
    ],
)
def test_bad_values_give_a_clear_error(tmp_path, data, fragment):
    with pytest.raises(LensConfigError, match=fragment):
        resolve_settings({}, write(tmp_path / "c.json", data), env={})


def test_bad_env_value_names_the_variable():
    with pytest.raises(LensConfigError, match="LENS_TIMEOUT"):
        resolve_settings({}, None, env={"LENS_TIMEOUT": "soon"})


# ------------------------------------------------------------------- writing


def test_atomic_write_replaces_without_leftovers(tmp_path):
    target = tmp_path / "sub" / "f.txt"
    atomic_write_text(str(target), "one")
    atomic_write_text(str(target), "two")
    assert target.read_text() == "two"
    assert os.listdir(target.parent) == ["f.txt"]


def test_update_config_keeps_a_backup_and_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    write(path, {"timeout": 30, "custom": "keep me"})

    update_config_file_from_cli(
        {"timeout": 45, "overlay_mode": "legacy", "api_key": "secret"}, str(path)
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"timeout": 45, "custom": "keep me", "overlay_mode": "legacy"}
    assert json.loads((tmp_path / "config.json.bak").read_text()) == {
        "timeout": 30,
        "custom": "keep me",
    }


def test_update_config_refuses_to_overwrite_a_corrupt_file(tmp_path):
    path = tmp_path / "config.json"
    write(path, "{broken")
    with pytest.raises(LensConfigError):
        update_config_file_from_cli({"timeout": 5}, str(path))
    assert path.read_text() == "{broken"


def test_update_config_without_changes_writes_nothing(tmp_path):
    path = tmp_path / "config.json"
    update_config_file_from_cli({"timeout": None}, str(path))
    assert not path.exists()
