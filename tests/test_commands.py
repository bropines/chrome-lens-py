"""The command layer: `lens_scan status`, `daemon ...`, `service ...`, `update`.

These are the commands that act on the machine rather than on an image, so
every test here keeps them away from the real one: its own state directory, no
LENS_* in the environment, and the platform layer (ShareX, login items,
installers) replaced by recorders.
"""

import json
import os
import sys

import pytest

from chrome_lens_py import __version__, client, manage, runtime, update


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Own state and config dirs; nothing of the user's machine is read."""
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in list(os.environ):
        if name.startswith("LENS_") and name != "LENS_STATE_DIR":
            monkeypatch.delenv(name)
    monkeypatch.setattr(manage, "sharex_info", lambda: {"supported": False})
    # The login item is a real file on the developer's own machine; point at
    # one inside the sandbox so `status` and `service status` describe that.
    monkeypatch.setattr(
        runtime, "login_item_path", lambda: str(tmp_path / "login-item")
    )
    monkeypatch.setattr(client, "daemon_report", lambda: {"state": "stopped"})
    return tmp_path


SERVICE = {
    "installed": False,
    "mechanism": "login item",
    "path": "p",
    "port": None,
    "token_file": None,
}


def write_receipt(tool_dir, fields):
    """uv's own record of how a tool was installed, as it writes it."""
    (tool_dir / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "chrome-lens-py", ' + fields + " }]\n",
        encoding="utf-8",
    )


def stopped():
    return {"state": "stopped"}


def running(**extra):
    base = {
        "state": "running",
        "pid": 4242,
        "version": __version__,
        "transport": "tcp",
        "address": "127.0.0.1:8765",
        "managed": "auto",
        "uptime": 125,
        "requests": 7,
        "idle_timeout": 600,
        "idle_remaining": 480,
    }
    base.update(extra)
    return base


# ------------------------------------------------------------------- routing


def test_a_scan_is_not_a_command():
    assert manage.route(["img.png"]) is None
    assert manage.route(["img.png", "-t", "ru"]) is None
    assert manage.route([]) is None
    # The flags the commands replaced stay with the old code path.
    assert manage.route(["--daemon-status"]) is None
    assert manage.route(["--setup-sharex", "--mode", "both"]) is None


def test_a_command_wins_over_a_file_of_the_same_name(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "status").write_bytes(b"not an image")
    assert manage.route(["status"]) == ("exit", manage.EXIT_OK)
    assert "lens_scan" in capsys.readouterr().out
    # ... and the file is still reachable, spelled as a path.
    assert manage.route(["./status"]) is None


def test_the_short_help_lists_the_commands_and_the_exit_codes(capsys):
    assert manage.route(["-h"]) == ("exit", manage.EXIT_OK)
    out = capsys.readouterr().out
    for command in manage.COMMANDS:
        assert command in out
    assert "64" in out and "--translate" in out


def test_help_options_hands_over_to_the_full_reference():
    assert manage.route(["help", "options"]) == ("argv", ["--help"])


def test_every_command_explains_itself(capsys):
    for command in manage.COMMANDS:
        if command == "help":
            continue
        assert command in manage.HELP, f"no `help {command}` text"
        assert manage.route(["help", command]) == ("exit", manage.EXIT_OK)
        assert command in capsys.readouterr().out


def test_dash_h_after_a_command_shows_that_command(capsys):
    assert manage.route(["service", "-h"]) == ("exit", manage.EXIT_OK)
    out = capsys.readouterr().out
    assert "lens_scan service" in out and "uninstall" in out


def test_a_typo_is_a_usage_error_that_points_at_the_right_help(capsys):
    assert manage.route(["daemon", "lgos"]) == ("exit", manage.EXIT_USAGE)
    err = capsys.readouterr().err
    assert "lgos" in err and "lens_scan help daemon" in err

    assert manage.route(["status", "--jsno"]) == ("exit", manage.EXIT_USAGE)
    assert "--jsno" in capsys.readouterr().err

    assert manage.route(["daemon", "logs", "--lines"]) == ("exit", manage.EXIT_USAGE)
    assert "needs a value" in capsys.readouterr().err

    assert manage.route(["help", "nonsense"]) == ("exit", manage.EXIT_USAGE)


