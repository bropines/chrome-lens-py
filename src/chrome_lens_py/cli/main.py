import argparse
import asyncio
import contextvars
import inspect
import io
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    TextIO,
    Tuple,
)

from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .. import __version__, formats
from ..api import LensAPI
from ..constants import DEFAULT_CONFIG_FILENAME
from ..exceptions import LensConfigError, LensException, LensImageError
from ..utils.config_manager import (
    SECRET_FIELDS,
    Settings,
    default_value,
    get_default_config_dir,
    resolve_settings,
    update_config_file_from_cli,
)
from ..utils.general import is_image_file_supported, is_url
from ..utils.sharex import copy_to_clipboard
from ..utils.sharex_setup import setup_sharex, setup_sharex_config

logger = logging.getLogger(__name__)

# Exit codes.
#
#   0   everything asked for happened (even if the image held no text)
#   1   it all failed: one image that failed, or a command that could not run
#   2   a batch where some images worked and some did not
#   64  the command line was wrong (sysexits.h's EX_USAGE)
#   130 interrupted
#
# 64 rather than argparse's own 2: a caller that sees 2 should know that the
# work started and partly succeeded, not have to guess whether it was a typo.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_USAGE = 64

CONCURRENCY_WARNING_THRESHOLD = 20

# `console` carries output that is the point of the command (--version, --help).
# `err_console` carries everything decorative or diagnostic, so stdout holds
# only result data and can be piped or redirected without cleaning it first.
console = Console()
err_console = Console(stderr=True)

ApiProvider = Callable[[Settings, Mapping[str, str]], Awaitable[Any]]


class RunLocally(Exception):
    """Raised inside the daemon for a command it must not run itself.

    The client then runs it in its own process, so --help, argparse errors and
    anything that touches the machine behave exactly as without a daemon.
    """


@dataclass
class CliContext:
    """Where one CLI run writes, and what it resolves against.

    Absent for an ordinary process, where stdout/stderr and the working
    directory are the real ones. Inside the daemon each forwarded request gets
    its own, held in a ContextVar so concurrent requests cannot see each
    other's streams (asyncio tasks inherit the context they are created in).
    """

    out: TextIO
    err: TextIO
    err_console: Console
    cwd: str
    env: Mapping[str, str] = field(default_factory=dict)
    api_provider: Optional[ApiProvider] = None
    log_level: int = logging.WARNING


_CONTEXT: "contextvars.ContextVar[Optional[CliContext]]" = contextvars.ContextVar(
    "lens_cli_context", default=None
)


def current_context() -> Optional[CliContext]:
    return _CONTEXT.get()


def real_path(path: str) -> str:
    """`path` as the filesystem should see it.

    Inside the daemon a relative path means "relative to the client's working
    directory", not the daemon's. Names shown to the user (and echoed in
    --oneline/json records) stay as typed; only the open()/stat() calls use
    this. URLs pass through.
    """
    ctx = _CONTEXT.get()
    if ctx is None or not path or is_url(path):
        return path
    return os.path.join(ctx.cwd, path)


def _stdout() -> TextIO:
    ctx = _CONTEXT.get()
    return ctx.out if ctx is not None else sys.stdout


def _stderr_console() -> Console:
    ctx = _CONTEXT.get()
    return ctx.err_console if ctx is not None else err_console


# ------------------------------------------------------------------- output


def emit(text: str = "") -> None:
    """Write result data to stdout exactly as given.

    Never goes through rich: rich wraps at the terminal width (80 columns when
    piped) and reads "[...]" as markup, either of which corrupts JSON and OCR
    text.
    """
    out = _stdout()
    out.write(text + "\n")
    out.flush()


def write_stdout(text: str) -> None:
    out = _stdout()
    out.write(text)
    out.flush()


def note(markup: str) -> None:
    """Decorative / informational message (stderr). Callers escape any data."""
    _stderr_console().print(markup)


def fail(message: str, label: str = "Error") -> None:
    """An error message (stderr). The text is data and is never parsed as markup."""
    _stderr_console().print(
        Text.assemble((f"{label}: ", "bold red"), message), soft_wrap=True
    )


def setup_logging(level_str: str = "WARNING"):
    log_level = getattr(logging, level_str.upper(), logging.WARNING)
    log_format = (
        "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        if log_level <= logging.DEBUG
        else "%(message)s"
    )
    # force=True: if anything logged before this point, the root logger already
    # has a handler and a plain basicConfig would silently do nothing, which is
    # how `-l DEBUG` used to have no effect.
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            RichHandler(
                # Logs go to stderr so that piping stdout (ShareX, shell
                # redirection) yields only the actual result text.
                console=Console(stderr=True),
                show_time=False,
                show_level=log_level <= logging.INFO,
                show_path=log_level <= logging.DEBUG,
                # Log messages carry URLs, paths and server replies; "[x]" in
                # them must not be read as markup.
                markup=False,
                rich_tracebacks=True,
            )
        ],
        force=True,
    )
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.debug("Logging level set to %s", level_str.upper())


def print_version():
    """Report the version and, just as usefully, which copy is running.

    With a pip install, a uv tool install, an editable checkout and a
    standalone build all able to own the name `lens_scan`, "which one did I
    just run?" is a real question. Printing the paths answers it on the spot.
    """
    console.print(f"[bold cyan]chrome-lens-py[/bold cyan] {__version__}")

    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        flavour = "standalone build"
    elif any(part == "site-packages" for part in Path(__file__).parts):
        flavour = "installed package"
    else:
        flavour = "source checkout (editable or run in place)"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="green")
    table.add_column(overflow="fold")
    table.add_row("Running from", flavour)
    table.add_row("Executable", sys.executable)
    table.add_row("Package", str(Path(__file__).resolve().parent.parent))
    table.add_row("Python", sys.version.split()[0])

    # Reported because --sharex fails quietly without it, and every frozen
    # binary we shipped up to 3.5.2 was built without it - so ShareX copied
    # nothing and said nothing. Also what CI asserts on, to stop that
    # recurring.
    try:
        import pyperclip  # noqa: F401

        clipboard = "available"
    except ImportError:
        clipboard = (
            "not installed (--sharex will not work; "
            "pip install 'chrome-lens-py\\[clipboard]')"
        )
    table.add_row("Clipboard", clipboard)
    console.print(table)


