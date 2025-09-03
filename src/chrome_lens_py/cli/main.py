import argparse
import asyncio
import json
import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text

from ..api import LensAPI
from ..constants import (
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_CONFIG_FILENAME,
)
from ..exceptions import LensConfigError, LensException
from ..utils.config_manager import (
    build_app_config,
    get_default_config_dir,
    update_config_file_from_cli,
)
from ..utils.general import is_image_file_supported
from ..utils.sharex import copy_to_clipboard

console = Console()


def setup_logging(level_str: str = "WARNING"):
    log_level = getattr(logging, level_str.upper(), logging.WARNING)
    log_format = (
        "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        if log_level <= logging.DEBUG
        else "%(message)s"
    )
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            RichHandler(
                console=console,
                show_time=False,
                show_level=log_level <= logging.INFO,
                show_path=log_level <= logging.DEBUG,
                markup=True,
                rich_tracebacks=True,
            )
        ],
    )
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.debug(f"Logging level set to {level_str.upper()}")


def print_help():
    console.print("\n[bold cyan]Google Lens CLI (chrome-lens-py)[/bold cyan]")
    console.print("Performs OCR and optional translation on an image.")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="green")
    table.add_column()
    table.add_row("Usage:", "lens_scan <image_source> [ocr_lang] [options]")
    table.add_row("\n[bold]Arguments:[/bold]")
    table.add_row("  image_source", "Path to an image file, a URL, or a directory.")
    table.add_row(
        "  ocr_lang",
        "BCP 47 language code for OCR (e.g., 'en', 'ja'). If omitted, auto-detection is attempted.",
    )
    table.add_row("\n[bold]Translation Options:[/bold]")
    table.add_row(
        "  -t, --translate TARGET_LANG",
        "Target language for translation (e.g., 'en', 'ru').",
    )
    table.add_row(
        "  --translate-from SOURCE_LANG",
        "Source language for translation (auto-detected if omitted).",
    )
    table.add_row(
        "  -to, --translate-out FILE_PATH",
        "Save the image with translated text overlaid.",
    )
    table.add_row("\n[bold]Output and Config Options:[/bold]")
    table.add_row(
        "  -b, --output-blocks",
        "Output OCR text as segmented blocks (useful for comics).",
    )
    table.add_row(
        "  -ol, --output-lines",
        "Output OCR text as individual lines with their geometry.",
    )
    table.add_row(
        "  --get-coords",
        "Output recognized words with their coordinates in JSON format.",
    )
    table.add_row(
        "  -q, --quiet",
        "Suppress informational messages and headers, printing only the final result data.",
    )
    table.add_row(
        "  -sx, --sharex", "Copy the result (translation or OCR) to the clipboard."
    )
    table.add_row(
        "  --ocr-single-line",
        "Join all OCR text into a single line (preserves line breaks by default).",
    )
    table.add_row(
        "  --config-file FILE_PATH", "Path to a custom JSON configuration file."
    )
    table.add_row(
        "  --update-config", "Update the default config file with CLI arguments."
    )
    table.add_row("  --font FONT_PATH", "Path to a .ttf font file for the overlay.")
    table.add_row("  --font-size SIZE", "Font size for the overlay (default: 20).")
    table.add_row("\n[bold]Advanced & Debug Options:[/bold]")
    table.add_row("  --api-key KEY", "Google Cloud API key (overrides config).")
    table.add_row(
        "  --proxy URL",
        "Proxy server URL (e.g., http://user:pass@host:port, socks5://host:port).",
    )
    table.add_row("  --timeout SECONDS", "Request timeout in seconds (default: 60).")
    table.add_row(
        "  --concurrency N",
        "Set the maximum number of concurrent requests (default: 5).",
    )
    table.add_row(
        "  --client-region REGION",
        f"Client region code (default: '{DEFAULT_CLIENT_REGION}').",
    )
    table.add_row(
        "  --client-time-zone TZ",
        f"Client time zone ID (default: '{DEFAULT_CLIENT_TIME_ZONE}').",
    )
    table.add_row(
        "  -l, --logging-level LEVEL",
        "Set logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    table.add_row("  -h, --help", "Show this help message and exit.")
    console.print(table)


async def cli_main():
    parser = argparse.ArgumentParser(description="Google Lens CLI", add_help=False)
    # Positional
    parser.add_argument(
        "image_source", nargs="?", help="Path to the image file, a URL, or a directory."
    )
    parser.add_argument(
        "ocr_lang", nargs="?", default=None, help="BCP 47 code for OCR."
    )
    # Translation
    parser.add_argument("-t", "--translate", dest="target_lang")
    parser.add_argument("--translate-from", dest="source_lang")
    parser.add_argument("-to", "--translate-out", dest="output_overlay_path")
    # Output & Config
    parser.add_argument(
        "-b",
        "--output-blocks",
        action="store_true",
        help="Output OCR text as segmented blocks.",
    )
    parser.add_argument(
        "-ol",
        "--output-lines",
        action="store_true",
        help="Output OCR text as individual lines.",
    )
    parser.add_argument(
        "--get-coords",
        action="store_true",
        help="Output word coordinates in JSON format.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational messages, printing only result data.",
    )
    parser.add_argument("-sx", "--sharex", action="store_true")
    parser.add_argument(
        "--ocr-single-line",
        action="store_false",
        dest="ocr_preserve_line_breaks",
        default=None,
    )
    parser.add_argument("--config-file", dest="config_file_path_override")
    parser.add_argument("--update-config", action="store_true")
    parser.add_argument("--font", dest="font_path")
    parser.add_argument("--font-size", type=int)
    # Advanced
    parser.add_argument("--api-key")
    parser.add_argument("--proxy")
    parser.add_argument("--timeout", type=int)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum number of concurrent requests.",
    )
    parser.add_argument("--client-region")
    parser.add_argument("--client-time-zone")
    # Meta
    parser.add_argument("-l", "--logging-level", dest="logging_level")
    parser.add_argument("-h", "--help", action="store_true")

    args = parser.parse_args()

    MAX_CONCURRENCY_HARD_LIMIT = 30
    CONCURRENCY_WARNING_THRESHOLD = 20

    if args.concurrency > MAX_CONCURRENCY_HARD_LIMIT:
        console.print(
            f"[bold red]Error:[/bold red] The concurrency value cannot be greater than {MAX_CONCURRENCY_HARD_LIMIT}."
        )
        console.print("This is a security measure to prevent IP blocking.")
        sys.exit(1)

    if args.concurrency > CONCURRENCY_WARNING_THRESHOLD:
        console.print(
            f"[bold yellow]Warning:[/bold yellow] High concurrency value ({args.concurrency}) set."
        )
        console.print(
            "This may result in a temporary block by Google. Use with caution."
        )

    if args.help:
        print_help()
        return
    if not args.image_source:
        console.print(
            "[bold red]Error:[/bold red] The 'image_source' argument is required.\n"
        )
        print_help()
        sys.exit(1)

    # Validate mutually exclusive output formats
    output_modes = [args.output_blocks, args.get_coords, args.output_lines]
    if sum(output_modes) > 1:
        console.print(
            "[bold red]Error:[/bold red] --output-blocks, --output-lines, and --get-coords cannot be used together."
        )
        sys.exit(1)

    default_config_path = os.path.join(
        get_default_config_dir(), DEFAULT_CONFIG_FILENAME
    )
    config_file_to_load = args.config_file_path_override or default_config_path

    try:
        app_config = build_app_config(vars(args), config_file_to_load)
    except LensConfigError as e:
        console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        sys.exit(1)

    setup_logging(app_config.get("logging_level", "WARNING"))

    if os.path.exists(config_file_to_load):
        logging.info(f"Using config file: {config_file_to_load}")
    elif args.config_file_path_override:
        logging.warning(
            f"Specified config file not found: {args.config_file_path_override}"
        )

    image_sources = []
    if os.path.isdir(args.image_source):
        if not args.quiet:
            console.print(f"Processing directory: [cyan]{args.image_source}[/cyan]")
        for filename in sorted(os.listdir(args.image_source)):
            full_path = os.path.join(args.image_source, filename)
            if is_image_file_supported(full_path):
                image_sources.append(full_path)
        if not image_sources:
            console.print(
                f"[bold red]Error:[/bold red] No supported image files found in directory '{args.image_source}'."
            )
            sys.exit(1)
    else:
        if not is_image_file_supported(args.image_source):
            console.print(
                f"[bold red]Error:[/bold red] Source '{args.image_source}' is not a valid URL or supported image file."
            )
            sys.exit(1)
        image_sources.append(args.image_source)

    if args.update_config:
        if args.config_file_path_override:
            console.print(
                "[bold yellow]Warning:[/bold yellow] --update-config only affects the default config file."
            )
        else:
            try:
                update_config_file_from_cli(vars(args), default_config_path)
            except LensConfigError as e:
                console.print(f"[bold red]Error updating config:[/bold red] {e}")

    api = LensAPI(
        api_key=app_config.get("api_key", DEFAULT_API_KEY),
        client_region=app_config.get("client_region"),
        client_time_zone=app_config.get("client_time_zone"),
        proxy=app_config.get("proxy"),
        timeout=app_config.get("timeout", 60),
        font_path=app_config.get("font_path"),
        font_size=app_config.get("font_size"),
        max_concurrent=args.concurrency,
    )

    try:
        output_format = "full_text"
        if args.output_blocks:
            output_format = "blocks"
        elif args.output_lines:
            output_format = "lines"

        results_buffer = {}
        next_to_print = 0
        results_ready = asyncio.Condition()

        async def worker(queue):
            while True:
                index, path = await queue.get()
                try:

                    try:
                        result = await api.process_image(
                            image_path=path,
                            ocr_language=args.ocr_lang,
                            target_translation_language=args.target_lang,
                            source_translation_language=args.source_lang,
                            output_overlay_path=args.output_overlay_path,
                            ocr_preserve_line_breaks=app_config.get(
                                "ocr_preserve_line_breaks", True
                            ),
                            output_format=output_format,
                        )
                    except Exception as e:
                        result = e

                    async with results_ready:
                        results_buffer[index] = result
                        results_ready.notify()

                finally:
                    queue.task_done()

        job_queue = asyncio.Queue()
        for i, path in enumerate(image_sources):
            job_queue.put_nowait((i, path))

        worker_tasks = [
            asyncio.create_task(worker(job_queue)) for _ in range(args.concurrency)
        ]

        while next_to_print < len(image_sources):
            async with results_ready:
                await results_ready.wait_for(lambda: next_to_print in results_buffer)

            result = results_buffer.pop(next_to_print)
            image_path = image_sources[next_to_print]

            if isinstance(result, Exception):
                console.print(
                    f"\n- [bold red]({next_to_print + 1}/{len(image_sources)}) Error for: {os.path.basename(image_path)}[/bold red] -"
                )
                console.print(f"[red]{result}[/red]")
                next_to_print += 1
                continue

            if len(image_sources) > 1 and not args.quiet:
                console.print(
                    f"\n- [bold green]({next_to_print + 1}/{len(image_sources)}) Result for: {os.path.basename(image_path)}[/bold green] -"
                )

            if args.get_coords:
                word_data = result.get("word_data")
                if not word_data:
                    console.print("[]")
                    next_to_print += 1
                    continue  # Continue to next image in batch

                processed_coords = []
                for data in word_data:
                    geom = data.get("geometry")
                    processed_coords.append(
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

                console.print(
                    json.dumps(processed_coords, indent=2, ensure_ascii=False)
                )

            elif args.output_lines:
                line_blocks = result.get("line_blocks", [])
                if not args.quiet:
                    console.print(
                        f"\n[bold green]OCR Results ({len(line_blocks)} lines):[/bold green]"
                    )
                if not line_blocks and not args.quiet:
                    console.print("No lines found.")

                for j, line in enumerate(line_blocks):
                    if not args.quiet:
                        console.print(f"\n--- [cyan]Line #{j+1}[/cyan] ---")
                    console.print(Text(line.get("text", "")))

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        console.print(
                            "\n[bold green]Translated Text (Full):[/bold green]"
                        )
                    console.print(Text(translated_text))

            elif args.output_blocks:
                text_blocks = result.get("text_blocks", [])
                if not args.quiet:
                    console.print(
                        f"\n[bold green]OCR Results ({len(text_blocks)} blocks):[/bold green]"
                    )
                if not text_blocks and not args.quiet:
                    console.print("No text blocks found.")

                for j, block in enumerate(text_blocks):
                    if not args.quiet:
                        console.print(f"\n--- [cyan]Block #{j+1}[/cyan] ---")
                    console.print(Text(block.get("text", "")))

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        console.print(
                            "\n[bold green]Translated Text (Full):[/bold green]"
                        )
                    console.print(Text(translated_text))

            else:  # Default 'full_text' output
                ocr_text = result.get("ocr_text")
                if ocr_text:
                    if not args.quiet:
                        console.print("\n[bold green]OCR Results:[/bold green]")
                    console.print(Text(ocr_text))
                elif not args.quiet:
                    console.print("\n[bold green]OCR Results:[/bold green]")
                    console.print("No OCR text found.")

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        console.print("\n[bold green]Translated Text:[/bold green]")
                    console.print(Text(translated_text))

            translated_text = result.get("translated_text")
            if args.target_lang and not translated_text and not args.quiet:
                console.print(
                    "\n[yellow]Translation was requested but not found in the response.[/yellow]"
                )

            if args.output_overlay_path and translated_text:
                if not args.quiet:
                    console.print(
                        f"\nImage with overlay saved to: [cyan]{args.output_overlay_path}[/cyan]"
                    )
                else:
                    logging.info(
                        f"Image with overlay saved to: {args.output_overlay_path}"
                    )

            if args.sharex:
                source_for_copy, text_to_copy = ("", "")
                # Prioritize translated text for copying
                if args.target_lang and translated_text:
                    text_to_copy, source_for_copy = translated_text, "Translated text"
                elif args.output_blocks:
                    blocks = result.get("text_blocks", [])
                    if blocks:
                        text_to_copy = "\n\n".join([b.get("text", "") for b in blocks])
                        source_for_copy = "OCR text (blocks)"
                else:
                    ocr_text = result.get("ocr_text")
                    if ocr_text:
                        text_to_copy, source_for_copy = ocr_text, "OCR text"

                if text_to_copy:
                    if copy_to_clipboard(text_to_copy):
                        if not args.quiet:
                            console.print(
                                f"\n[bold magenta]({source_for_copy} copied to clipboard)[/bold magenta]"
                            )
                        else:
                            logging.info(f"{source_for_copy} copied to clipboard")
                    else:
                        # This is an error/warning, so it should probably stay visible
                        console.print(
                            "\n[bold red]Failed to copy text. Is 'pyperclip' installed? "
                            '(`pip install "chrome-lens-py[clipboard]"`)[/bold red]'
                        )
                elif not args.quiet:
                    console.print("\n[yellow]No text available to copy.[/yellow]")

            next_to_print += 1

        await job_queue.join()
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    except LensException as e:
        console.print(f"\n[bold red]Lens API Error:[/bold red] {e}")
        sys.exit(1)


def run():
    if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
        try:
            os.system("chcp 65001 > nul")
            logging.debug("Set Windows console to chcp 65001 (UTF-8)")
        except Exception as e:
            print(f"Warning: Failed to set console to UTF-8 (chcp 65001). Error: {e}")
    try:
        asyncio.run(cli_main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")


if __name__ == "__main__":
    run()