def test_options_may_be_written_either_way():
    positional, options = manage.parse(
        ["logs", "--lines=5", "--json"], flags=("--json",), values=("--lines",)
    )
    assert positional == ["logs"] and options == {"lines": "5", "json": True}


# -------------------------------------------------------------------- status


def test_status_is_a_health_check_not_just_a_report(monkeypatch, capsys):
    service = {
        "installed": False,
        "mechanism": "x",
        "path": "p",
        "port": None,
        "token_file": None,
    }
    monkeypatch.setattr(manage, "service_info", lambda: dict(service))

    # Nothing running and no service installed is healthy: a daemon starts by
    # itself on the next scan.
    assert manage.route(["status"]) == ("exit", manage.EXIT_OK)
    assert "not running" in capsys.readouterr().out

    # A daemon recorded and no longer answering is not.
    monkeypatch.setattr(
        client,
        "daemon_report",
        lambda: {"state": "unresponsive", "pid": 7, "error": "gone"},
    )
    assert manage.route(["status"]) == ("exit", manage.EXIT_FAIL)
    assert "not answering" in capsys.readouterr().out

    # Nor is a login service with nothing behind it.
    monkeypatch.setattr(client, "daemon_report", stopped)
    monkeypatch.setattr(manage, "service_info", lambda: dict(SERVICE, installed=True))
    assert manage.route(["status"]) == ("exit", manage.EXIT_FAIL)

    monkeypatch.setattr(client, "daemon_report", running)
    assert manage.route(["status"]) == ("exit", manage.EXIT_OK)


def test_status_json_says_everything_the_screen_does(monkeypatch, capsys):
    monkeypatch.setattr(client, "daemon_report", lambda: running(managed="service"))
    assert manage.route(["status", "--json"]) == ("exit", manage.EXIT_OK)
    report = json.loads(capsys.readouterr().out)
    assert report["install"]["version"] == __version__
    assert report["daemon"]["pid"] == 4242
    assert set(report) >= {"install", "config", "state_dir", "daemon", "service"}
    assert report["service"]["mechanism"] == runtime.login_item_kind()


def test_status_takes_no_arguments(capsys):
    assert manage.route(["status", "extra"]) == ("exit", manage.EXIT_USAGE)
    assert "extra" in capsys.readouterr().err


# -------------------------------------------------------------------- daemon


def test_daemon_status_exits_zero_only_while_one_is_running(monkeypatch, capsys):
    assert manage.route(["daemon", "status"]) == ("exit", manage.EXIT_FAIL)
    assert "not running" in capsys.readouterr().out

    monkeypatch.setattr(client, "daemon_report", running)
    assert manage.route(["daemon", "status"]) == ("exit", manage.EXIT_OK)
    out = capsys.readouterr().out
    assert "4242" in out and "2m 05s" in out and "requests   7" in out

    assert manage.route(["daemon", "status", "--json"]) == ("exit", manage.EXIT_OK)
    assert json.loads(capsys.readouterr().out)["requests"] == 7


def test_a_daemon_of_an_older_version_is_reported_as_such(monkeypatch, capsys):
    """It answers with the old behaviour until the next scan retires it."""
    monkeypatch.setattr(
        client, "daemon_report", lambda: running(version="3.0.0", stale=True)
    )
    assert manage.route(["daemon", "status"]) == ("exit", manage.EXIT_OK)
    assert "3.0.0" in capsys.readouterr().out

    monkeypatch.setattr(manage, "service_info", lambda: dict(SERVICE, installed=True))
    assert manage.route(["status"]) == ("exit", manage.EXIT_OK)  # not a fault
    assert "replaced on the next scan" in capsys.readouterr().out