# ------------------------------------------------------------------- parser


class _HelpFormatter(argparse.HelpFormatter):
    """argparse's formatter with room for our long option names."""

    def __init__(self, prog: str):
        width = max(shutil.get_terminal_size((100, 24)).columns - 2, 60)
        super().__init__(prog, max_help_position=36, width=min(width, 110))


def _default_text(name: str) -> str:
    return f" (default: {default_value(name)})"


class _Parser(argparse.ArgumentParser):
    """argparse, with a usage error that exits 64 and points at the short help.

    argparse's own 2 is this CLI's "some images failed", and the full option
    list is sixty lines - neither is what someone who typed `--fromat json`
    needs to see.
    """

    def error(self, message: str):  # type: ignore[override]
        self.exit(
            EXIT_USAGE,
            f"lens_scan: {message}\nTry `lens_scan -h`, or `lens_scan help options` "
            "for every option.\n",
        )


class _NoExitParser(argparse.ArgumentParser):
    """Parser for the daemon: a usage error must not print to its stderr or exit.

    The client re-runs the command line locally instead, so the user sees
    argparse's own message in their own terminal.
    """

    def error(self, message: str):  # type: ignore[override]
        raise RunLocally(f"usage error: {message}")

    def exit(self, status: int = 0, message: Optional[str] = None):  # type: ignore[override]
        raise RunLocally("argparse exit")


