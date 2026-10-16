"""The daemon end to end, with LensAPI replaced by the fake from test_cli.

The headline test is parity: the same command line gives the same stdout and
exit code (and, where it is deterministic, stderr) whether it runs in-process
or through client -> socket -> daemon -> CLI.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path

import pytest
from PIL import Image

from chrome_lens_py import __version__, client, daemon, runtime
from chrome_lens_py.cli import main as cli
from chrome_lens_py.exceptions import LensAPIError
from chrome_lens_py.server import LensServer

from .test_cli import FakeAPI

TOKEN = "d" * 24
SRC = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("LENS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    FakeAPI.instances = []
    FakeAPI.handler = staticmethod(lambda path, kw: "hello")
    monkeypatch.setattr(cli, "LensAPI", FakeAPI)
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda text: True)
    monkeypatch.setattr(
        runtime, "spawn_detached", lambda args: pytest.fail("must not spawn here")
    )
    # Logging handlers are process-global; give every test its own.
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])


@pytest.fixture
def images(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        path = tmp_path / name
        Image.new("RGB", (200, 100), "white").save(path)
        paths.append(str(path))
    return paths


class DaemonThread:
    """A real LensServer + CLI handler on a background event loop, published
    through daemon.json exactly as the managed daemon would."""

    def __init__(self):
        self.cache = daemon.ApiCache()
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.server = None

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        self.server = LensServer(
            object(),
            port=0,
            token=TOKEN,
            cli_handler=partial(cli.run_cli_request, api_provider=self.cache.acquire),
        )
        await self.server.start()
        runtime.write_private_json(
            runtime.daemon_file(),
            {
                "version": __version__,
                "pid": os.getpid(),
                "transport": "tcp",
                "address": f"127.0.0.1:{self.server.port}",
                "token": TOKEN,
                "started_at": time.time(),
            },
        )
        self.ready.set()
        await self.server._stop_event.wait()
        await self.server.stop(grace=1)

    def __enter__(self):
        self.thread.start()
        assert self.ready.wait(10)
        return self

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.server.request_stop)
        self.thread.join(10)


def in_process(argv, capfd):
    code = cli.main([str(a) for a in argv])
    out, err = capfd.readouterr()
    return code, out, err


def via_daemon(argv, capfd):
    code = client.try_remote([str(a) for a in argv])
    assert code is not None, "the daemon declined"
    out, err = capfd.readouterr()
    return code, out, err


PARITY = [
    ("plain", lambda p: [p[0]]),
    ("translate", lambda p: [p[0], "-t", "ru"]),
    ("quiet", lambda p: [p[0], "-q"]),
    ("oneline", lambda p: [p[0], "--oneline"]),
    ("json", lambda p: [p[0], "--format", "json"]),
    ("jsonl-dir", lambda p: [str(Path(p[0]).parent), "--format", "jsonl"]),
    ("hocr", lambda p: [p[0], "--format", "hocr"]),
    ("tsv", lambda p: [p[0], "--format", "tsv"]),
    ("blocks", lambda p: [p[0], "-b"]),
    ("lines", lambda p: [p[0], "-ol"]),
    ("coords", lambda p: [p[0], "--get-coords"]),
    ("single-line", lambda p: [p[0], "--ocr-single-line"]),
    ("dir", lambda p: [str(Path(p[0]).parent)]),
    ("sharex", lambda p: [p[0], "--sharex"]),
    ("bad-mode-mix", lambda p: [p[0], "--format", "json", "--get-coords"]),
    ("not-an-image", lambda p: [p[0] + ".missing"]),
]


@pytest.mark.parametrize("name,build", PARITY, ids=[p[0] for p in PARITY])
def test_same_command_same_result_in_process_and_through_the_daemon(
    name, build, images, capfd
):
    argv = build(images)
    local = in_process(argv, capfd)
    with DaemonThread():
        remote = via_daemon(argv, capfd)
    assert remote[0] == local[0]
    assert remote[1] == local[1]
    assert remote[2] == local[2]


def test_failures_have_the_same_exit_codes_and_streams(images, capfd):
    def handler(path, kw):
        if path.endswith("b.png"):
            raise LensAPIError("bad b")
        return "ok " + os.path.basename(path)

    FakeAPI.handler = staticmethod(handler)
    directory = str(Path(images[0]).parent)
    local = in_process([directory], capfd)
    with DaemonThread():
        remote = via_daemon([directory], capfd)
    assert local[0] == 2 and remote == local

    FakeAPI.handler = staticmethod(
        lambda p, kw: (_ for _ in ()).throw(LensAPIError("all bad"))
    )
    local = in_process([directory], capfd)
    with DaemonThread():
        remote = via_daemon([directory], capfd)
    assert local[0] == 1 and remote == local


def test_a_config_file_warning_reaches_the_clients_stderr(images, tmp_path, capfd):
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"timeout": 12, "no_such_setting": 1}))
    argv = [images[0], "--config-file", str(config)]
    local = in_process(argv, capfd)
    assert "no_such_setting" in local[2]
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    daemon.install_daemon_logging()
    with DaemonThread():
        remote = via_daemon(argv, capfd)
    assert "no_such_setting" in remote[2]
    assert remote[0] == local[0] and remote[1] == local[1]


# ---------------------------------------------------- cwd, env, the API cache


def test_relative_paths_resolve_against_the_clients_directory(
    images, tmp_path, monkeypatch, capfd
):
    folder = Path(images[0]).parent
    monkeypatch.chdir(folder)  # the "client"
    assert os.getcwd() != str(Path(__file__).parent)
    FakeAPI.handler = staticmethod(lambda p, kw: "text")
    with DaemonThread():
        code = client.try_remote(["a.png", "--oneline", "-to", "out.png", "-t", "ru"])
    out, _ = capfd.readouterr()
    assert code == 0
    # Shown as typed...
    assert json.loads(out)["file"] == "a.png"
    # ...opened and written where the client meant.
    call = FakeAPI.instances[-1].calls[-1]
    assert call["image_path"] == str(folder / "a.png")
    assert call["output_overlay_path"] == str(folder / "out.png")


def test_a_relative_font_and_config_file_resolve_too(images, tmp_path, monkeypatch):
    folder = Path(images[0]).parent
    (folder / "my.json").write_text('{"timeout": 31}')
    monkeypatch.chdir(folder)
    with DaemonThread():
        assert (
            client.try_remote(["a.png", "--config-file", "my.json", "--font", "f.ttf"])
            == 0
        )
    kwargs = FakeAPI.instances[-1].init_kwargs
    assert kwargs["timeout"] == 31
    assert kwargs["font_path"] == str(folder / "f.ttf")


def test_settings_come_from_the_clients_environment_not_the_daemons(
    images, monkeypatch
):
    monkeypatch.setenv("LENS_TIMEOUT", "99")  # the daemon's own, inherited env
    with DaemonThread() as d:
        # A client whose environment says 7: simulated by the request itself.
        reply = asyncio.run_coroutine_threadsafe(
            d.cache.acquire(
                cli.resolve_settings({}, None, env={"LENS_TIMEOUT": "7"}),
                {"LENS_TIMEOUT": "7"},
            ),
            d.loop,
        ).result(10)
    assert reply.init_kwargs["timeout"] == 7


def test_the_api_is_reused_for_equal_settings_and_stays_open(images):
    async def go():
        cache = daemon.ApiCache(max_size=2)
        env = {}
        s1 = cli.resolve_settings({}, None, env={})
        a = await cache.acquire(s1, env)
        again = await cache.acquire(cli.resolve_settings({}, None, env={}), env)
        other = await cache.acquire(
            cli.resolve_settings({"timeout": 5}, None, env={}), env
        )
        # Rendering options are per call, so they do not split the cache.
        render = await cache.acquire(
            cli.resolve_settings({"overlay_mode": "legacy"}, None, env={}), env
        )
        return a, again, other, render, cache

    a, again, other, render, cache = asyncio.run(go())
    assert a is again and a is render and other is not a
    assert not a.closed


def test_the_cache_keys_on_every_construction_setting():
    async def go():
        cache = daemon.ApiCache(max_size=50)
        base = {}
        variants = [
            {},
            {"api_key": "k"},
            {"proxy": "http://p:1"},
            {"trust_env": False},
            {"timeout": 5},
            {"client_region": "DE"},
            {"client_time_zone": "Europe/Berlin"},
            {"retries": 0},
            {"concurrency": 3},
            {"font_size": 12},
        ]
        apis = [
            await cache.acquire(cli.resolve_settings(v, None, env={}), base)
            for v in variants
        ]
        endpoint = await cache.acquire(
            cli.resolve_settings({}, None, env={}), {"LENS_ENDPOINT": "http://e/x"}
        )
        return apis, endpoint

    apis, endpoint = asyncio.run(go())
    assert len({id(a) for a in apis}) == len(apis)
    assert endpoint is not apis[0]
    assert endpoint.init_kwargs["endpoints"] == ["http://e/x"]
    assert apis[0].init_kwargs["endpoints"]  # explicit, never the daemon's env


def test_two_requests_share_one_api_and_do_not_close_it(images, capfd):
    with DaemonThread():
        assert client.try_remote([images[0]]) == 0
        assert client.try_remote([images[1], "-t", "ru"]) == 0
    assert len(FakeAPI.instances) == 1
    assert len(FakeAPI.instances[0].calls) == 2
    assert not FakeAPI.instances[0].closed


def test_concurrent_requests_do_not_mix_their_output(images):
    async def go():
        cache = daemon.ApiCache()
        base = Path(images[0]).parent

        def handler(path, kw):
            return "text of " + os.path.basename(path)

        FakeAPI.handler = staticmethod(handler)

        async def one(name, extra):
            return await cli.run_cli_request(
                argv=[name, *extra],
                cwd=str(base),
                env={},
                api_provider=cache.acquire,
            )

        return await asyncio.gather(
            one("a.png", []),
            one("b.png", ["--oneline"]),
            one("c.png", ["-q"]),
            one("a.png", ["--format", "json"]),
        )

    a, b, c, j = asyncio.run(go())
    assert a["stdout"] == "text of a.png\n"
    assert json.loads(b["stdout"])["ocr_text"] == "text of b.png"
    assert c["stdout"] == "text of c.png\n" and c["stderr"] == ""
    assert json.loads(j["stdout"])["file"] == "a.png"


def test_debug_logging_goes_to_the_requesting_client_only(images, capfd):
    daemon.install_daemon_logging()
    with DaemonThread():
        code = client.try_remote([images[0], "--timeout", "5", "-l", "DEBUG"])
    out, err = capfd.readouterr()
    assert code == 0
    assert "from command line" in err  # the per-setting debug lines
    assert "from command line" not in out


def test_sharex_copies_inside_the_daemon(images, monkeypatch):
    copied = []
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda t: copied.append(t) or True)
    with DaemonThread():
        assert client.try_remote([images[0], "--sharex", "-q"]) == 0
    assert copied == ["hello"]


# ------------------------------------------------- what the daemon hands back


@pytest.mark.parametrize(
    "argv",
    [
        ["--serve"],
        ["--setup-sharex"],
        ["--update-config", "--timeout", "5"],
        ["--version"],
        ["-V"],
        ["--help"],
        ["--install-service"],
        ["--uninstall-service"],
        ["--daemon-status"],
        ["--daemon-stop"],
        ["--daemon-start"],
        [],  # no image: the CLI prints help to stderr
        ["--no-such-flag"],  # argparse would print usage and exit
        ["img.png", "--timeout", "notanumber"],
    ],
)
def test_commands_that_must_run_in_the_clients_process_are_declined(argv):
    result = asyncio.run(
        cli.run_cli_request(argv=argv, cwd=os.getcwd(), env={}, stdin_is_tty=False)
    )
    assert "run_locally" in result and "exit_code" not in result


def test_a_crash_inside_a_run_becomes_an_error_reply_not_a_hang(monkeypatch, images):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "_run_batch", boom)
    result = asyncio.run(cli.run_cli_request(argv=[images[0]], cwd=os.getcwd(), env={}))
    assert result["exit_code"] == 1 and "kaboom" in result["stderr"]


# --------------------------------------------------------- uploader / service


def test_service_config_is_created_once_and_the_token_is_stable():
    first = daemon.ensure_service_config(None)
    assert first["port"] == 8765 and len(first["token"]) >= 32
    assert daemon.ensure_service_config(None) == first
    moved = daemon.ensure_service_config(9001)
    assert moved["port"] == 9001 and moved["token"] == first["token"]
    assert daemon.read_service_config() == moved


def test_the_uploader_file_matches_what_sharex_expects():
    from chrome_lens_py.utils import sharex_setup

    cfg = sharex_setup.build_uploader_config(8765, "tok", "ru")
    assert cfg["DestinationType"] == "ImageUploader"
    assert cfg["RequestMethod"] == "POST" and cfg["Body"] == "Binary"
    assert cfg["RequestURL"] == "http://127.0.0.1:8765/v1/ocr/raw"
    assert cfg["Headers"] == {"Authorization": "Bearer tok"}
    assert cfg["Parameters"] == {"translate_to": "ru"}
    assert cfg["URL"] == "{response}" and cfg["ErrorMessage"] == "{json:error}"
    assert "Parameters" not in sharex_setup.build_uploader_config(1, "t")
    with pytest.raises(ValueError):
        sharex_setup.build_uploader_config(1, "t", 'ru" & calc')


def test_setup_uploader_writes_the_file_and_starts_the_service_daemon(
    tmp_path, monkeypatch, capsys
):
    from chrome_lens_py.utils import sharex_setup

    monkeypatch.setattr(sharex_setup, "get_documents_path", lambda: tmp_path)
    (tmp_path / "ShareX").mkdir()
    started = []
    monkeypatch.setattr(client, "start_daemon", lambda *a: started.append(1) or True)
    monkeypatch.setattr(client, "wait_for_daemon", lambda *a, **k: {"pid": 1})
    assert sharex_setup.setup_sharex_uploader("ru", 8800) is True
    written = json.loads(
        (tmp_path / "ShareX" / sharex_setup.UPLOADER_FILENAME).read_text()
    )
    service = daemon.read_service_config()
    assert written["RequestURL"].endswith(":8800/v1/ocr/raw")
    assert written["Headers"]["Authorization"] == f"Bearer {service['token']}"
    assert started == [1]
    assert "Double-click" in capsys.readouterr().out


def test_cli_setup_sharex_mode_selects_uploader_or_program(monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli,
        "setup_sharex_uploader",
        lambda lang, port: seen.append(("up", lang, port)) or True,
    )
    monkeypatch.setattr(
        cli,
        "setup_sharex_config",
        lambda lang=None: seen.append(("prog", lang)) or True,
    )
    assert (
        cli.main(["--setup-sharex", "--mode", "uploader", "-t", "de", "--port", "9000"])
        == 0
    )
    assert cli.main(["--setup-sharex", "-t", "de"]) == 0
    assert seen == [("up", "de", 9000), ("prog", "de")]


def test_service_files_for_each_platform():
    import plistlib

    from chrome_lens_py.utils import service

    command = ["/usr/bin/python3", "-m", "chrome_lens_py", "--serve", "--service"]
    unit = service.render_systemd_unit(command + ["a b", "100%"])
    assert "ExecStart=/usr/bin/python3 -m chrome_lens_py --serve --service" in unit
    assert "'a b'" in unit and "100%%" in unit  # quoted, % escaped for systemd
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit

    plist = plistlib.loads(service.render_launch_agent(command, "/tmp/d.log"))
    assert plist["ProgramArguments"] == command
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["Label"] == service.LAUNCH_AGENT_LABEL

    assert service.windowless(["C:/Py/python.exe", "-m", "x"])[1:] == ["-m", "x"]
    assert service.windowless(["C:/x/lens_scan.exe", "--serve"]) == [
        "C:/x/lens_scan.exe",
        "--serve",
    ]


# ------------------------------------------- the real daemon, as a subprocess


def run_lens(*args, timeout=30, **kwargs):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "chrome_lens_py", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        **kwargs,
    )


def wait_gone(path, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def real_daemon_cleanup():
    yield
    run_lens("--daemon-stop", timeout=30)


def test_start_status_stop_of_a_real_daemon(
    real_daemon_cleanup, monkeypatch, short_tmp
):
    monkeypatch.undo()  # undo the fixture's spawn blocker; keep nothing else
    # Short on purpose: on macOS a tmp_path is too long for an AF_UNIX path,
    # and the daemon would (correctly) fall back to TCP.
    monkeypatch.setenv("LENS_STATE_DIR", os.path.join(short_tmp, "rs"))
    assert run_lens("--daemon-status").returncode == 1

    started = run_lens("--daemon-start")
    assert started.returncode == 0, started.stderr
    assert "started" in started.stdout

    info = runtime.read_daemon()
    assert info and info["version"] == __version__ and info["pid"] != os.getpid()
    assert runtime.pid_alive(info["pid"])
    if os.name == "posix":
        assert info["transport"] == "unix"
        assert os.stat(info["address"]).st_mode & 0o777 == 0o600
        assert os.stat(runtime.daemon_file()).st_mode & 0o777 == 0o600
        assert os.stat(runtime.state_dir()).st_mode & 0o777 == 0o700
    else:
        assert info["transport"] == "tcp" and info["address"].startswith("127.0.0.1:")

    status = run_lens("--daemon-status")
    assert status.returncode == 0 and str(info["pid"]) in status.stdout
    again = run_lens("--daemon-start")
    assert "already running" in again.stdout

    stopped = run_lens("--daemon-stop")
    assert stopped.returncode == 0 and "stopped" in stopped.stdout
    assert wait_gone(runtime.daemon_file())
    assert not runtime.pid_alive(info["pid"]) or wait_gone(runtime.daemon_file())
    if os.name == "posix":
        assert not os.path.exists(info["address"])


def test_spawning_does_not_hold_the_callers_pipes_open(
    real_daemon_cleanup, monkeypatch, tmp_path
):
    """ShareX reads our stdout to EOF; a daemon holding it would hang ShareX."""
    monkeypatch.undo()
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "rs"))
    started = time.monotonic()
    done = run_lens("--daemon-start", timeout=30)  # capture_output=True: pipes
    assert done.returncode == 0
    assert time.monotonic() - started < 25
    # The daemon outlived the call that started it, yet the call returned.
    assert runtime.pid_alive(runtime.read_daemon()["pid"])


def test_a_real_daemon_exits_on_its_own_when_idle_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "rs"))
    done = run_lens("--daemon-start", "--daemon-idle-timeout", "2")
    assert done.returncode == 0, done.stderr
    pid = runtime.read_daemon()["pid"]
    assert wait_gone(runtime.daemon_file(), 20)
    deadline = time.monotonic() + 10
    while runtime.pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not runtime.pid_alive(pid)
    assert not os.path.exists(os.path.join(runtime.state_dir(), runtime.LOCK_FILE))


def test_an_old_daemon_is_replaced_by_the_new_version(
    real_daemon_cleanup, monkeypatch, tmp_path
):
    monkeypatch.undo()
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "rs"))
    assert run_lens("--daemon-start").returncode == 0
    old = runtime.read_daemon()
    # Pretend that daemon is from another release.
    runtime.write_private_json(runtime.daemon_file(), {**old, "version": "0.0.1"})
    done = run_lens("--daemon-start")
    assert done.returncode == 0, done.stderr
    new = runtime.read_daemon()
    assert new["version"] == __version__ and new["token"] != old["token"]
    deadline = time.monotonic() + 10
    while runtime.pid_alive(old["pid"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not runtime.pid_alive(old["pid"])


@pytest.mark.network
def test_two_real_requests_through_a_real_auto_daemon(
    real_daemon_cleanup, monkeypatch, tmp_path
):
    """Live: spawn the daemon the way `auto` does and send two real OCR requests."""
    monkeypatch.undo()
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "rs"))
    from PIL import ImageDraw, ImageFont

    image = Image.new("RGB", (700, 160), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 56)
    except OSError:
        font = ImageFont.load_default(56)
    draw.text((20, 40), "Daemon warm test", font=font, fill="black")
    path = tmp_path / "live.png"
    image.save(path)

    assert run_lens("--daemon-start").returncode == 0
    first = run_lens(str(path), "-q", timeout=120)
    second = run_lens(str(path), "-q", timeout=120)
    assert first.returncode == 0 and second.returncode == 0, first.stderr
    assert "warm" in first.stdout.lower() and first.stdout == second.stdout
    status = run_lens("--daemon-status")
    assert "requests   2" in status.stdout


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX path limit")
def test_daemon_falls_back_to_tcp_when_the_socket_path_is_too_long(
    real_daemon_cleanup, monkeypatch, short_tmp
):
    # A state directory deep enough that the socket path cannot fit in
    # sun_path. The daemon must still come up - over loopback TCP with its
    # token - rather than fail to bind.
    monkeypatch.undo()
    deep = os.path.join(short_tmp, *(["d" * 40] * 3))
    monkeypatch.setenv("LENS_STATE_DIR", deep)
    started = run_lens("--daemon-start")
    assert started.returncode == 0, started.stderr
    info = runtime.read_daemon()
    assert info and info["transport"] == "tcp"
    assert run_lens("--daemon-status").returncode == 0