def test_daemon_start_stop_restart_reach_the_client(monkeypatch):
    done = []
    monkeypatch.setattr(
        client, "daemon_start", lambda idle=0: done.append(("start", idle)) or 0
    )
    monkeypatch.setattr(client, "daemon_stop", lambda: done.append(("stop",)) or 0)

    assert manage.route(["daemon", "start", "--idle-timeout", "0"]) == ("exit", 0)
    assert manage.route(["daemon", "stop"]) == ("exit", 0)
    assert manage.route(["daemon", "restart"]) == ("exit", 0)
    assert done == [("start", 0), ("stop",), ("stop",), ("start", 600)]


def test_a_restart_that_cannot_stop_does_not_start_a_second_daemon(monkeypatch):
    started = []
    monkeypatch.setattr(client, "daemon_stop", lambda: 1)
    monkeypatch.setattr(
        client, "daemon_start", lambda idle=0: started.append(idle) or 0
    )
    assert manage.route(["daemon", "restart"]) == ("exit", manage.EXIT_FAIL)
    assert started == []


def test_logs_show_the_end_of_the_file_and_say_so_when_there_is_none(capsys):
    assert manage.route(["daemon", "logs"]) == ("exit", manage.EXIT_OK)
    assert "No log files yet" in capsys.readouterr().out

    runtime.ensure_private_dir(runtime.data_dir(create=True))
    with open(runtime.log_file(), "w", encoding="utf-8") as f:
        f.write("\n".join(f"line {n}" for n in range(100)) + "\n")
    assert manage.route(["daemon", "logs", "--lines", "3"]) == ("exit", manage.EXIT_OK)
    out = capsys.readouterr().out
    assert "line 99" in out and "line 97" in out and "line 96" not in out
    assert runtime.log_file() in out


# ------------------------------------------------------------------- service