def build_parser(
    parser_class: type = _Parser,
) -> argparse.ArgumentParser:
    """The one description of the command line; --help is generated from it.

    Options that map to a persistent setting are declared with
    ``default=SUPPRESS``. A flag the user did not type is then absent from the
    parsed namespace, which is what lets the config file and LENS_* variables
    take effect instead of being overridden by a hard-coded default.
    """
    parser = parser_class(
        prog="lens_scan",
        usage="lens_scan <image_source> [ocr_lang] [options]\n"
        "       lens_scan <command> [options]   (status, daemon, service, "
        "sharex, update, config, serve)",
        description="Performs OCR and optional translation on an image with Google Lens.",
        add_help=False,
        formatter_class=_HelpFormatter,
    )
    SUPPRESS = argparse.SUPPRESS

    def setting(group, *flags, **kwargs):
        kwargs.setdefault("default", SUPPRESS)
        return group.add_argument(*flags, **kwargs)

    # Positional
    g = parser.add_argument_group("Arguments")
    g.add_argument(
        "image_source",
        nargs="?",
        help="Path to an image file, a URL, or a directory.",
    )
    g.add_argument(
        "ocr_lang",
        nargs="?",
        default=None,
        help="BCP 47 language code for OCR (e.g. 'en', 'ja'). "
        "Auto-detected if omitted.",
    )

    g = parser.add_argument_group("Translation")
    setting(
        g,
        "-t",
        "--translate",
        dest="target_lang",
        metavar="TARGET_LANG",
        help="Target language for translation (e.g. 'en', 'ru').",
    )
    g.add_argument(
        "--translate-from",
        dest="source_lang",
        metavar="SOURCE_LANG",
        help="Source language for translation (auto-detected if omitted).",
    )
    g.add_argument(
        "-to",
        "--translate-out",
        dest="output_overlay_path",
        metavar="FILE_PATH",
        help="Save the image with the translated text overlaid.",
    )

    g = parser.add_argument_group("Output")
    g.add_argument(
        "--format",
        choices=formats.FORMATS,
        default="text",
        dest="output_format",
        help="Output format: text (default), json, jsonl (one object per image), "
        "hocr (XHTML) or tsv (tesseract-style). Not combinable with "
        "-b/-ol/--get-coords/--oneline.",
    )
    g.add_argument(
        "--oneline",
        action="store_true",
        help='Print each result as one compact JSON line: {"file", "ocr_text", '
        '"translated_text", "error"}. Compatible with the Chrome-Lens-OCR fork.',
    )
    g.add_argument(
        "-b",
        "--output-blocks",
        action="store_true",
        help="Output OCR text as segmented blocks (useful for comics).",
    )
    g.add_argument(
        "-ol",
        "--output-lines",
        action="store_true",
        help="Output OCR text as individual lines.",
    )
    g.add_argument(
        "--get-coords",
        action="store_true",
        help="Output recognized words with their coordinates as JSON.",
    )
    setting(
        g,
        "--ocr-single-line",
        action="store_false",
        dest="ocr_preserve_line_breaks",
        help="Join all OCR text into a single line (line breaks are kept by default).",
    )
    g.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational messages; print only result data.",
    )
    g.add_argument(
        "-sx",
        "--sharex",
        action="store_true",
        help="Copy the result (translation or OCR) to the clipboard.",
    )
    g.add_argument(
        "--region",
        metavar="CX,CY,W,H",
        help="Re-read one region at native resolution (values normalized 0..1).",
    )
    g.add_argument(
        "--text-query",
        metavar="TEXT",
        help="Text to send alongside --region.",
    )

    g = parser.add_argument_group("Overlay rendering (with --translate-out)")
    setting(
        g,
        "--overlay-mode",
        choices=["chromium", "legacy"],
        metavar="MODE",
        help="'chromium' repaints each line in place using the server's inpainted "
        "background; 'legacy' is the old white-box overlay"
        + _default_text("overlay_mode")
        + ".",
    )
    setting(
        g,
        "--vertical-text",
        choices=["keep", "auto", "horizontal"],
        metavar="MODE",
        help="Top-to-bottom source text: 'auto' keeps it vertical only when "
        "translating into a CJK language, 'keep' always renders vertically, "
        "'horizontal' always reflows" + _default_text("vertical_text") + ".",
    )
    setting(
        g,
        "--erase-mode",
        choices=["patch", "hull"],
        metavar="MODE",
        help="How to remove the source text: 'patch' uses the server's "
        "inpainting, 'hull' covers the whole text area with its background "
        "colour" + _default_text("erase_mode") + ".",
    )
    setting(
        g,
        "--hull-padding",
        type=float,
        metavar="N",
        help="How far the hull reaches past the text, in line heights"
        + _default_text("hull_padding")
        + ".",
    )
    setting(
        g,
        "--outline",
        dest="outline_scale",
        type=float,
        metavar="N",
        help="Multiplier on the outline behind translated text; 0 removes it"
        + _default_text("outline_scale")
        + ".",
    )
    setting(
        g,
        "--min-text-size",
        dest="min_readable_px",
        type=float,
        metavar="PX",
        help="Enlarge text that would render smaller than this many pixels"
        + _default_text("min_readable_px")
        + ".",
    )
    setting(
        g,
        "--text-align",
        choices=["auto", "left", "center", "right"],
        metavar="SIDE",
        help="auto (follow the source), left, center or right"
        + _default_text("text_align")
        + ".",
    )
    setting(
        g,
        "--manga",
        dest="manga_mode",
        action="store_true",
        help="Preset for vertical Japanese: always reflow, lay out wider than the "
        "detected box, erase by hull, bigger minimum size.",
    )
    setting(
        g,
        "--manga-growth",
        dest="manga_box_growth",
        type=float,
        metavar="N",
        help="How much wider than the detected box to lay out in manga mode"
        + _default_text("manga_box_growth")
        + ".",
    )
    setting(
        g,
        "--font",
        dest="font_path",
        metavar="FONT_PATH",
        help="Path to a .ttf font file for the overlay.",
    )
    setting(
        g,
        "--font-size",
        type=int,
        metavar="SIZE",
        help="Font size for the overlay (default: 20).",
    )

    g = parser.add_argument_group("Daemon / fast mode")
    setting(
        g,
        "--daemon",
        choices=["auto", "on", "off"],
        metavar="MODE",
        help="Use a warm background daemon for speed: auto = use it if running "
        "and start one for next time, on = wait for it, off = never"
        + _default_text("daemon")
        + ".",
    )
    setting(
        g,
        "--daemon-idle-timeout",
        dest="daemon_idle_timeout",
        type=int,
        metavar="SECONDS",
        help="An automatically started daemon exits after this long without "
        "requests; 0 = never" + _default_text("daemon_idle_timeout") + ".",
    )
    g = parser.add_argument_group("Server (foreground)")
    g.add_argument(
        "--serve",
        action="store_true",
        help="Run as a local HTTP server instead of processing one image.",
    )
    g.add_argument(
        "--auto",
        action="store_true",
        help="With --serve: run as the managed daemon (private socket or "
        "ephemeral port, random token, idle exit). This is what --daemon-start "
        "runs.",
    )
    g.add_argument(
        "--service",
        action="store_true",
        help="With --serve: run as the persistent daemon on --port with the "
        "token from --setup-sharex --mode uploader. No idle exit.",
    )
    g.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="ADDR",
        help="Address to bind (default: 127.0.0.1).",
    )
    setting(
        g,
        "--port",
        dest="daemon_port",
        type=int,
        metavar="N",
        help="Port to bind" + _default_text("daemon_port") + ".",
    )
    g.add_argument(
        "--token",
        help="Require this bearer token. Mandatory when --host is not loopback.",
    )
    g.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="Let one browser origin call the daemon (repeatable). None by "
        "default, so no web page can reach it.",
    )

    g = parser.add_argument_group("Connection")
    setting(g, "--api-key", metavar="KEY", help="Google Cloud API key.")
    setting(
        g,
        "--proxy",
        metavar="URL",
        help="Proxy server URL (e.g. http://user:pass@host:port, socks5://host:port).",
    )
    setting(
        g,
        "--no-env-proxy",
        dest="trust_env",
        action="store_false",
        help="Ignore HTTP_PROXY/HTTPS_PROXY/ALL_PROXY from the environment and "
        "connect directly.",
    )
    setting(
        g,
        "--timeout",
        type=int,
        metavar="SECONDS",
        help="Request timeout in seconds" + _default_text("timeout") + ".",
    )
    setting(
        g,
        "--retries",
        type=int,
        metavar="N",
        help="Retries after a network error or a retryable HTTP status"
        + _default_text("retries")
        + ".",
    )
    setting(
        g,
        "--concurrency",
        type=int,
        metavar="N",
        help="Maximum number of concurrent requests"
        + _default_text("concurrency")
        + ", at most 30.",
    )
    setting(
        g,
        "--client-region",
        metavar="REGION",
        help="Client region code" + _default_text("client_region") + ".",
    )
    setting(
        g,
        "--client-time-zone",
        metavar="TZ",
        help="Client time zone ID" + _default_text("client_time_zone") + ".",
    )

    g = parser.add_argument_group("Configuration and setup")
    g.add_argument(
        "--config-file",
        dest="config_file_path_override",
        metavar="FILE_PATH",
        help="Path to a custom JSON configuration file.",
    )
    g.add_argument(
        "--update-config",
        action="store_true",
        help="Save the settings given on this command line into the default "
        "config file (never the API key).",
    )
    g.add_argument(
        "--show-config",
        action="store_true",
        help="Print every setting, its value and where that value came from "
        "(what `lens_scan config show` runs).",
    )
    g.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="With --show-config: print it as JSON.",
    )
    setting(
        g,
        "-l",
        "--logging-level",
        metavar="LEVEL",
        help="Logging level: DEBUG, INFO, WARNING, ERROR"
        + _default_text("logging_level")
        + ".",
    )
    g.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show the version and which copy of it is running.",
    )
    g.add_argument(
        "-h", "--help", action="store_true", help="Show this help message and exit."
    )

    # The commands replaced these in 3.8. They keep working - ShareX
    # configurations, Startup shortcuts, LaunchAgents and systemd units on
    # people's machines were written with them, and so were scripts.
    g = parser.add_argument_group("Older flags (the commands above replaced these)")
    g.add_argument(
        "--daemon-status",
        action="store_true",
        help="Now `lens_scan daemon status`.",
    )
    g.add_argument(
        "--daemon-start",
        action="store_true",
        help="Now `lens_scan daemon start`.",
    )
    g.add_argument(
        "--daemon-stop", action="store_true", help="Now `lens_scan daemon stop`."
    )
    g.add_argument(
        "--install-service",
        action="store_true",
        help="Now `lens_scan service install`.",
    )
    g.add_argument(
        "--uninstall-service",
        action="store_true",
        help="Now `lens_scan service uninstall`.",
    )
    g.add_argument(
        "--setup-sharex",
        action="store_true",
        help="Now `lens_scan sharex`.",
    )
    g.add_argument(
        "--mode",
        choices=["program", "uploader", "both"],
        default="program",
        help="With --setup-sharex / `lens_scan sharex`: program = Ctrl+O runs "
        "lens_scan per capture (default, works with nothing running); uploader = "
        "Ctrl+Shift+O posts the capture straight to an always-on daemon, no "
        "process per capture; both = both hotkeys. uploader/both install the "
        "daemon as a login service.",
    )
    return parser


