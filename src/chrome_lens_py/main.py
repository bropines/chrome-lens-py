import argparse
import asyncio
import json
import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler

# Import exceptions
from .exceptions import (LensAPIError, LensCookieError, LensError,
                         LensParsingError)
# Import the *updated* LensAPI
from .lens_api import LensAPI
# Keep utils
from .utils import get_default_config_dir, is_supported_mime, is_url

# Constants might be used for default values or reference
# from .constants import HEADERS_DEFAULT # Example header set reference

console = Console()


def print_help():
    # Use OLD data_type names here for consistency
    console.print("Usage: [b]lens_scan [options] <image_source> [data_type][/b]")
    console.print(
        "\n[b]image_source[/b]: Path to an image file, directory of images, or image URL."
    )
    console.print("\nOptions:")
    console.print("[b]-h, --help[/b]                Show this help message and exit")
    console.print(
        "[b]-c, --cookie-file[/b]         Path to the Netscape or .pkl cookie file"
    )
    console.print(
        "[b]-p, --proxy[/b]               Specify proxy server (e.g., http://user:pass@host:port, socks5://host:port)"
    )
    console.print(
        "[b]--config-file[/b]             Path to the JSON configuration file"
    )
    console.print(
        "[b]--debug=(info|debug)[/b]      Enable logging (debug includes more detail)"
    )
    console.print(
        "[b]--coordinate-format[/b]       Output coordinates format: 'percent' (default) or 'pixels'"
    )
    # sleep-time is less relevant due to internal rate limiter, maybe remove or deprioritize help text?
    # console.print(
    #     "[b]-st, --sleep-time[/b]         (Less relevant now) Sleep time between requests in milliseconds")
    console.print(
        "[b]-uc, --update-config[/b]      Update the default config file with non-sensitive CLI args."
    )
    console.print(
        "[b]--debug-out[/b]               Path to save raw metadata response (for debugging)"
    )
    console.print(
        "[b]--out-txt[/b]                 Output results to text file(s): 'per_file' for individual files in the source directory, or a specific filename (e.g., 'output.txt') for a single combined file."
    )
    # header-type is less relevant now, only one default set used internally
    # console.print(
    #     "[b]--header-type[/b]             (Currently ignored) Header type to use")
    console.print(
        "[b]--rate-limit-rpm[/b]          Set max requests per minute (e.g., 30). Overrides config."
    )
    console.print("\n[b][data_type][/b] options (default: all):")
    console.print(
        "[b]all[/b]                       Get all data (language, full text, coordinates, stitched text)"
    )
    console.print(
        "[b]full_text_default[/b]         Get the main reconstructed text"
    )  # Reverted Name
    console.print(
        "[b]full_text_old_method[/b]      Get text stitched sequentially"
    )  # Reverted Name
    console.print(
        "[b]full_text_new_method[/b]      Get text stitched using line reconstruction"
    )  # Reverted Name
    console.print(
        "[b]coordinates[/b]               Get word annotations with coordinates (and angle)"
    )


