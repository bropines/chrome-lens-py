"""The thin client and the files it relies on: discovery, fallback, spawn lock.

A fake daemon (a thread speaking just enough HTTP) stands in for the real one,
so every failure the client must survive can be produced on demand.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from chrome_lens_py import __version__, client, runtime

POSIX = os.name == "posix"


@pytest.fixture(autouse=True)
def state(monkeypatch, tmp_path):
    """Own state dir, no LENS_* in the environment, nothing really spawned."""
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in list(os.environ):
        if name.startswith("LENS_") and name != "LENS_STATE_DIR":
            monkeypatch.delenv(name)
    spawned = []
    monkeypatch.setattr(
        runtime, "spawn_detached", lambda args: spawned.append(list(args)) or True
    )
    return SimpleNamespace(spawned=spawned, dir=tmp_path / "state")


# --------------------------------------------------------------- fake daemon


def http_reply(status=200, payload=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    head = (
        f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    )
    return head.encode("latin-1") + body


class FakeDaemon:
    """Listens on loopback; `behave(request_bytes)` returns the reply bytes.

    Returning None closes the connection without answering; `hang` makes it
    read the request and then say nothing.
    """

    def __init__(self, behave=None, hang=False):
        self.behave = behave or (
            lambda req: http_reply(
                200, {"exit_code": 0, "stdout": "from daemon\n", "stderr": ""}
            )
        )
        self.hang = hang
        self.requests = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.token = "tok-" + "x" * 20
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.sock.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        conn.settimeout(5)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, _, body = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n")[1:]:
                key, _, value = line.partition(b":")
                if key.strip().lower() == b"content-length":
                    length = int(value)
            while len(body) < length:
                body += conn.recv(65536)
            self.requests.append((head, body))
            if self.hang:
                self._stop.wait(5)
                return
            reply = self.behave(head + b"\r\n\r\n" + body)
            if reply is not None:
                conn.sendall(reply)
        finally:
            conn.close()

    def publish(self, version=None, pid=None, token=None):
        runtime.write_private_json(
            runtime.daemon_file(),
            {
                "version": version or __version__,
                "pid": pid or os.getpid(),
                "transport": "tcp",
                "address": f"127.0.0.1:{self.port}",
                "token": token or self.token,
                "started_at": time.time(),
            },
        )

    def close(self):
        self._stop.set()
        self.sock.close()


@pytest.fixture
def fake():
    made = []

    def make(**kwargs):
        d = FakeDaemon(**kwargs)
        made.append(d)
        return d

    yield make
    for d in made:
        d.close()


def unused_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------- discovery file


def test_state_dir_honours_the_override(state):
    assert runtime.state_dir() == str(state.dir)


def test_write_is_atomic_complete_and_private(state):
    runtime.write_private_json(runtime.daemon_file(), {"a": 1})
    assert runtime.read_json(runtime.daemon_file()) == {"a": 1}
    assert [p.name for p in state.dir.iterdir()] == ["daemon.json"]  # no temp left
    if POSIX:
        assert os.stat(runtime.daemon_file()).st_mode & 0o777 == 0o600
        assert os.stat(state.dir).st_mode & 0o777 == 0o700


def test_read_daemon_rejects_malformed_files(state):
    path = runtime.daemon_file()
    os.makedirs(state.dir)
    assert runtime.read_daemon() is None  # absent
    for text in ("", "{not json", "[]", '{"pid": "x"}', '{"transport": "ftp"}'):
        with open(path, "w") as f:
            f.write(text)
        assert runtime.read_daemon() is None


def test_remove_only_deletes_the_file_of_the_same_daemon(state):
    runtime.write_private_json(runtime.daemon_file(), {"token": "new"})
    runtime.remove_daemon_file("old")
    assert os.path.exists(runtime.daemon_file())
    runtime.remove_daemon_file("new")
    assert not os.path.exists(runtime.daemon_file())


def test_pid_alive_sees_this_process_and_a_dead_one():
    assert runtime.pid_alive(os.getpid())
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert not runtime.pid_alive(done.pid)
    assert not runtime.pid_alive(0)


# ----------------------------------------------------------------- spawn lock


def test_spawn_lock_admits_one_holder_and_goes_stale(state):
    assert runtime.acquire_spawn_lock()
    assert not runtime.acquire_spawn_lock()
    assert runtime.acquire_spawn_lock(stale_after=0)  # a leftover is taken over
    runtime.release_spawn_lock()
    assert runtime.acquire_spawn_lock()


def test_concurrent_first_calls_spawn_exactly_one_daemon(state):
    winners = []
    barrier = threading.Barrier(16)

    def race():
        barrier.wait()
        if runtime.acquire_spawn_lock():
            winners.append(1)

    threads = [threading.Thread(target=race) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_start_daemon_spawns_once_while_the_lock_is_held(state):
    assert client.start_daemon(123) is True
    assert client.start_daemon(123) is False
    assert state.spawned == [["--serve", "--auto", "--daemon-idle-timeout", "123"]]


def test_start_daemon_uses_the_service_profile_once_uploader_mode_is_set_up(state):
    runtime.write_private_json(
        os.path.join(runtime.data_dir(), runtime.SERVICE_FILE),
        {"port": 8765, "token": "t"},
    )
    assert client.start_daemon() is True
    # On Windows the service daemon runs under the supervisor, as the login
    # item starts it; elsewhere launchd/systemd do the restarting.
    expected = (
        [runtime.SUPERVISE_FLAG]
        if sys.platform == "win32"
        else list(runtime.SERVICE_DAEMON_ARGS)
    )
    assert state.spawned == [expected]


# ----------------------------------------------------------- spawn command line


def test_daemon_command_for_a_source_or_pip_install(monkeypatch):
    monkeypatch.setattr(runtime, "is_compiled", lambda: False)
    monkeypatch.setattr(runtime, "_isolated", lambda: False)
    cmd = runtime.daemon_command(["--serve", "--auto"])
    assert cmd == [sys.executable, "-m", "chrome_lens_py", "--serve", "--auto"]


def test_daemon_command_keeps_isolated_mode_for_the_portable_build(monkeypatch):
    monkeypatch.setattr(runtime, "is_compiled", lambda: False)
    monkeypatch.setattr(runtime, "_isolated", lambda: True)
    cmd = runtime.daemon_command(["--serve"])
    assert cmd == [sys.executable, "-I", "-m", "chrome_lens_py", "--serve"]


def test_daemon_command_for_a_compiled_binary_runs_the_binary_itself(
    monkeypatch, tmp_path
):
    exe = tmp_path / ("lens_scan.exe" if os.name == "nt" else "lens_scan")
    exe.write_bytes(b"")
    monkeypatch.setattr(runtime, "is_compiled", lambda: True)
    monkeypatch.setattr(sys, "argv", [str(exe), "image.png"])
    assert runtime.daemon_command(["--serve", "--auto"]) == [
        str(exe),
        "--serve",
        "--auto",
    ]


# -------------------------------------------------------------------- the mode


def test_mode_defaults_to_auto():
    assert client.resolve_mode([], {}) == ("auto", 600)


def test_mode_precedence_flag_then_config_then_env(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"daemon": "off", "daemon_idle_timeout": 30}))
    argv = ["--config-file", str(cfg)]
    env = {"LENS_DAEMON": "on", "LENS_DAEMON_IDLE_TIMEOUT": "99"}
    assert client.resolve_mode(argv, env) == ("off", 30)  # config beats env
    assert client.resolve_mode(argv + ["--daemon", "on"], env) == ("on", 30)
    assert (
        client.resolve_mode(["--daemon=auto", "--config-file", str(cfg)], env)[0]
        == "auto"
    )
    assert client.resolve_mode([], env) == ("on", 99)  # env when nothing else


def test_mode_accepts_booleans_in_the_config_file(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"daemon": false}')
    assert client.resolve_mode(["--config-file", str(cfg)], {})[0] == "off"


@pytest.mark.parametrize(
    "argv,env",
    [(["--daemon", "sometimes"], {}), ([], {"LENS_DAEMON": "maybe"})],
)
def test_an_unusable_mode_means_off_so_the_cli_reports_it(argv, env):
    assert client.resolve_mode(argv, env)[0] == "off"


def test_an_unusable_config_file_is_left_for_the_cli_to_report(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text("{broken")
    assert client.resolve_mode(["--config-file", str(cfg)], {}) == ("auto", 600)


@pytest.mark.parametrize(
    "argv",
    [
        ["--serve"],
        ["--setup-sharex", "-t", "ru"],
        ["--update-config", "--timeout", "5"],
        ["--version"],
        ["-V"],
        ["--help"],
        ["-h"],
        ["--install-service"],
        ["--uninstall-service"],
        ["--ser"],  # an abbreviation argparse would accept
        ["img.png", "--setup-sh"],
    ],
)
def test_commands_that_must_run_locally_are_recognised(argv):
    assert client._is_local_only(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["img.png"],
        ["img.png", "-t", "ru", "--sharex"],
        ["--region", "0.5,0.5,1,1", "a"],
    ],
)
def test_ordinary_requests_are_forwarded(argv):
    assert not client._is_local_only(argv)


# --------------------------------------------------------- forwarding + fallback


def run_remote(argv=("img.png",)):
    return client.try_remote(list(argv))


def test_a_running_daemon_answers_and_its_output_is_written_verbatim(fake, capsys):
    def behave(req):
        return http_reply(
            200, {"exit_code": 2, "stdout": "héllo ✓\n", "stderr": "warn\n"}
        )

    d = fake(behave=behave)
    d.publish()
    assert run_remote(["a.png", "-t", "ru"]) == 2
    out, err = capsys.readouterr()
    assert out == "héllo ✓\n" and err == "warn\n"

    head, body = d.requests[0]
    assert head.startswith(b"POST /v1/cli HTTP/1.1")
    assert f"Authorization: Bearer {d.token}".encode() in head
    sent = json.loads(body)
    assert sent["argv"] == ["a.png", "-t", "ru"]
    assert sent["cwd"] == os.getcwd()
    assert set(sent) >= {"stdin_is_tty", "stdout_is_tty", "stderr_is_tty", "env"}


def test_interleaved_output_is_replayed_in_order(fake, capfd):
    events = [["err", "header\n"], ["out", "text\n"], ["err", "footer\n"]]
    d = fake(
        behave=lambda r: http_reply(
            200,
            {
                "exit_code": 0,
                "stdout": "text\n",
                "stderr": "header\nfooter\n",
                "events": events,
            },
        )
    )
    d.publish()
    assert run_remote() == 0
    out, err = capfd.readouterr()
    assert out == "text\n" and err == "header\nfooter\n"


def test_only_lens_settings_and_a_few_render_variables_are_forwarded(fake, monkeypatch):
    monkeypatch.setenv("LENS_API_KEY", "k")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://secret@proxy")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    d = fake()
    d.publish()
    run_remote()
    env = json.loads(d.requests[0][1])["env"]
    assert env["LENS_API_KEY"] == "k" and env["NO_COLOR"] == "1"
    assert "HTTPS_PROXY" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert "LENS_STATE_DIR" not in env


def test_mode_off_never_touches_the_daemon(fake, state):
    d = fake()
    d.publish()
    assert run_remote(["img.png", "--daemon", "off"]) is None
    assert d.requests == [] and state.spawned == []


def test_local_only_commands_never_touch_the_daemon(fake, state):
    d = fake()
    d.publish()
    assert run_remote(["--setup-sharex"]) is None
    assert d.requests == [] and state.spawned == []


def test_no_daemon_runs_locally_and_auto_starts_one_for_next_time(state):
    assert run_remote() is None
    assert state.spawned and state.spawned[0][:2] == ["--serve", "--auto"]


def test_a_second_call_while_the_first_is_still_starting_does_not_spawn_again(state):
    run_remote()
    run_remote()
    assert len(state.spawned) == 1


def test_a_stale_file_is_cleaned_up_and_the_call_falls_back(state):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    d = FakeDaemon()
    d.publish(pid=gone.pid)
    d.close()  # the port now refuses
    time.sleep(0.2)
    assert run_remote() is None
    assert runtime.read_daemon() is None
    assert state.spawned


@pytest.mark.skipif(not POSIX, reason="Windows checks liveness by connecting")
def test_a_dead_pid_is_noticed_before_connecting(fake, state):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    d = fake()
    d.publish(pid=gone.pid)
    assert run_remote() is None
    assert d.requests == []
    assert runtime.read_daemon() is None


def test_a_daemon_of_another_version_is_asked_to_exit_and_not_used(fake, state):
    seen = []

    def behave(req):
        seen.append(req.split(b"\r\n", 1)[0])
        if req.startswith(b"POST /v1/shutdown"):
            runtime.remove_daemon_file()  # what a real daemon does on its way out
            return http_reply(200, {"ok": True})
        return http_reply(200, {"exit_code": 0, "stdout": "old\n", "stderr": ""})

    d = fake(behave=behave)
    d.publish(version="0.0.1")
    assert run_remote() is None
    assert seen == [b"POST /v1/shutdown HTTP/1.1"]
    assert state.spawned  # and a fresh one is started


@pytest.mark.parametrize(
    "reply",
    [
        b"",  # closed without a word (the daemon died mid-request)
        b"garbage",
        b"HTTP/1.1 200 OK\r\n\r\nnot json",
        http_reply(raw=b"[1, 2]"),
        http_reply(payload={"exit_code": "0", "stdout": "", "stderr": ""}),
        http_reply(payload={"exit_code": 0, "stdout": 5, "stderr": ""}),
        http_reply(payload={"exit_code": True, "stdout": "", "stderr": ""}),
        http_reply(
            payload={
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "events": [["fd9", "x"]],
            }
        ),
        http_reply(500, {"error": "boom"}),
        http_reply(401, {"error": "token"}),
        # Content-Length promises more than arrives.
        b"HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n{}",
    ],
)
def test_a_bad_reply_falls_back_without_writing_anything(fake, capsys, reply):
    d = fake(behave=lambda req: reply or None)
    d.publish()
    assert run_remote() is None
    assert capsys.readouterr() == ("", "")


def test_a_daemon_that_never_answers_times_out_into_a_local_run(fake, monkeypatch):
    monkeypatch.setattr(client, "READ_TIMEOUT", 0.3)
    d = fake(hang=True)
    d.publish()
    started = time.monotonic()
    assert run_remote() is None
    assert time.monotonic() - started < 3


def test_a_decline_from_a_live_daemon_does_not_start_another(fake, state):
    d = fake(behave=lambda r: http_reply(500, {"error": "boom"}))
    d.publish()
    assert run_remote() is None
    assert state.spawned == []


def test_the_daemon_can_ask_for_a_local_run(fake, state):
    d = fake(behave=lambda r: http_reply(200, {"run_locally": "usage error"}))
    d.publish()
    assert run_remote() is None
    assert state.spawned == []


def test_mode_on_waits_for_a_daemon_that_is_starting(fake, monkeypatch, state):
    d = fake()

    def spawn(args):
        threading.Timer(0.3, d.publish).start()  # it "finishes booting" later
        return True

    monkeypatch.setattr(runtime, "spawn_detached", spawn)
    assert run_remote(["img.png", "--daemon", "on"]) == 0
    assert d.requests


def test_mode_on_gives_up_after_the_wait_and_runs_locally(monkeypatch, state):
    monkeypatch.setattr(client, "START_WAIT_SECONDS", 0.3)
    assert run_remote(["img.png", "--daemon", "on"]) is None


def test_the_client_never_raises_whatever_goes_wrong(monkeypatch, fake):
    d = fake()
    d.publish()
    monkeypatch.setattr(client, "_forward", lambda *a: 1 / 0)
    assert run_remote() is None


# ------------------------------------------------------------------ management


def test_status_of_a_running_daemon_and_of_none(fake, capsys):
    assert client.daemon_status() == 1
    assert "not running" in capsys.readouterr().out

    status = {
        "pid": 4242,
        "version": __version__,
        "uptime": 125,
        "requests": 7,
        "idle_timeout": 600,
        "idle_remaining": 480,
    }
    d = fake(behave=lambda r: http_reply(200, status))
    d.publish()
    assert client.daemon_status() == 0
    out = capsys.readouterr().out
    assert "4242" in out and "2m 05s" in out and "7" in out and "8m 00s" in out


def test_stop_asks_the_daemon_and_waits_until_it_is_gone(fake, capsys):
    def behave(req):
        if req.startswith(b"POST /v1/shutdown"):
            runtime.remove_daemon_file()
        return http_reply(200, {"ok": True})

    d = fake(behave=behave)
    d.publish()
    assert client.daemon_stop() == 0
    assert "stopped" in capsys.readouterr().out
    assert client.daemon_stop() == 0  # nothing running is not an error


def test_manage_dispatches_on_the_flag(fake, capsys):
    assert client.legacy_manage(["img.png"]) is None
    assert client.legacy_manage(["--daemon-status"]) == 1
    assert client.legacy_manage(["--daemon-stop", "--daemon-status"]) == 1
    assert "cannot be used together" in capsys.readouterr().err


# ---------------------------------------------------------------- entry point


def test_entry_falls_through_to_the_real_cli(monkeypatch):
    ran = []
    import chrome_lens_py.cli.main as cli

    monkeypatch.setattr(cli, "run", lambda: ran.append(True))
    client.entry(["img.png", "--daemon", "off"])
    assert ran == [True]


def test_entry_exits_with_the_daemons_exit_code(fake, monkeypatch):
    d = fake(
        behave=lambda r: http_reply(200, {"exit_code": 2, "stdout": "", "stderr": ""})
    )
    d.publish()
    with pytest.raises(SystemExit) as stop:
        client.entry(["img.png"])
    assert stop.value.code == 2


def test_daemon_env_makes_the_package_importable_from_any_cwd(monkeypatch):
    # The daemon starts in the home directory. A relative PYTHONPATH entry (or
    # a source checkout) that only worked from the caller's cwd left it with
    # "No module named chrome_lens_py", so it silently never came up.
    import os

    import chrome_lens_py
    from chrome_lens_py import runtime

    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["src", "other/rel"]))
    entries = runtime.daemon_env()["PYTHONPATH"].split(os.pathsep)

    package_root = os.path.dirname(
        os.path.dirname(os.path.abspath(chrome_lens_py.__file__))
    )
    assert entries[0] == package_root
    assert all(os.path.isabs(e) for e in entries)
    assert os.path.abspath("other/rel") in entries


# ------------------------------------------ Windows venv launcher, skipped


def _fake_venv(monkeypatch, tmp_path, launcher_name="python.exe"):
    base_dir = tmp_path / "base"
    venv_dir = tmp_path / "venv" / "Scripts"
    base_dir.mkdir(parents=True)
    venv_dir.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (base_dir / name).write_bytes(b"")
        (venv_dir / name).write_bytes(b"")
    monkeypatch.setattr(runtime, "_IS_WINDOWS", True)
    monkeypatch.setattr(runtime, "is_compiled", lambda: False)
    monkeypatch.setattr(runtime, "_isolated", lambda: False)
    monkeypatch.setattr(runtime.sys, "executable", str(venv_dir / launcher_name))
    monkeypatch.setattr(
        runtime.sys, "_base_executable", str(base_dir / "python.exe"), raising=False
    )
    monkeypatch.setattr(runtime.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(runtime.sys, "base_prefix", str(base_dir))
    return base_dir, venv_dir


def test_spawns_skip_the_venv_launcher(monkeypatch, tmp_path):
    # Each daemon used to appear twice in Task Manager: the venv's launcher
    # waiting on the real interpreter it had started.
    base_dir, venv_dir = _fake_venv(monkeypatch, tmp_path)
    cmd = runtime.daemon_command(["--serve"])
    assert cmd[0] == str(base_dir / "python.exe")
    env = runtime.daemon_env()
    assert env[runtime.VENV_LAUNCHER_ENV] == str(venv_dir / "python.exe")
    assert env[runtime.DIRECT_ENV] == "1"


def test_pythonw_stays_pythonw(monkeypatch, tmp_path):
    base_dir, _ = _fake_venv(monkeypatch, tmp_path, "pythonw.exe")
    assert runtime.daemon_command(["--serve"])[0] == str(base_dir / "pythonw.exe")


def test_no_redirect_outside_a_venv_or_off_windows(monkeypatch, tmp_path):
    _fake_venv(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime.sys, "base_prefix", runtime.sys.prefix)
    assert runtime.venv_redirect() is None
    _fake_venv(monkeypatch, tmp_path / "again")
    monkeypatch.setattr(runtime, "_IS_WINDOWS", False)
    assert runtime.venv_redirect() is None


def test_a_launcher_started_supervisor_respawns_itself_once(monkeypatch, tmp_path):
    _fake_venv(monkeypatch, tmp_path)
    monkeypatch.delenv(runtime.DIRECT_ENV, raising=False)
    assert runtime.should_respawn_direct()
    spawned = []
    monkeypatch.setattr(runtime, "spawn_detached", lambda a: spawned.append(a) or True)
    monkeypatch.setattr(
        runtime, "supervise", lambda: pytest.fail("ran under the launcher")
    )
    with pytest.raises(SystemExit) as done:
        client.entry([runtime.SUPERVISE_FLAG])
    assert done.value.code == 0 and spawned == [[runtime.SUPERVISE_FLAG]]

    # The direct child carries the marker and supervises instead.
    monkeypatch.setenv(runtime.DIRECT_ENV, "1")
    assert not runtime.should_respawn_direct()