def test_service_status_reports_both_halves(monkeypatch, capsys):
    assert manage.route(["service", "status"]) == ("exit", manage.EXIT_FAIL)
    out = capsys.readouterr().out
    assert "not installed" in out and runtime.login_item_path() in out

    monkeypatch.setattr(client, "daemon_report", lambda: running(managed="service"))
    monkeypatch.setattr(
        manage,
        "service_info",
        lambda: {
            "installed": True,
            "mechanism": "Startup shortcut",
            "path": "p",
            "port": 8765,
            "token_file": "t",
        },
    )
    assert manage.route(["service", "status"]) == ("exit", manage.EXIT_OK)
    assert "8765" in capsys.readouterr().out
    assert manage.route(["service", "status", "--json"]) == ("exit", manage.EXIT_OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["service"]["installed"] and payload["daemon"]["state"] == "running"


def test_service_actions_reach_the_platform_layer(monkeypatch):
    from chrome_lens_py.utils import service

    calls = []
    monkeypatch.setattr(
        service, "install_service", lambda port: calls.append(("install", port)) or True
    )
    monkeypatch.setattr(
        service, "uninstall_service", lambda: calls.append(("uninstall",)) or True
    )
    monkeypatch.setattr(
        service, "control", lambda action: calls.append((action,)) or True
    )

    assert manage.route(["service", "install", "--port", "9000"]) == ("exit", 0)
    assert manage.route(["service", "uninstall"]) == ("exit", 0)
    assert manage.route(["service", "restart"]) == ("exit", 0)
    assert calls == [("install", 9000), ("uninstall",), ("restart",)]

    monkeypatch.setattr(service, "control", lambda action: False)
    assert manage.route(["service", "stop"]) == ("exit", manage.EXIT_FAIL)


def test_service_logs_include_the_supervisor_on_windows(monkeypatch, capsys):
    monkeypatch.setattr(manage.sys, "platform", "win32")
    runtime.ensure_private_dir(runtime.data_dir(create=True))
    with open(runtime.supervisor_log_file(), "w", encoding="utf-8") as f:
        f.write("supervisor: daemon started\n")
    assert manage.route(["service", "logs"]) == ("exit", manage.EXIT_OK)
    assert "supervisor: daemon started" in capsys.readouterr().out


# -------------------------------------------------------------------- config


def test_config_path_is_local_and_show_defers_to_the_cli(capsys):
    assert manage.route(["config", "path"]) == ("exit", manage.EXIT_OK)
    assert capsys.readouterr().out.strip() == client.config_path()

    assert manage.route(["config"]) == ("argv", ["--show-config"])
    assert manage.route(["config", "show", "--json"]) == (
        "argv",
        ["--show-config", "--json"],
    )


def test_version_json_without_the_heavy_cli(capsys):
    assert manage.route(["version"]) == ("argv", ["--version"])
    assert manage.route(["version", "--json"]) == ("exit", manage.EXIT_OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == __version__ and payload["python"]


def test_serve_keeps_its_options():
    assert manage.route(["serve", "--port", "9", "--token", "t"]) == (
        "argv",
        ["--serve", "--port", "9", "--token", "t"],
    )


# -------------------------------------------------------------------- update


@pytest.mark.parametrize(
    "executable, kind, expected",
    [
        (
            "/home/u/.local/share/uv/tools/chrome-lens-py/bin/python",
            "uv",
            ["tool", "upgrade", "--reinstall", "chrome-lens-py"],
        ),
        (
            "/home/u/.local/pipx/venvs/chrome-lens-py/bin/python",
            "pipx",
            ["upgrade", "chrome-lens-py"],
        ),
        (
            "/opt/homebrew/Cellar/lens-scan/3.7.1/libexec/bin/python3",
            "brew",
            ["upgrade", "bropines/tap/lens-scan"],
        ),
        (
            "C:/Users/u/scoop/apps/lens-scan-portable/current/python.exe",
            "scoop",
            ["update", "lens-scan-portable"],
        ),
    ],
)
def test_each_install_updates_itself_its_own_way(
    monkeypatch, executable, kind, expected
):
    monkeypatch.setattr(update.sys, "executable", executable)
    monkeypatch.setattr(update, "_git_checkout", lambda package: False)
    found = update.detect()
    assert found.kind == kind
    assert found.command[1:] == expected


def test_a_uv_tool_pinned_to_a_version_is_reinstalled_without_the_pin(
    monkeypatch, tmp_path
):
    """`uv tool upgrade` honours the pin, so it would report success and move nothing."""
    monkeypatch.setattr(
        update.sys,
        "executable",
        "/home/u/.local/share/uv/tools/chrome-lens-py/bin/python",
    )
    monkeypatch.setattr(update, "_git_checkout", lambda package: False)
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path))
    write_receipt(tmp_path, 'extras = ["clipboard"], specifier = "==3.8.0"')
    found = update.detect()
    assert found.kind == "uv" and "pinned" in found.label
    spelled = update.quote(found.command)
    assert "tool install --force --refresh" in spelled
    assert "chrome-lens-py[clipboard]" in spelled
    # The environment is recreated, which Windows will not allow from inside
    # it, so the command goes to a window of its own - one that waits before
    # closing, or its answer would be gone before it could be read.
    assert found.fresh_shell is (sys.platform == "win32")
    if sys.platform == "win32":
        assert found.command[0] == "cmd" and "& pause" in spelled


def test_the_extras_a_uv_tool_was_installed_with_survive(monkeypatch, tmp_path):
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path))
    write_receipt(tmp_path, 'extras = ["clipboard", "rtl"]')
    assert update._uv_requirement() == ("chrome-lens-py[clipboard,rtl]", False)

    (tmp_path / "uv-receipt.toml").unlink()
    requirement, pinned = update._uv_requirement()  # no receipt: still answers
    assert requirement.startswith("chrome-lens-py") and pinned is False