def load_config(config_file=None):
    """Loads configuration from a JSON file."""
    config = {}
    # Determine config file path
    effective_config_file = config_file
    if not effective_config_file:
        # Check environment variable
        env_config_path = os.getenv("LENS_SCAN_CONFIG_PATH")
        if env_config_path and os.path.isfile(env_config_path):
            effective_config_file = env_config_path
            logging.debug(
                f"Using config file from environment variable: {effective_config_file}"
            )
        else:
            # Load default config from default config directory
            app_name = "chrome-lens-py"
            config_dir = get_default_config_dir(app_name)
            default_config_file = os.path.join(config_dir, "config.json")
            if os.path.isfile(default_config_file):
                effective_config_file = default_config_file
                logging.debug(f"Using default config file: {effective_config_file}")

    # Load the determined config file
    if effective_config_file and os.path.isfile(effective_config_file):
        try:
            with open(effective_config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            logging.debug(f"Loaded configuration from: {effective_config_file}")
        except (json.JSONDecodeError, IOError) as e:
            console.print(
                f"[red]Error loading config file '{effective_config_file}':[/red] {e}"
            )
            # Decide if execution should stop or continue with defaults
            # sys.exit(1) # Optional: exit on config load error
        except Exception as e:
            console.print(
                f"[red]Unexpected error loading config file '{effective_config_file}':[/red] {e}"
            )
            # sys.exit(1) # Optional: exit
    else:
        logging.debug("No config file specified or found. Using defaults and CLI args.")

    return config


def save_config(config):
    """Saves configuration to the default config file location."""
    app_name = "chrome-lens-py"
    config_dir = get_default_config_dir(app_name)
    if not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir)
        except OSError as e:
            console.print(
                f"[red]Error creating config directory '{config_dir}':[/red] {e}. Cannot save config."
            )
            return
    default_config_file = os.path.join(config_dir, "config.json")
    try:
        with open(default_config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        logging.info(f"Configuration saved to {default_config_file}")
    except (IOError, TypeError) as e:
        console.print(
            f"[red]Error saving config file '{default_config_file}':[/red] {e}"
        )
    except Exception as e:
        console.print(
            f"[red]Unexpected error saving config file '{default_config_file}':[/red] {e}"
        )


async def process_image(image_source, data_type, coordinate_format, api):
    """Processes a single image source (file, URL) using the LensAPI."""
    try:
        logging.info(
            f"Processing source: '{str(image_source)[:100]}...' requesting data type: {data_type}"
        )

        # Call the appropriate async API method based on OLD data_type names
        if data_type == "all":
            result = await api.get_all_data(
                image_source, coordinate_format=coordinate_format
            )
        elif data_type == "full_text_default":  # Reverted Name
            result = await api.get_full_text(
                image_source
            )  # Maps to the new get_full_text
        elif data_type == "full_text_old_method":  # Reverted Name
            # Maps to get_stitched_text_sequential
            result = await api.get_stitched_text_sequential(image_source)
        elif data_type == "full_text_new_method":  # Reverted Name
            # Maps to get_stitched_text_smart
            result = await api.get_stitched_text_smart(image_source)
        elif data_type == "coordinates":
            result = await api.get_text_with_coordinates(
                image_source, coordinate_format=coordinate_format
            )
        else:
            # Should not happen if arg choices are set correctly, but check anyway
            console.print(f"[red]Invalid data type '{data_type}' requested.[/red]")
            return None  # Indicate failure

        logging.debug(f"Result received for '{str(image_source)[:50]}...'")
        return result

    # Catch errors specifically from the API layer or below
    except (LensAPIError, LensParsingError, LensCookieError, LensError) as e:
        logging.error(f"API Error processing '{str(image_source)[:100]}...': {e}")
        console.print(f"[red]API Error processing source:[/red] {e}")
        # Optionally include details if available and logging level allows
        if logging.getLogger().isEnabledFor(logging.DEBUG) and hasattr(e, "body"):
            console.print(
                f"[grey]Response Body (partial): {str(e.body)[:200]}...[/grey]"
            )
        return None  # Indicate failure
    except Exception as e:
        # Catch unexpected errors during the API call
        logging.error(
            f"Unexpected Error processing '{str(image_source)[:100]}...': {e}",
            exc_info=True,
        )
        console.print(f"[red]Unexpected Error processing source:[/red] {e}")
        return None  # Indicate failure


async def process_directory(
    directory_path, data_type, coordinate_format, api, out_txt_option=None
):
    """Processes all supported image files in a directory."""
    files_to_process = []
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        if os.path.isfile(file_path) and is_supported_mime(file_path):
            files_to_process.append((filename, file_path))
        elif os.path.isfile(file_path):
            logging.debug(f"Skipping unsupported file: {filename}")

    if not files_to_process:
        console.print(f"No supported image files found in directory: {directory_path}")
        return

    console.print(
        f"Found {len(files_to_process)} supported images in '{directory_path}'. Processing..."
    )

    results_data = {}  # Store results if needed later, e.g., for single file output

    # --- Output Handling ---
    single_output_file = None
    if out_txt_option and out_txt_option != "per_file":
        # User specified a filename for combined output
        output_file_path = os.path.join(directory_path, out_txt_option)
        try:
            single_output_file = open(output_file_path, "w", encoding="utf-8")
            logging.info(f"Will write all results to single file: {output_file_path}")
        except IOError as e:
            console.print(
                f"[red]Error opening output file '{output_file_path}': {e}. Cannot write output.[/red]"
            )
            return  # Cannot proceed with this output mode

    # Process files one by one (async allows concurrency within API calls if supported)
    for idx, (filename, file_path) in enumerate(files_to_process):
        if (
            logging.root.level > logging.INFO
        ):  # Add visual separator if not in verbose modes
            console.print(
                f"--- Processing file {idx+1}/{len(files_to_process)}: [cyan]{filename}[/cyan] ---"
            )
        else:
            logging.info(
                f"Processing file {idx+1}/{len(files_to_process)}: {filename}..."
            )

        # Await the result for the current file
        result = await process_image(file_path, data_type, coordinate_format, api)

        if result is not None:
            # Format result for output (handle dicts vs strings)
            if isinstance(result, dict):
                result_str = json.dumps(result, indent=2, ensure_ascii=False)
            elif isinstance(result, list):
                result_str = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                result_str = str(result)  # Assume string if not dict/list

            if out_txt_option == "per_file":
                base_name, _ = os.path.splitext(filename)
                output_file_path = os.path.join(directory_path, f"{base_name}.txt")
                try:
                    with open(output_file_path, "w", encoding="utf-8") as output_file:
                        output_file.write(result_str + "\n")  # Add newline
                    logging.info(f"Result for {filename} written to {output_file_path}")
                except IOError as e:
                    console.print(
                        f"[red]Error writing output file '{output_file_path}': {e}[/red]"
                    )
            elif single_output_file:
                # Write to the combined file
                single_output_file.write(f"# --- Result for: {filename} ---\n")
                single_output_file.write(result_str + "\n\n")  # Add separator
                logging.info(f"Result for {filename} added to combined output file.")
                results_data[filename] = result  # Store if needed elsewhere
            else:
                # Default: print to console if no file output specified for directory
                console.print(f"\n[bold green]Result for {filename}:[/bold green]")
                console.print(result_str)
        else:
            # Processing failed for this file, error already logged by process_image
            if single_output_file:
                single_output_file.write(f"# --- FAILED processing: {filename} ---\n\n")
            results_data[filename] = {
                "error": "Processing failed, see logs."
            }  # Mark failure

    # Close the single output file if it was opened
    if single_output_file:
        single_output_file.close()
        logging.info(f"Finished writing all results to {single_output_file.name}")


# Make main async
async def main():
    parser = argparse.ArgumentParser(
        description="Process images with Google Lens API (Updated Method) and extract text/data.",
        add_help=False,  # Use custom help print
    )
    # Positional Arguments
    parser.add_argument(
        "image_source",
        nargs="?",
        help="Path to the image file, directory, or image URL.",
    )
    # Use OLD data_type names here for CLI compatibility
    parser.add_argument(
        "data_type",
        nargs="?",
        default="all",
        choices=[
            "all",
            "full_text_default",
            "full_text_old_method",
            "full_text_new_method",
            "coordinates",
        ],
        help="Type of data to extract (default: all). See --help for details.",
    )
    # Options
    parser.add_argument(
        "-h", "--help", action="store_true", help="Show this help message and exit."
    )
    parser.add_argument(
        "-c", "--cookie-file", help="Path to the Netscape or .pkl cookie file."
    )
    parser.add_argument(
        "-p",
        "--proxy",
        help="Proxy server (e.g., http://user:pass@host:port, socks5://host:port).",
    )
    parser.add_argument("--config-file", help="Path to the JSON configuration file.")
    parser.add_argument(
        "--debug", choices=["info", "debug"], help="Set logging level (info or debug)."
    )
    parser.add_argument(
        "--coordinate-format",
        choices=["percent", "pixels"],
        default=None,  # Default handled later
        help="Output coordinates format ('percent' or 'pixels'). Default: percent.",
    )
    # parser.add_argument('-st', '--sleep-time', type=int, default=None,
    #                     help="DEPRECATED: Sleep time (ms). Rate limiting is now automatic.")
    parser.add_argument(
        "-uc",
        "--update-config",
        action="store_true",
        help="Update default config file with non-sensitive CLI args.",
    )
    parser.add_argument(
        "--debug-out", help="Path to save raw metadata response text for debugging."
    )
    parser.add_argument(
        "--out-txt",
        help="Output to file(s): 'per_file' or specific filename for combined output.",
    )
    # parser.add_argument('--header-type', choices=['default'], default='default',
    #                     help="IGNORED: Header type selection is currently fixed.")
    parser.add_argument(
        "--rate-limit-rpm",
        type=int,
        default=None,  # Default handled later
        help="Override max requests per minute (e.g., 30).",
    )

    args = parser.parse_args()

    # --- Help and Basic Validation ---
    if args.help or not args.image_source:
        print_help()
        sys.exit(0 if args.help else 1)  # Exit code 0 for help, 1 for missing arg

    # --- Configuration Loading and Merging ---
    # Order: CLI Args > Env Vars > Config File > Defaults
    config_from_file = load_config(args.config_file)

    # Initialize final config with defaults that can be overridden
    final_config = {
        "coordinate_format": "percent",
        "debug": "warning",  # Corresponds to logging.WARNING
        # Default data_type from config or 'all' if not set
        "data_type": config_from_file.get("data_type", "all"),
        "rate_limiting": {},  # Placeholder for rate limit settings
        # 'header_type': 'default' # Currently fixed, but keep for structure
    }

    # Update from config file first (overwrites defaults)
    final_config.update(config_from_file)

    # Environment variable overrides (only for proxy/cookies for security)
    env_proxy = os.getenv("LENS_SCAN_PROXY")
    env_cookies = os.getenv("LENS_SCAN_COOKIES")
    if env_proxy:
        final_config["proxy"] = env_proxy
        logging.debug("Using proxy from environment variable.")
    if env_cookies:
        final_config["cookies"] = env_cookies  # Path or string
        logging.debug("Using cookies from environment variable.")

    # Command-line argument overrides (highest priority)
    if args.proxy:
        final_config["proxy"] = args.proxy
    if args.cookie_file:
        final_config["cookies"] = args.cookie_file
    if args.coordinate_format:
        final_config["coordinate_format"] = args.coordinate_format
    if args.debug:
        final_config["debug"] = args.debug
    # data_type comes from args.data_type (positional)
    # It doesn't need to be stored in final_config dict, we use args.data_type directly
    if args.debug_out:
        final_config["debug_out"] = args.debug_out
    if args.rate_limit_rpm is not None:
        # Store in config structure expected by LensCore/LensAPI
        final_config.setdefault("rate_limiting", {})[
            "max_requests_per_minute"
        ] = args.rate_limit_rpm
    # header_type arg ignored for now

    # --- Logging Setup ---
    log_level_str = final_config.get("debug", "warning").upper()
    logging_level = getattr(logging, log_level_str, logging.WARNING)

    # Configure RichHandler based on level
    if logging_level <= logging.DEBUG:
        log_format = "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        show_path = True
        show_level = True
    elif logging_level <= logging.INFO:
        log_format = "[%(levelname)s] %(message)s"
        show_path = False
        show_level = True
    else:  # WARNING, ERROR, CRITICAL
        log_format = "%(message)s"
        show_path = False
        show_level = False  # Don't show [WARNING] by default

    logging.basicConfig(
        level=logging_level,
        format=log_format,
        datefmt="[%X]",
        handlers=[
            RichHandler(
                rich_tracebacks=True,
                markup=True,
                show_level=show_level,
                show_time=False,  # Keep console clean
                show_path=show_path,
            )
        ],
        force=True,  # Override any existing default config
    )
    logging.debug(f"Logging level set to: {log_level_str}")
    logging.debug(
        f"Final configuration before API init: {json.dumps(final_config, default=str)}"
    )

    # --- Update Default Config File (if requested) ---
    if (
        args.update_config and not args.config_file
    ):  # Only update default if no specific file was loaded
        # Load the current default config again to update it
        app_name = "chrome-lens-py"
        config_dir = get_default_config_dir(app_name)
        default_config_file_path = os.path.join(config_dir, "config.json")
        current_default_config = {}
        if os.path.isfile(default_config_file_path):
            try:
                with open(default_config_file_path, "r", encoding="utf-8") as f:
                    current_default_config = json.load(f)
            except Exception as e:
                logging.warning(f"Could not load default config for updating: {e}")

        config_updated = False
        # Update only non-sensitive fields from CLI args if they differ
        update_fields = [
            "coordinate_format",
            "debug",
            "data_type",
            "rate_limiting",
            "debug_out",
        ]  #'sleep_time', 'header_type' removed
        for field in update_fields:
            # Get value determined by CLI/Env/File merge (stored in final_config)
            cli_value = final_config.get(field)
            # Special handling for rate_limiting dict
            if field == "rate_limiting":
                current_rpm = current_default_config.get("rate_limiting", {}).get(
                    "max_requests_per_minute"
                )
                cli_rpm = (
                    cli_value.get("max_requests_per_minute")
                    if isinstance(cli_value, dict)
                    else None
                )
                if cli_rpm is not None and current_rpm != cli_rpm:
                    current_default_config.setdefault("rate_limiting", {})[
                        "max_requests_per_minute"
                    ] = cli_rpm
                    config_updated = True
            elif (
                field == "data_type"
            ):  # data_type comes from args directly for update check
                if args.data_type != current_default_config.get(
                    field
                ):  # Compare CLI arg with current config value
                    current_default_config[field] = (
                        args.data_type
                    )  # Update config with CLI value
                    config_updated = True
            elif (
                cli_value is not None and current_default_config.get(field) != cli_value
            ):
                current_default_config[field] = cli_value
                config_updated = True

        if config_updated:
            logging.info("Updating default configuration file with new settings...")
            save_config(current_default_config)  # Save the updated dictionary

    # --- Initialize API and Process ---
    api = None  # Define api outside try block
    try:
        # Pass the final merged config, logging level is set globally now
        api = LensAPI(config=final_config, logging_level=logging_level)

        image_source = args.image_source
        data_type = args.data_type  # Use the value directly from positional args
        coordinate_format = final_config[
            "coordinate_format"
        ]  # Use final determined format

        if os.path.isdir(image_source):
            await process_directory(
                directory_path=image_source,
                data_type=data_type,
                coordinate_format=coordinate_format,
                api=api,
                out_txt_option=args.out_txt,
            )
        elif os.path.isfile(image_source) or is_url(image_source):
            result = await process_image(
                image_source=image_source,
                data_type=data_type,
                coordinate_format=coordinate_format,
                api=api,
            )
            if (
                result is not None and not args.out_txt
            ):  # Print only if no file output for single image
                # Format result nicely for console
                if isinstance(result, dict) or isinstance(result, list):
                    console.print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    console.print(str(result))
            elif (
                result is not None and args.out_txt
            ):  # Handle single file output with --out-txt
                output_filename = (
                    args.out_txt
                    if args.out_txt != "per_file"
                    else f"{os.path.splitext(os.path.basename(image_source))[0]}.txt"
                )
                # Determine output directory based on whether source is URL or file
                if is_url(image_source):
                    output_dir = os.getcwd()  # Save in CWD for URLs
                else:
                    output_dir = (
                        os.path.dirname(os.path.abspath(image_source))
                        if os.path.isfile(image_source)
                        else os.path.abspath(image_source)
                    )

                # Ensure output directory exists (especially needed for CWD case)
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, output_filename)

                if isinstance(result, dict) or isinstance(result, list):
                    result_str = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    result_str = str(result)
                try:
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(result_str + "\n")
                    logging.info(f"Result written to {output_path}")
                except IOError as e:
                    console.print(
                        f"[red]Error writing output to file '{output_path}': {e}[/red]"
                    )

        else:
            console.print(
                f"[red]Error:[/red] Image source '{image_source}' is not a valid file, directory, or URL."
            )
            sys.exit(1)

    except (LensAPIError, LensParsingError, LensCookieError, LensError) as e:
        # Catch errors raised from API initialization or processing
        logging.critical(
            f"Critical API Error: {e}", exc_info=logging_level <= logging.DEBUG
        )  # Show traceback on debug
        console.print(f"[bold red]Critical Error:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        # Catch unexpected errors in the main flow
        logging.critical(
            f"An unexpected error occurred in main: {e}", exc_info=True
        )  # Always show traceback
        console.print(f"[bold red]Unexpected Critical Error:[/bold red] {e}")
        sys.exit(1)
    finally:
        # Ensure the session is closed gracefully
        if api and hasattr(api, "close_session"):
            logging.debug("Closing API session...")
            await api.close_session()
            logging.info("API session closed.")


def cli_run():
    # Setup asyncio event loop policy for Windows if needed
    if sys.platform == "win32":
        # Proactor event loop is generally better for subprocesses and networking on Windows
        # Selector event loop might be default and sometimes works better for simple async IO
        # Choose one based on testing or stick to default if no issues.
        # asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        # Or let Python choose the default for the version
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(130)  # Standard exit code for Ctrl+C


if __name__ == "__main__":
    cli_run()
