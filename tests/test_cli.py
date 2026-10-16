"""Offline tests for the lens_scan command line, with LensAPI replaced by a fake."""

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from chrome_lens_py.cli import main as cli
from chrome_lens_py.exceptions import LensAPIError
from chrome_lens_py.utils import sharex_setup


def geo(cx, cy, w, h):
    return {
        "center_x": cx,
        "center_y": cy,
        "width": w,
        "height": h,
        "angle_deg": 0.0,
        "coordinate_type": "NORMALIZED",
    }


class FakeAPI:
    """Stands in for LensAPI. `handler(path, kwargs)` returns text or raises."""

    handler = staticmethod(lambda path, kw: "hello")
    instances = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.calls = []
        self.closed = False
        FakeAPI.instances.append(self)

    async def process_image(self, **kwargs):
        self.calls.append(kwargs)
        text = FakeAPI.handler(kwargs["image_path"], kwargs)
        fmt = kwargs["output_format"]
        word = text.split("\n")[0]
        result = {
            "translated_text": (
                "перевод" if kwargs["target_translation_language"] else None
            ),
            "word_data": [
                {"word": word, "separator": "", "geometry": geo(0.5, 0.5, 0.2, 0.1)}
            ],
            "detected_language": "en",
        }
        if fmt == "detailed":
            result["detailed_blocks"] = [
                {
                    "text": text,
                    "geometry": geo(0.5, 0.5, 0.8, 0.5),
                    "lines": [
                        {
                            "text": text,
                            "geometry": geo(0.5, 0.5, 0.8, 0.2),
                            "words": [
                                {
                                    "text": text,
                                    "separator": "",
                                    "geometry": geo(0.5, 0.5, 0.4, 0.2),
                                }
                            ],
                        }
                    ],
                }
            ]
        elif fmt == "blocks":
            result["text_blocks"] = [{"text": text}]
        elif fmt == "lines":
            result["line_blocks"] = [{"text": text}]
        else:
            result["ocr_text"] = text
        return result

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No real config, no LENS_* variables, a fake API, no clipboard."""
    import os

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in list(os.environ):
        if name.startswith("LENS_"):
            monkeypatch.delenv(name)
    FakeAPI.instances = []
    FakeAPI.handler = staticmethod(lambda path, kw: "hello")
    monkeypatch.setattr(cli, "LensAPI", FakeAPI)
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda text: True)


@pytest.fixture
def images(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        path = tmp_path / name
        Image.new("RGB", (200, 100), "white").save(path)
        paths.append(str(path))
    return paths


def run(argv):
    return cli.main([str(a) for a in argv])


# --------------------------------------------------------------- exit codes


def test_success_exits_zero(images, capsys):
    assert run([images[0]]) == 0
    assert "hello" in capsys.readouterr().out


def test_single_failure_exits_one_with_error_on_stderr(images, capsys):
    FakeAPI.handler = staticmethod(
        lambda p, kw: (_ for _ in ()).throw(LensAPIError("boom"))
    )
    assert run([images[0]]) == 1
    out, err = capsys.readouterr()
    assert "boom" in err and "boom" not in out
    assert out == ""


def test_all_failed_exits_one_partial_exits_two(images, capsys):
    def handler(path, kw):
        if path.endswith("b.png"):
            raise LensAPIError("bad b")
        return "ok " + path[-5:]

    FakeAPI.handler = staticmethod(handler)
    directory = str(Path(images[0]).parent)
    assert run([directory]) == 2
    out, err = capsys.readouterr()
    assert "ok a.png" in out and "ok c.png" in out
    assert "bad b" in err and "bad b" not in out

    FakeAPI.handler = staticmethod(
        lambda p, kw: (_ for _ in ()).throw(LensAPIError("all bad"))
    )
    assert run([directory]) == 1


def test_unsupported_source_exits_one(tmp_path, capsys):
    assert run([tmp_path / "missing.png"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "not a valid" in err


def test_missing_image_source_exits_one_and_help_goes_to_stderr(capsys):
    assert run([]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "--translate" in err


def test_clipboard_failure_is_a_failure(images, monkeypatch, capsys):
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda text: False)
    assert run([images[0], "--sharex"]) == 1
    assert "pyperclip" in capsys.readouterr().err


def test_bad_config_exits_one_with_message(images, tmp_path, capsys):
    config = tmp_path / "bad.json"
    config.write_text("[1,2,3]")
    assert run([images[0], "--config-file", config]) == 1
    assert "JSON object" in capsys.readouterr().err


# ------------------------------------------------------- output integrity


def test_get_coords_json_keeps_brackets(images, capsys):
    FakeAPI.handler = staticmethod(lambda p, kw: "a[b]c")
    assert run([images[0], "--get-coords"]) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert list(parsed[0]) == ["a[b]c"]


def test_get_coords_json_is_not_wrapped_at_terminal_width(images, capsys):
    long_word = "x" * 300
    FakeAPI.handler = staticmethod(lambda p, kw: long_word)
    assert run([images[0], "--get-coords"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)[0][long_word]["center_x"] == 0.5
    assert f'"{long_word}"' in out  # on one line


def test_ocr_text_with_markup_and_long_lines_survives(images, capsys):
    text = "[bold]not markup[/bold] " + "word " * 80 + "[/nonsense]"
    FakeAPI.handler = staticmethod(lambda p, kw: text)
    assert run([images[0]]) == 0
    assert text in capsys.readouterr().out


def test_translated_text_survives_intact(images, capsys):
    assert run([images[0], "-t", "ru"]) == 0
    out = capsys.readouterr().out
    assert "перевод" in out


def test_decorations_stay_off_stdout(images, capsys):
    assert run([images[0]]) == 0
    out, err = capsys.readouterr()
    assert out == "hello\n"
    assert "OCR Results" in err


def test_quiet_prints_only_the_result(images, capsys):
    assert run([images[0], "-q"]) == 0
    out, err = capsys.readouterr()
    assert out == "hello\n" and err == ""


def test_error_text_with_brackets_is_not_eaten(images, capsys):
    FakeAPI.handler = staticmethod(
        lambda p, kw: (_ for _ in ()).throw(LensAPIError("bad [thing] here"))
    )
    run([images[0]])
    assert "bad [thing] here" in capsys.readouterr().err


# ------------------------------------------------------------------ formats


def test_oneline_prints_one_json_object_per_image(images, capsys):
    FakeAPI.handler = staticmethod(lambda p, kw: "line1\nline2")
    assert run([images[0], "--oneline"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "file": images[0],
        "ocr_text": "line1\nline2",
        "translated_text": None,
        "error": None,
    }


def test_oneline_reports_errors_in_the_record_and_exit_code(images, tmp_path, capsys):
    def handler(path, kw):
        if path.endswith("b.png"):
            raise LensAPIError("nope")
        return "fine"

    FakeAPI.handler = staticmethod(handler)
    assert run([tmp_path, "--oneline"]) == 2
    out, err = capsys.readouterr()
    records = [json.loads(line) for line in out.splitlines()]
    assert [r["error"] is None for r in records] == [True, False, True]
    assert "nope" in records[1]["error"] and "nope" in err


def test_format_json_for_one_image(images, capsys):
    assert run([images[0], "--format", "json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["width"] == 200 and parsed["blocks"][0]["lines"][0]["words"]
    assert FakeAPI.instances[0].calls[0]["output_format"] == "detailed"


def test_format_jsonl_one_line_per_image(images, tmp_path, capsys):
    assert run([tmp_path, "--format", "jsonl"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and all(
        json.loads(line)["ocr_text"] == "hello" for line in lines
    )


def test_format_hocr_is_xhtml(images, capsys):
    assert run([images[0], "--format", "hocr"]) == 0
    root = ET.fromstring(capsys.readouterr().out)
    assert root.tag.endswith("html")
    page = next(el for el in root.iter() if el.get("class") == "ocr_page")
    assert "bbox 0 0 200 100" in page.get("title")


def test_format_tsv(images, capsys):
    assert run([images[0], "--format", "tsv"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert rows[0][0] == "level" and rows[-1][-1] == "hello"


def test_format_cannot_be_combined_with_other_modes(images, capsys):
    assert run([images[0], "--format", "json", "--get-coords"]) == 1
    assert "cannot be used together" in capsys.readouterr().err
    assert run([images[0], "--oneline", "-b"]) == 1


def test_sharex_copies_ocr_text_from_a_detailed_format(images, monkeypatch, capsys):
    copied = []
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda t: copied.append(t) or True)
    assert run([images[0], "--format", "json", "--sharex"]) == 0
    assert copied == ["hello"]


# ---------------------------------------------------------------- settings


def test_config_file_values_reach_the_api_and_cli_overrides_them(images, tmp_path):
    config = tmp_path / "c.json"
    config.write_text(
        json.dumps(
            {
                "overlay_mode": "legacy",
                "concurrency": 2,
                "timeout": 11,
                "manga_mode": True,
            }
        )
    )
    assert run([images[0], "--config-file", config]) == 0
    api = FakeAPI.instances[-1]
    assert api.calls[0]["overlay_mode"] == "legacy"
    assert api.calls[0]["manga_mode"] is True
    assert api.init_kwargs["timeout"] == 11
    assert api.init_kwargs["max_concurrent"] == 2

    assert run([images[0], "--config-file", config, "--overlay-mode", "chromium"]) == 0
    assert FakeAPI.instances[-1].calls[0]["overlay_mode"] == "chromium"


def test_env_variables_apply_and_config_beats_them(images, tmp_path, monkeypatch):
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"timeout": 22}))
    monkeypatch.setenv("LENS_TIMEOUT", "5")
    monkeypatch.setenv("LENS_API_KEY", "envkey")
    monkeypatch.setenv("LENS_PROXY", "http://envproxy:1")
    assert run([images[0], "--config-file", config]) == 0
    kwargs = FakeAPI.instances[-1].init_kwargs
    assert kwargs["timeout"] == 22
    assert kwargs["api_key"] == "envkey" and kwargs["proxy"] == "http://envproxy:1"


def test_target_language_from_config_translates(images, tmp_path):
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"target_lang": "de"}))
    assert run([images[0], "--config-file", config]) == 0
    assert FakeAPI.instances[-1].calls[0]["target_translation_language"] == "de"


def test_no_env_proxy_flag_disables_trust_env(images):
    assert run([images[0]]) == 0
    assert FakeAPI.instances[-1].init_kwargs["trust_env"] is True
    assert run([images[0], "--no-env-proxy"]) == 0
    assert FakeAPI.instances[-1].init_kwargs["trust_env"] is False


def test_retries_is_held_back_until_lensapi_accepts_it(images, monkeypatch):
    assert run([images[0], "--retries", "5"]) == 0
    assert "max_retries" not in FakeAPI.instances[-1].init_kwargs

    class RetryAPI(FakeAPI):
        def __init__(self, api_key=None, max_retries=None, **kwargs):
            super().__init__(api_key=api_key, max_retries=max_retries, **kwargs)

    monkeypatch.setattr(cli, "LensAPI", RetryAPI)
    assert run([images[0], "--retries", "5"]) == 0
    assert FakeAPI.instances[-1].init_kwargs["max_retries"] == 5


def test_concurrency_over_the_hard_limit_is_refused(images, capsys):
    assert run([images[0], "--concurrency", "31"]) == 1
    assert "concurrency" in capsys.readouterr().err


def test_update_config_without_an_image_saves_and_exits(tmp_path, capsys):
    assert run(["--update-config", "--timeout", "77", "--overlay-mode", "legacy"]) == 0
    saved = json.loads(
        (tmp_path / "xdg" / "chrome-lens-py" / "config.json").read_text()
    )
    assert saved == {"timeout": 77, "overlay_mode": "legacy"}


def test_serve_uses_the_merged_settings(tmp_path, monkeypatch):
    config = tmp_path / "c.json"
    config.write_text(
        json.dumps({"timeout": 33, "client_region": "DE", "proxy": "p:1"})
    )
    captured = {}

    async def fake_run_server(**kwargs):
        captured.update(kwargs)

    from chrome_lens_py import server

    monkeypatch.setattr(server, "run_server", fake_run_server)
    code = run(
        [
            "--serve",
            "--config-file",
            config,
            "--concurrency",
            "4",
            "--client-time-zone",
            "Europe/Berlin",
        ]
    )
    assert code == 0
    assert captured["timeout"] == 33
    assert captured["client_region"] == "DE"
    assert captured["client_time_zone"] == "Europe/Berlin"
    assert captured["max_concurrent"] == 4
    assert captured["proxy"] == "p:1"


def test_serve_refuses_a_public_bind_without_a_token(capsys):
    assert run(["--serve", "--host", "0.0.0.0"]) == 1
    assert "--token" in capsys.readouterr().err


# ---------------------------------------------------------------------- help


def all_option_strings():
    parser = cli.build_parser()
    return [opt for action in parser._actions for opt in action.option_strings]


def test_every_parser_option_appears_in_help(capsys):
    assert run(["--help"]) == 0
    out = capsys.readouterr().out
    options = all_option_strings()
    assert "--hull-padding" in options and "--setup-sharex" in options
    missing = [opt for opt in options if opt not in out]
    assert missing == []


def test_help_names_the_positionals(capsys):
    run(["-h"])
    out = capsys.readouterr().out
    assert "image_source" in out and "ocr_lang" in out


# ------------------------------------------------------------------ logging


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    yield root
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])


def test_setup_logging_wins_even_after_an_implicit_basicconfig(clean_root_logger):
    root = clean_root_logger
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)

    logging.warning("module-level call that installs a default handler")
    assert root.handlers  # the implicit basicConfig happened

    cli.setup_logging("DEBUG")
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1

    cli.setup_logging("ERROR")
    assert root.level == logging.ERROR


def test_debug_level_reaches_the_cli(images, clean_root_logger, capsys):
    assert run([images[0], "-l", "DEBUG"]) == 0
    assert clean_root_logger.level == logging.DEBUG
    assert "Setting" in capsys.readouterr().err


def test_log_messages_with_brackets_do_not_break_the_handler(clean_root_logger, capsys):
    cli.setup_logging("INFO")
    logging.getLogger("x").info("see [/nonsense] and [bold]this[/bold]")
    assert "[/nonsense]" in capsys.readouterr().err


# -------------------------------------------------------------------- sharex


def test_sharex_args_with_and_without_a_language():
    assert sharex_setup.build_action_args() == '--sharex "$input"'
    assert sharex_setup.build_action_args("ru") == '-t ru --sharex "$input"'
    with pytest.raises(ValueError):
        sharex_setup.build_action_args('ru" & calc')


def test_apply_lens_hotkey_adds_then_updates():
    config = {"Hotkeys": []}
    assert sharex_setup.apply_lens_hotkey(config, "C:/a/lens_scan.exe", "X") is False
    assert (
        sharex_setup.apply_lens_hotkey(config, "C:/b/lens_scan.exe", "-t ru Y") is True
    )
    assert len(config["Hotkeys"]) == 1
    program = config["Hotkeys"][0]["TaskSettings"]["ExternalPrograms"][0]
    assert program["Path"] == "C:/b/lens_scan.exe" and program["Args"] == "-t ru Y"


def test_setup_sharex_backs_up_and_writes_atomically(tmp_path, monkeypatch):
    sharex_dir = tmp_path / "ShareX"
    sharex_dir.mkdir()
    config_path = sharex_dir / "HotkeysConfig.json"
    original = '{"Hotkeys": [], "Other": {"keep": true}}'
    config_path.write_text("\ufeff" + original, encoding="utf-8")

    monkeypatch.setattr(sharex_setup.sys, "platform", "win32")
    monkeypatch.setattr(sharex_setup, "get_documents_path", lambda: tmp_path)
    monkeypatch.setattr(sharex_setup, "terminate_sharex", lambda: False)
    monkeypatch.setattr(sharex_setup, "_find_lens_scan", lambda: "C:/x/lens_scan.exe")
    monkeypatch.setattr(sharex_setup, "_restart_sharex", lambda interactive: None)

    assert sharex_setup.setup_sharex_config("ru") is True

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["Other"] == {"keep": True}
    program = saved["Hotkeys"][0]["TaskSettings"]["ExternalPrograms"][0]
    assert program["Args"] == '-t ru --sharex "$input"'

    backups = [p for p in sharex_dir.iterdir() if ".bak-" in p.name]
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8-sig") == original
    assert not [p for p in sharex_dir.iterdir() if p.name.endswith(".tmp")]


def test_setup_sharex_leaves_a_corrupt_file_untouched(tmp_path, monkeypatch):
    sharex_dir = tmp_path / "ShareX"
    sharex_dir.mkdir()
    config_path = sharex_dir / "HotkeysConfig.json"
    config_path.write_text("{not json", encoding="utf-8")

    monkeypatch.setattr(sharex_setup.sys, "platform", "win32")
    monkeypatch.setattr(sharex_setup, "get_documents_path", lambda: tmp_path)
    monkeypatch.setattr(sharex_setup, "terminate_sharex", lambda: False)
    monkeypatch.setattr(sharex_setup, "_find_lens_scan", lambda: "C:/x/lens_scan.exe")
    monkeypatch.setattr(sharex_setup, "_restart_sharex", lambda interactive: None)

    assert sharex_setup.setup_sharex_config() is False
    assert config_path.read_text() == "{not json"
    assert [p.name for p in sharex_dir.iterdir()] == ["HotkeysConfig.json"]


def test_setup_sharex_flag_passes_the_language_and_sets_the_exit_code(monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli, "setup_sharex_config", lambda lang=None: seen.append(lang) or True
    )
    assert run(["--setup-sharex", "-t", "ru"]) == 0
    assert seen == ["ru"]
    monkeypatch.setattr(cli, "setup_sharex_config", lambda lang=None: False)
    assert run(["--setup-sharex"]) == 1