def print_help(parser: Optional[argparse.ArgumentParser] = None, file=None) -> None:
    """Render the full option reference from the parser, so it cannot drift.

    This is `lens_scan help options`. The front door is the short help in
    chrome_lens_py/manage.py, which lists the commands and the dozen options
    most people need; everything below is the reference behind it.
    """
    parser = parser or build_parser()
    file = file or sys.stdout
    header = Console(file=file)
    header.print("\n[bold cyan]Google Lens CLI (chrome-lens-py)[/bold cyan]")
    file.write(parser.format_help())
    file.write(
        "\nCommands: status, daemon, service, sharex, update, config, serve, "
        "version, help.\n"
        "  lens_scan status            is the daemon up, the service installed, "
        "ShareX wired?\n"
        "  lens_scan help <command>    what one command does\n"
        "\nEnvironment: any setting can also be given as LENS_<NAME> "
        "(LENS_API_KEY, LENS_PROXY, LENS_TIMEOUT, ...).\n"
        "Precedence: command line > config file > environment > defaults.\n"
        "Exit codes: 0 all images processed, 1 all failed, 2 some failed, "
        "64 wrong command line, 130 interrupted.\n"
    )
    file.flush()


def print_resolved_config(settings: Settings, path: str, as_json: bool) -> int:
    """Every setting, its value, and which layer decided it.

    The layers (command line > config file > LENS_* > default) are the first
    thing to check when a setting "does not work": usually it does, and
    something further up is overriding it.
    """
    from ..utils.config_manager import SETTING_NAMES

    rows = []
    for name in SETTING_NAMES:
        value = getattr(settings, name)
        rows.append(
            (
                name,
                "<hidden>" if name in SECRET_FIELDS and value else value,
                settings.sources.get(name, "default"),
            )
        )
    if as_json:
        emit(
            json.dumps(
                {
                    "config_file": path,
                    "config_file_exists": os.path.isfile(path),
                    "settings": {
                        name: {"value": value, "source": source}
                        for name, value, source in rows
                    },
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        return EXIT_OK

    console.print(
        f"Config file: [cyan]{escape(path)}[/cyan]"
        + ("" if os.path.isfile(path) else "  [dim](no file yet)[/dim]")
    )
    table = Table(box=None, pad_edge=False, padding=(0, 2))
    table.add_column("setting", style="green")
    table.add_column("value", overflow="fold")
    table.add_column("from", style="dim")
    for name, value, source in rows:
        table.add_row(name, escape(str(value)), source)
    _stderr_console().print(table)
    note(
        "\n[dim]Precedence: command line > config file > LENS_* environment > "
        "default. Write the current command line into the file with "
        "--update-config.[/dim]"
    )
    return EXIT_OK


# ---------------------------------------------------------------- processing


def api_cache_key(settings: Settings, env: Mapping[str, str]) -> Tuple[Any, ...]:
    """Everything that decides how a LensAPI is *constructed*.

    A daemon keeps one LensAPI (and so one pooled HTTP/2 connection) per key.
    Overlay-rendering options are per call, not per instance, so they stay out.
    """
    kwargs = _api_kwargs(settings)
    return (
        tuple(sorted((k, repr(v)) for k, v in kwargs.items())),
        settings.retries,  # not always in kwargs: see _api_kwargs
        env.get("LENS_ENDPOINT", ""),
    )


def _api_kwargs(settings: Settings) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(
        api_key=settings.api_key,
        client_region=settings.client_region,
        client_time_zone=settings.client_time_zone,
        proxy=settings.proxy,
        timeout=settings.timeout,
        font_path=settings.font_path,
        font_size=settings.font_size,
        max_concurrent=settings.concurrency,
        trust_env=settings.trust_env,
    )
    # LensAPI grew no retry parameter yet. Pass ours only once it has one, so
    # --retries starts working the day core accepts `max_retries`.
    try:
        if "max_retries" in inspect.signature(LensAPI.__init__).parameters:
            kwargs["max_retries"] = settings.retries
    except (TypeError, ValueError):
        pass
    return kwargs


def _render_kwargs(settings: Settings) -> Dict[str, Any]:
    return dict(
        overlay_mode=settings.overlay_mode,
        vertical_text=settings.vertical_text,
        erase_mode=settings.erase_mode,
        hull_padding=settings.hull_padding,
        outline_scale=settings.outline_scale,
        min_readable_px=settings.min_readable_px,
        text_align=settings.text_align,
        manga_mode=settings.manga_mode,
        manga_box_growth=settings.manga_box_growth,
    )


def _exit_code(failed: int, total: int) -> int:
    if failed == 0:
        return EXIT_OK
    return EXIT_FAILED if failed >= total else EXIT_PARTIAL


def _coords_json(result: Dict[str, Any]) -> str:
    word_data = result.get("word_data")
    if not word_data:
        return "[]"
    processed = []
    for data in word_data:
        geom = data.get("geometry")
        processed.append(
            {
                data["word"]: (
                    {
                        "center_x": round(geom["center_x"], 4),
                        "center_y": round(geom["center_y"], 4),
                        "width": round(geom["width"], 4),
                        "height": round(geom["height"], 4),
                        "angle_deg": round(geom["angle_deg"], 2),
                    }
                    if geom
                    else None
                )
            }
        )
    return json.dumps(processed, indent=2, ensure_ascii=False)


async def _image_size(api: Any, source: str) -> Optional[Tuple[int, int]]:
    """Pixel size of the image as Lens saw it (it reports geometry normalized)."""
    try:
        if not is_url(source):
            from PIL import Image

            with Image.open(real_path(source)) as image:
                return image.size

        from ..core.image_processor import prepare_image_for_api

        client = await api.request_handler.get_client()
        _, _, _, original = await prepare_image_for_api(
            source, client=client, keep_original=True
        )
        return original.size if original is not None else None
    except Exception as e:
        logger.debug("Could not determine the size of %s: %s", source, e)
        return None


def _text_to_copy(
    result: Dict[str, Any], settings: Settings, blocks_mode: bool
) -> Tuple[str, str]:
    translated = result.get("translated_text")
    if settings.target_lang and translated:
        return translated, "Translated text"
    if blocks_mode:
        blocks = result.get("text_blocks", [])
        if blocks:
            return "\n\n".join(b.get("text", "") for b in blocks), "OCR text (blocks)"
        return "", ""
    text = formats.ocr_text(result, settings.ocr_preserve_line_breaks)
    return (text, "OCR text") if text else ("", "")


def _print_text_result(
    result: Dict[str, Any], args: argparse.Namespace, settings: Settings
) -> None:
    quiet = args.quiet
    if args.output_lines:
        line_blocks = result.get("line_blocks", [])
        if not quiet:
            note(f"\n[bold green]OCR Results ({len(line_blocks)} lines):[/bold green]")
            if not line_blocks:
                note("No lines found.")
        for j, line in enumerate(line_blocks):
            if not quiet:
                note(f"\n--- [cyan]Line #{j + 1}[/cyan] ---")
            emit(line.get("text", ""))
    elif args.output_blocks:
        text_blocks = result.get("text_blocks", [])
        if not quiet:
            note(f"\n[bold green]OCR Results ({len(text_blocks)} blocks):[/bold green]")
            if not text_blocks:
                note("No text blocks found.")
        for j, block in enumerate(text_blocks):
            if not quiet:
                note(f"\n--- [cyan]Block #{j + 1}[/cyan] ---")
            emit(block.get("text", ""))
    else:
        ocr_text = result.get("ocr_text")
        if not quiet:
            note("\n[bold green]OCR Results:[/bold green]")
        if ocr_text:
            emit(ocr_text)
        elif not quiet:
            note("No OCR text found.")

    translated = result.get("translated_text")
    if translated:
        if not quiet:
            suffix = " (Full)" if (args.output_lines or args.output_blocks) else ""
            note(f"\n[bold green]Translated Text{suffix}:[/bold green]")
        emit(translated)


async def _run_region(
    api: Any, args: argparse.Namespace, settings: Settings, source: str
) -> int:
    try:
        region = tuple(float(v) for v in args.region.split(","))
        if len(region) != 4:
            raise ValueError
    except ValueError:
        fail(
            "--region takes four numbers: center_x,center_y,width,height "
            "(normalized 0..1)."
        )
        return EXIT_USAGE

    try:
        result = await api.process_region(
            real_path(source),
            region=region,
            ocr_language=args.ocr_lang,
            text_query=args.text_query,
            ocr_preserve_line_breaks=settings.ocr_preserve_line_breaks,
        )
    except LensException as e:
        fail(str(e), "Lens API Error")
        return EXIT_FAILED

    if not args.quiet:
        note(
            f"\n[bold green]Region OCR[/bold green] "
            f"(crop sent at {result['crop_size'][0]}x{result['crop_size'][1]}):"
        )
    emit(result["ocr_text"])
    if args.sharex and result["ocr_text"]:
        if not copy_to_clipboard(result["ocr_text"]):
            fail("Could not copy to the clipboard.")
            return EXIT_FAILED
    return EXIT_OK


def _overlay_path_for(base: Optional[str], index: int, total: int) -> Optional[str]:
    """Give every image in a batch its own overlay file.

    A single --translate-out path meant each image overwrote the previous one,
    so only the last result survived.
    """
    if not base or total == 1:
        return base
    stem, ext = os.path.splitext(base)
    return f"{stem}_{index + 1}{ext or '.png'}"


def _collect_sources(source: str, quiet: bool) -> Optional[List[str]]:
    # Names are kept as typed (they are echoed in results); real_path() is what
    # touches the disk, so a daemon resolves them against the client's cwd.
    if os.path.isdir(real_path(source)):
        if not quiet:
            note(f"Processing directory: [cyan]{escape(source)}[/cyan]")
        found = [
            os.path.join(source, name)
            for name in sorted(os.listdir(real_path(source)))
            if is_image_file_supported(real_path(os.path.join(source, name)))
        ]
        if not found:
            fail(f"No supported image files found in directory '{source}'.")
            return None
        return found
    if not is_image_file_supported(real_path(source)):
        fail(f"Source '{source}' is not a valid URL or supported image file.")
        return None
    return [source]


async def _run_batch(
    api: Any, args: argparse.Namespace, settings: Settings, sources: List[str]
) -> int:
    total = len(sources)
    fmt = args.output_format
    structured = fmt != "text"  # json / jsonl / hocr / tsv

    if args.oneline:
        api_format = "full_text"
    elif structured:
        api_format = "detailed"
    elif args.output_blocks:
        api_format = "blocks"
    elif args.output_lines:
        api_format = "lines"
    else:
        api_format = "full_text"

    needs_size = fmt in ("hocr", "tsv")
    wants_size = fmt in ("json", "jsonl")

    async def process(index: int, path: str):
        overlay_path = _overlay_path_for(args.output_overlay_path, index, total)
        result = await api.process_image(
            image_path=real_path(path),
            ocr_language=args.ocr_lang,
            target_translation_language=settings.target_lang,
            source_translation_language=args.source_lang,
            output_overlay_path=real_path(overlay_path) if overlay_path else None,
            ocr_preserve_line_breaks=settings.ocr_preserve_line_breaks,
            output_format=api_format,
            **_render_kwargs(settings),
        )
        size = None
        if needs_size or wants_size:
            size = await _image_size(api, path)
            if needs_size and size is None:
                raise LensImageError(
                    f"Could not determine the pixel size of '{path}', which "
                    f"--format {fmt} needs for its coordinates."
                )
        return result, size

    results: Dict[int, Any] = {}
    ready = asyncio.Condition()
    queue: asyncio.Queue = asyncio.Queue()
    for i, path in enumerate(sources):
        queue.put_nowait((i, path))

    async def worker():
        while True:
            index, path = await queue.get()
            try:
                try:
                    outcome: Any = await process(index, path)
                except Exception as e:  # any failure is that image's, not the run's
                    outcome = e
                async with ready:
                    results[index] = outcome
                    ready.notify()
            finally:
                queue.task_done()

    workers = [
        asyncio.create_task(worker()) for _ in range(min(settings.concurrency, total))
    ]

    failed = 0
    pages: List[formats.Page] = []  # for the formats written once at the end
    records: List[Dict[str, Any]] = []

    try:
        for index, path in enumerate(sources):
            async with ready:
                await ready.wait_for(lambda: index in results)
            outcome = results.pop(index)
            name = os.path.basename(path) if not is_url(path) else path

            if isinstance(outcome, Exception):
                failed += 1
                label = f"({index + 1}/{total}) {name}" if total > 1 else name
                fail(str(outcome), f"Error for {label}")
                if args.oneline:
                    emit(formats.oneline_record(path, error=str(outcome)))
                elif fmt in ("json", "jsonl"):
                    record = formats.error_record(path, str(outcome))
                    if fmt == "jsonl":
                        emit(formats.format_jsonl_line(record))
                    else:
                        records.append(record)
                continue

            result, size = outcome
            if total > 1 and not args.quiet and not (args.oneline or structured):
                note(
                    f"\n- [bold green]({index + 1}/{total}) Result for: "
                    f"{escape(name)}[/bold green] -"
                )

            if args.oneline:
                emit(
                    formats.oneline_record(
                        path,
                        ocr_text=result.get("ocr_text"),
                        translated_text=result.get("translated_text"),
                    )
                )
            elif structured:
                page = formats.Page(
                    file=path,
                    result=result,
                    width=size[0] if size else None,
                    height=size[1] if size else None,
                )
                if fmt in ("json", "jsonl"):
                    record = formats.page_to_dict(
                        page, settings.ocr_preserve_line_breaks
                    )
                    if fmt == "jsonl":
                        emit(formats.format_jsonl_line(record))
                    else:
                        records.append(record)
                else:
                    pages.append(page)
            elif args.get_coords:
                emit(_coords_json(result))
            else:
                _print_text_result(result, args, settings)

            translated = result.get("translated_text")
            if settings.target_lang and not translated and not args.quiet:
                note(
                    "\n[yellow]Translation was requested but not found in the response.[/yellow]"
                )

            if args.output_overlay_path and translated:
                saved = _overlay_path_for(args.output_overlay_path, index, total)
                if not args.quiet:
                    note(
                        f"\nImage with overlay saved to: [cyan]{escape(str(saved))}[/cyan]"
                    )
                else:
                    logger.info("Image with overlay saved to: %s", saved)

            if args.sharex:
                text, what = _text_to_copy(
                    result,
                    settings,
                    blocks_mode=args.output_blocks and not structured,
                )
                if text:
                    if copy_to_clipboard(text):
                        if not args.quiet:
                            note(
                                f"\n[bold magenta]({what} copied to clipboard)[/bold magenta]"
                            )
                        else:
                            logger.info("%s copied to clipboard", what)
                    else:
                        failed += 1
                        fail(
                            "Failed to copy text. Is 'pyperclip' installed? "
                            '(pip install "chrome-lens-py[clipboard]")'
                        )
                elif not args.quiet:
                    note("\n[yellow]No text available to copy.[/yellow]")

        if fmt == "json" and records:
            emit(formats.format_json(records))
        elif fmt == "hocr" and pages:
            write_stdout(formats.format_hocr(pages))
        elif fmt == "tsv" and pages:
            write_stdout(formats.format_tsv(pages))
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    return _exit_code(failed, total)


async def _run_serve(args: argparse.Namespace, settings: Settings) -> int:
    from ..server import is_loopback, run_server

    if not is_loopback(args.host) and not args.token:
        fail(f"refusing to listen on {args.host} without --token.")
        err_console.print(
            "Anyone who could reach that address would be able to spend your "
            "API key on Google requests.\n"
            "Either bind 127.0.0.1, or pass --token."
        )
        return EXIT_USAGE

    note(
        f"[bold green]chrome-lens-py daemon[/bold green] on "
        f"[cyan]http://{escape(args.host)}:{settings.daemon_port}[/cyan]  "
        f"(POST /v1/ocr, POST /v1/region, POST /v1/ocr/raw, GET /health)"
    )
    if args.allow_origin:
        note(f"Allowed browser origins: {escape(', '.join(args.allow_origin))}")
    else:
        note(
            "[dim]Local programs only; no web page can reach it. "
            "Use --allow-origin to permit one.[/dim]"
        )
    try:
        await run_server(
            host=args.host,
            port=settings.daemon_port,
            token=args.token,
            allowed_origins=frozenset(args.allow_origin),
            **_api_kwargs(settings),
        )
    except ValueError as e:
        fail(str(e))
        return EXIT_FAILED
    return EXIT_OK


async def _run_managed(args: argparse.Namespace, settings: Settings) -> int:
    """--serve --auto / --serve --service: the daemon lens_scan talks to itself."""
    from ..daemon import run_managed_daemon

    if args.allow_origin:
        fail("--allow-origin is not available on the managed daemon.")
        return EXIT_USAGE
    if args.auto and args.service:
        fail("--auto and --service cannot be used together.")
        return EXIT_USAGE
    try:
        return await run_managed_daemon(
            settings,
            service=bool(args.service),
            port_override=(
                settings.daemon_port
                if settings.sources.get("daemon_port") == "command line"
                else None
            ),
        )
    except LensConfigError as e:
        fail(str(e), "Configuration Error")
        return EXIT_FAILED


def _check_output_modes(args: argparse.Namespace) -> Optional[str]:
    modes = {
        "--output-blocks": args.output_blocks,
        "--output-lines": args.output_lines,
        "--get-coords": args.get_coords,
        "--oneline": args.oneline,
        f"--format {args.output_format}": args.output_format != "text",
    }
    chosen = [flag for flag, on in modes.items() if on]
    if len(chosen) > 1:
        return f"{', '.join(chosen)} cannot be used together."
    if args.region and chosen:
        return f"{chosen[0]} cannot be combined with --region."
    return None


# Things the daemon never runs itself: they act on the machine (ShareX, the
# config file, services), print version/help, or are the daemon.
_LOCAL_ONLY_ATTRS = (
    "version",
    "help",
    "setup_sharex",
    "update_config",
    "show_config",
    "serve",
    "install_service",
    "uninstall_service",
    "daemon_status",
    "daemon_start",
    "daemon_stop",
)


async def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return its exit code (0 ok, 1 all failed, 2 some failed).

    Inside the daemon (a CliContext is set) this is the same code, writing to
    that context's streams and resolving paths against its working directory.
    Anything that must run in the user's own process raises RunLocally.
    """
    ctx = current_context()
    parser = build_parser(_NoExitParser if ctx is not None else argparse.ArgumentParser)
    args = parser.parse_args(argv)

    if ctx is not None:
        for attr in _LOCAL_ONLY_ATTRS:
            if getattr(args, attr, False):
                raise RunLocally(f"--{attr.replace('_', '-')}")
        if not args.image_source:
            raise RunLocally("no image source")

    if args.version:
        print_version()
        return EXIT_OK
    if args.help:
        print_help(parser)
        return EXIT_OK
    if args.setup_sharex:
        lang = getattr(args, "target_lang", None)
        if args.mode == "program":
            ok = setup_sharex_config(lang)
        else:
            ok = setup_sharex(args.mode, lang, getattr(args, "daemon_port", None))
        return EXIT_OK if ok else EXIT_FAILED
    if args.daemon_status or args.daemon_start or args.daemon_stop:
        from .. import client

        if args.daemon_status:
            return client.daemon_status()
        if args.daemon_stop:
            return client.daemon_stop()
        return client.daemon_start(
            getattr(args, "daemon_idle_timeout", client.DEFAULT_IDLE_TIMEOUT)
        )
    if args.install_service or args.uninstall_service:
        from ..utils import service

        if args.uninstall_service:
            return EXIT_OK if service.uninstall_service() else EXIT_FAILED
        return (
            EXIT_OK
            if service.install_service(getattr(args, "daemon_port", None))
            else EXIT_FAILED
        )

    env = ctx.env if ctx is not None else None
    default_config_path = os.path.join(
        get_default_config_dir(environ=env), DEFAULT_CONFIG_FILENAME
    )
    config_file_to_load = (
        real_path(args.config_file_path_override)
        if args.config_file_path_override
        else default_config_path
    )

    try:
        settings = resolve_settings(vars(args), config_file_to_load, env=env)
    except LensConfigError as e:
        fail(str(e), "Configuration Error")
        return EXIT_FAILED

    level = settings.logging_level
    managed = args.serve and (args.auto or args.service)
    if args.serve and settings.sources.get("logging_level") == "default":
        level = "INFO"  # a daemon with no log output looks hung
    if ctx is not None:
        # The daemon's logging is installed once; a request only chooses how
        # much of it to send back to its own client.
        ctx.log_level = getattr(logging, level, logging.WARNING)
    elif not managed:
        setup_logging(level)

    if settings.font_path:
        settings.font_path = real_path(settings.font_path)

    if os.path.exists(config_file_to_load):
        logger.info("Using config file: %s", config_file_to_load)
    elif args.config_file_path_override:
        logger.warning("Specified config file not found: %s", config_file_to_load)
    for message in settings.notes:
        logger.warning(message)
    for name, source in settings.sources.items():
        if source != "default":
            shown = "<hidden>" if name in SECRET_FIELDS else getattr(settings, name)
            logger.debug("Setting %s = %s (from %s)", name, shown, source)

    if args.show_config:
        return print_resolved_config(
            settings, config_file_to_load, getattr(args, "as_json", False)
        )

    if args.update_config:
        if args.config_file_path_override:
            note(
                "[bold yellow]Warning:[/bold yellow] --update-config only affects "
                "the default config file."
            )
        else:
            try:
                update_config_file_from_cli(vars(args), default_config_path)
            except LensConfigError as e:
                fail(str(e), "Error updating config")
                return EXIT_FAILED
        if not args.image_source and not args.serve:
            return EXIT_OK

    if args.serve:
        if args.auto or args.service:
            return await _run_managed(args, settings)
        return await _run_serve(args, settings)

    if settings.concurrency > CONCURRENCY_WARNING_THRESHOLD:
        note(
            f"[bold yellow]Warning:[/bold yellow] High concurrency value "
            f"({settings.concurrency}) set. This may result in a temporary block "
            "by Google. Use with caution."
        )

    if not args.image_source:
        from ..manage import short_help

        fail("nothing to read. Give an image, a URL or a folder - or a command.")
        sys.stderr.write("\n" + short_help())
        sys.stderr.flush()
        return EXIT_USAGE

    problem = _check_output_modes(args)
    if problem:
        fail(problem)
        return EXIT_USAGE

    sources = _collect_sources(args.image_source, args.quiet)
    if sources is None:
        return EXIT_FAILED

    owns_api = ctx is None or ctx.api_provider is None
    if owns_api:
        api = LensAPI(**_api_kwargs(settings))
    else:
        assert ctx is not None and ctx.api_provider is not None
        api = await ctx.api_provider(settings, ctx.env)
    try:
        if args.region:
            return await _run_region(api, args, settings, sources[0])
        return await _run_batch(api, args, settings, sources)
    finally:
        if owns_api:  # a daemon keeps its pooled connections for the next request
            await api.aclose()


class _Recorder(io.StringIO):
    """A capture buffer that also remembers the order writes arrived in."""

    def __init__(self, order: List[List[Any]], tag: str):
        super().__init__()
        self._order = order
        self._tag = tag

    def write(self, text: str) -> int:
        if text:
            if self._order and self._order[-1][0] == self._tag:
                self._order[-1][1] += text
            else:
                self._order.append([self._tag, text])
        return super().write(text)


async def run_cli_request(
    *,
    argv: Sequence[str],
    cwd: str,
    env: Mapping[str, str],
    stdin_is_tty: bool = False,
    stdout_is_tty: bool = False,
    stderr_is_tty: bool = False,
    columns: Optional[int] = None,
    api_provider: Optional[ApiProvider] = None,
) -> Dict[str, Any]:
    """Run one forwarded command line inside this (daemon) process.

    Returns ``{"exit_code", "stdout", "stderr"}``, or ``{"run_locally": why}``
    for a command the client has to run itself. `stdin_is_tty` is accepted for
    completeness: no daemon-eligible command reads stdin or prompts.
    """
    order: List[List[Any]] = []
    out, err = _Recorder(order, "out"), _Recorder(order, "err")
    ctx = CliContext(
        out=out,
        err=err,
        err_console=Console(
            file=err,
            force_terminal=stderr_is_tty,
            width=columns,
            # The daemon has no console to probe, so say what rich would have
            # decided in the client: a Windows stdout that is not a terminal
            # (ShareX's pipe) is "legacy" there, which also wraps one column
            # narrower.
            legacy_windows=sys.platform == "win32" and not stdout_is_tty,
            _environ=dict(env),
        ),
        cwd=cwd,
        env=dict(env),
        api_provider=api_provider,
    )
    token = _CONTEXT.set(ctx)
    try:
        code = await cli_main(list(argv))
    except RunLocally as e:
        return {"run_locally": str(e)}
    except asyncio.CancelledError:
        raise
    except Exception as e:  # a bug must not turn into a hung or empty reply
        logger.exception("Forwarded command crashed")
        err.write(f"Error: {type(e).__name__}: {e}\n")
        code = EXIT_FAILED
    finally:
        _CONTEXT.reset(token)
    reply: Dict[str, Any] = {
        "exit_code": code,
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
    }
    if reply["stdout"] and reply["stderr"]:
        # On a terminal the two streams interleave ("OCR Results:" before the
        # text it heads); the client replays them in the order they were written.
        reply["events"] = order
    return reply


def force_utf8_streams(streams=None):
    """Make stdout/stderr able to carry the text we are about to print.

    This was once guarded by sys.platform == "win32", because the console code
    page is where it was first noticed. That was too narrow: a Unix process
    started without LANG gets an ASCII stdout too, and the first non-Latin
    character then raises UnicodeEncodeError and takes the run down with it.
    Every way this tool is actually automated does exactly that - launchd,
    cron, an Automator Quick Action, Karabiner's shell_command, a plain
    non-interactive ssh command. Caught on macOS, where translating into
    Russian died inside rich's writer.

    Reconfiguring the stream directly rather than shelling out to chcp: chcp is
    a console builtin that is not always resolvable (it fails outright under
    Git Bash / MSYS), and it does nothing for a piped stdout, which is exactly
    how ShareX invokes us.
    """
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        try:
            if getattr(stream, "encoding", "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception as e:  # pragma: no cover - very old/odd streams
            logger.debug("Could not reconfigure stream to UTF-8: %s", e)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Synchronous entry point that returns the exit code instead of exiting."""
    try:
        return asyncio.run(cli_main(argv))
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        return 130


def run():
    force_utf8_streams()
    sys.exit(main())


if __name__ == "__main__":
    run()