def test_a_plain_python_install_is_updated_with_pip(monkeypatch):
    monkeypatch.setattr(update.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(update, "_git_checkout", lambda package: False)
    monkeypatch.setattr(update, "_has_clipboard", lambda: True)
    found = update.detect()
    assert found.kind == "pip"
    assert found.command[1:] == [
        "-m",
        "pip",
        "install",
        "--upgrade",
        "chrome-lens-py[clipboard]",
    ]


def test_what_cannot_be_updated_for_you_says_what_to_do(monkeypatch):
    monkeypatch.setattr(update.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(update, "_git_checkout", lambda package: True)
    found = update.detect()
    assert found.kind == "source" and found.command is None and found.hint


def test_versions_are_compared_as_numbers():
    assert update.is_newer("3.8.0", "3.7.1")
    assert update.is_newer("3.10.0", "3.9.9")  # not as strings
    assert not update.is_newer("3.7.1", "3.7.1")
    assert not update.is_newer("", "3.7.1")
    assert update.parse_version("v3.8.0") == (3, 8, 0)


def test_the_newest_version_comes_from_pypi(monkeypatch):
    import urllib.request

    class Reply:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=0: Reply(b'{"info": {"version": "9.9.9"}}'),
    )
    assert update.latest() == "9.9.9"

    def refuse(request, timeout=0):
        raise OSError("no network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert update.latest() is None  # never raises: it is only ever advice


def test_check_reports_and_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(update, "latest", lambda: "9.9.9")
    monkeypatch.setattr(
        update, "detect", lambda: update.Install("pip", "pip", ["pip", "x"])
    )
    monkeypatch.setattr(update, "run", lambda cmd: pytest.fail("ran an update"))

    assert manage.route(["update", "--check"]) == ("exit", manage.EXIT_OK)
    out = capsys.readouterr().out
    assert "9.9.9" in out and "update available" in out

    assert manage.route(["update", "--dry-run"]) == ("exit", manage.EXIT_OK)
    assert "Would run: pip x" in capsys.readouterr().out

    assert manage.route(["update", "--json"]) == ("exit", manage.EXIT_OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["update_available"] and payload["command"] == "pip x"


def test_an_update_stops_the_daemon_and_puts_the_service_back(monkeypatch, capsys):
    from chrome_lens_py.utils import service

    order = []
    monkeypatch.setattr(update, "latest", lambda: "9.9.9")
    monkeypatch.setattr(
        update, "detect", lambda: update.Install("pip", "pip", ["pip", "x"])
    )
    monkeypatch.setattr(
        update, "run", lambda cmd: order.append(("run", list(cmd))) or 0
    )
    monkeypatch.setattr(client, "daemon_report", lambda: running(managed="service"))
    monkeypatch.setattr(client, "daemon_stop", lambda: order.append(("stop",)) or 0)
    monkeypatch.setattr(
        service, "control", lambda action: order.append((action,)) or True
    )

    assert manage.route(["update"]) == ("exit", manage.EXIT_OK)
    assert order == [("stop",), ("run", ["pip", "x"]), ("restart",)]
    assert "Updated." in capsys.readouterr().out


def test_a_failed_update_brings_the_daemon_back_and_fails(monkeypatch, capsys):
    order = []
    monkeypatch.setattr(update, "latest", lambda: "9.9.9")
    monkeypatch.setattr(
        update, "detect", lambda: update.Install("pip", "pip", ["pip", "x"])
    )
    monkeypatch.setattr(update, "run", lambda cmd: 1)
    monkeypatch.setattr(client, "daemon_report", running)
    monkeypatch.setattr(client, "daemon_stop", lambda: order.append("stop") or 0)
    monkeypatch.setattr(
        client, "daemon_start", lambda idle=0: order.append("start") or 0
    )

    assert manage.route(["update"]) == ("exit", manage.EXIT_FAIL)
    assert order == ["stop", "start"]
    assert "failed" in capsys.readouterr().out


def test_an_install_that_replaces_itself_is_handed_a_window_of_its_own(
    monkeypatch, capsys
):
    handed = []
    monkeypatch.setattr(update, "latest", lambda: "9.9.9")
    monkeypatch.setattr(
        update,
        "detect",
        lambda: update.Install(
            "installer", "standalone", ["ps", "x"], fresh_shell=True
        ),
    )
    monkeypatch.setattr(update, "run", lambda cmd: pytest.fail("ran in-process"))
    monkeypatch.setattr(
        update, "run_detached", lambda cmd: handed.append(list(cmd)) or True
    )

    assert manage.route(["update"]) == ("exit", manage.EXIT_OK)
    assert handed == [["ps", "x"]]
    assert "window of its own" in capsys.readouterr().out


# ------------------------------------------------------------------ the entry


def test_entry_runs_a_command_without_waking_the_daemon(monkeypatch):
    forwarded = []
    monkeypatch.setattr(client, "try_remote", lambda argv: forwarded.append(argv))
    monkeypatch.setattr(client, "daemon_report", running)
    with pytest.raises(SystemExit) as stop:
        client.entry(["daemon", "status"])
    assert stop.value.code == 0 and forwarded == []


def test_entry_rewrites_a_command_into_the_flags_the_cli_knows(monkeypatch):
    seen = []
    import chrome_lens_py.cli.main as cli

    monkeypatch.setattr(cli, "run", lambda: seen.append(list(sys.argv[1:])))
    monkeypatch.setattr(client, "try_remote", lambda argv: None)
    saved = list(sys.argv)
    try:
        client.entry(["version"])
    finally:
        sys.argv[:] = saved
    assert seen == [["--version"]]


def test_report_states_are_rendered_the_same_way_in_both_outputs(monkeypatch, capsys):
    """One shape for the daemon's state, two ways of printing it."""
    for report in (
        stopped(),
        running(),
        {"state": "unresponsive", "pid": 1, "error": "x"},
    ):
        monkeypatch.setattr(client, "daemon_report", lambda report=report: report)
        manage.print_daemon(report)
        text = capsys.readouterr().out
        assert text.startswith("lens_scan daemon:")
        assert client.daemon_status() == (0 if report["state"] == "running" else 1)
        capsys.readouterr()


def test_duration_reads_like_a_duration():
    assert manage.duration(0) == "0s"
    assert manage.duration(65) == "1m 05s"
    assert manage.duration(3725) == "1h 02m 05s"
    assert manage.duration(None) == "unknown"


def test_install_info_knows_which_copy_is_running():
    info = manage.install_info()
    assert info["version"] == __version__
    assert info["flavour"] in (
        "standalone build",
        "installed package",
        "source checkout",
    )
    assert os.path.isdir(info["package"])
    assert isinstance(info["clipboard"], bool)


def test_nothing_in_the_command_layer_imports_the_world():
    """manage.py is read on every run, including a scan racing a warm daemon."""
    source = open(
        os.path.join(os.path.dirname(manage.__file__), "manage.py"), encoding="utf-8"
    ).read()
    head = source.split("def ")[0]
    for heavy in ("rich", "httpx", "PIL", "argparse", "from .utils", "from .cli"):
        assert heavy not in head, f"{heavy} imported at module level"


def test_service_info_follows_the_login_item_and_the_token_file():
    info = manage.service_info()
    assert info["path"] == runtime.login_item_path()
    assert info["installed"] is False and info["port"] is None

    runtime.write_private_json(runtime.service_file(), {"port": 8765, "token": "t"})
    open(runtime.login_item_path(), "w").close()
    refreshed = manage.service_info()
    assert refreshed["installed"] and refreshed["port"] == 8765
    assert refreshed["token_file"] == runtime.service_file()


def test_the_login_item_belongs_to_this_platform(monkeypatch):
    monkeypatch.undo()  # look at the real one: read only, never written here
    assert runtime.login_item_kind() in (
        "Startup shortcut",
        "LaunchAgent",
        "systemd --user unit",
    )
    path = runtime.login_item_path()
    assert os.path.isabs(path) and os.path.basename(path)


def test_the_supervisor_flag_is_still_not_a_command():
    """The login item passes it to a stdlib-only path; no command may shadow it."""
    assert runtime.SUPERVISE_FLAG not in manage.COMMANDS
    assert manage.route([runtime.SUPERVISE_FLAG]) is None


def test_update_hints_never_tell_you_to_run_nothing():
    for install in (
        update.Install("docker", "Docker image", hint="docker pull ..."),
        update.Install("source", "source checkout", hint="git pull"),
    ):
        assert install.command is None and install.hint
    assert update.quote(["a b", "c"])
