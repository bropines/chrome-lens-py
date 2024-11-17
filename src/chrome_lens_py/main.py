# main.py

import sys
import argparse
import logging
import os
import json
from .lens_api import LensAPI
from rich.console import Console
from .exceptions import LensAPIError, LensParsingError, LensCookieError
from .utils import get_default_config_dir, is_supported_mime

console = Console()

def print_help():
    console.print("Usage: [b]lens_scan [options] <image_source> [data_type][/b]")
    console.print("\nOptions:")
    console.print("[b]-h, --help[/b]                Show this help message and exit")
    console.print("[b]-c, --cookie-file[/b]         Path to the Netscape cookie file")
    console.print("[b]-p, --proxy[/b]               Specify proxy server (e.g., socks5://user:pass@host:port)")
    console.print("[b]--config-file[/b]             Path to the configuration file")
    console.print("[b]--debug=(info|debug)[/b]      Enable logging at the specified level")
    console.print("[b]--coordinate-format[/b]       Output coordinates format: 'percent' or 'pixels'")
    console.print("[b]-st, --sleep-time[/b]         Sleep time between requests in milliseconds")
    console.print("[b]-uc, --update-config[/b]      Update the default config file with CLI arguments (excluding proxy and cookies)")
    console.print("[b]--debug-out[/b]               Path to save debug output response")
    console.print("\n[b][data_type][/b] options:")
    console.print("[b]all[/b]                       Get all data (full text, coordinates, and stitched text)")
    console.print("[b]full_text_default[/b]         Get only the default full text")
    console.print("[b]full_text_old_method[/b]      Get stitched text using the old method")
    console.print("[b]full_text_new_method[/b]      Get stitched text using the new method")
    console.print("[b]coordinates[/b]               Get text with coordinates")

def load_config(config_file=None):
    """Loads configuration from a file."""
    config = {}
    if config_file and os.path.isfile(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            console.print(f"[red]Error loading config file:[/red] {e}")
            sys.exit(1)
    else:
        # Load default config from default config directory
        app_name = 'chrome-lens-py'
        config_dir = get_default_config_dir(app_name)
        default_config_file = os.path.join(config_dir, 'config.json')
        if os.path.isfile(default_config_file):
            try:
                with open(default_config_file, 'r') as f:
                    config = json.load(f)
            except Exception as e:
                console.print(f"[red]Error loading default config file:[/red] {e}")
                sys.exit(1)
    return config

def save_config(config):
    """Saves configuration to the default config file."""
    app_name = 'chrome-lens-py'
    config_dir = get_default_config_dir(app_name)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    default_config_file = os.path.join(config_dir, 'config.json')
    try:
        with open(default_config_file, 'w') as f:
            json.dump(config, f, indent=4)
        logging.debug(f"Configuration saved to {default_config_file}")
    except Exception as e:
        console.print(f"[red]Error saving config file:[/red] {e}")

def process_image(image_source, data_type, coordinate_format, api):
    try:
        if data_type == "all":
            result = api.get_all_data(image_source, coordinate_format=coordinate_format)
        elif data_type == "full_text_default":
            result = api.get_full_text(image_source)
        elif data_type == "full_text_old_method":
            result = api.get_stitched_text_sequential(image_source, coordinate_format=coordinate_format)
        elif data_type == "full_text_new_method":
            result = api.get_stitched_text_smart(image_source, coordinate_format=coordinate_format)
        elif data_type == "coordinates":
            result = api.get_text_with_coordinates(image_source, coordinate_format=coordinate_format)
        else:
            console.print("[red]Invalid data type specified.[/red]")
            sys.exit(1)
        return result
    except (LensAPIError, LensParsingError, LensCookieError) as e:
        console.print(f"[red]Error processing {image_source}:[/red] {e}")
        return None

def process_directory(directory_path, data_type, coordinate_format, api):
    # Open the output text file
    output_file_path = os.path.join(directory_path, 'output.txt')
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        # List all files in the directory
        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)
            if os.path.isfile(file_path):
                # Check if it's an image
                if is_supported_mime(file_path):
                    # Process the image
                    result = process_image(file_path, data_type, coordinate_format, api)
                    if result:
                        # Write to output file
                        output_file.write(f"#{filename}\n")
                        output_file.write(f"{result}\n\n")
                else:
                    # Ignore non-image files
                    continue

def main():
    parser = argparse.ArgumentParser(
        description="Process images with Google Lens API and extract text data.", add_help=False)
    parser.add_argument('image_source', nargs='?', help="Path to the image file or URL")
    parser.add_argument('data_type', nargs='?', choices=[
        'all', 'full_text_default', 'full_text_old_method', 'full_text_new_method', 'coordinates'], help="Type of data to extract")
    parser.add_argument('-h', '--help', action='store_true',
                        help="Show this help message and exit")
    parser.add_argument('-c', '--cookie-file',
                        help="Path to the Netscape cookie file")
    parser.add_argument('-p', '--proxy', help="Proxy server (e.g., socks5://user:pass@host:port)")
    parser.add_argument('--debug', choices=['info', 'debug'],
                        help="Enable logging at the specified level")
    parser.add_argument('--coordinate-format', choices=['percent', 'pixels'], default=None,
                        help="Output coordinates format: 'percent' or 'pixels'")
    parser.add_argument('-st', '--sleep-time', type=int, default=None,
                        help="Sleep time between requests in milliseconds")
    parser.add_argument('--config-file', help="Path to the configuration file")
    parser.add_argument('-uc', '--update-config', action='store_true',
                        help="Update the default config file with CLI arguments (excluding proxy and cookies)")
    parser.add_argument('--debug-out', help="Path to save debug output response")  # Added argument

    args = parser.parse_args()

    if args.help or not args.image_source:
        print_help()
        sys.exit(1)

    # Load configuration
    config = load_config(args.config_file)

    # Load configurations from environment variables
    env_proxy = os.getenv('LENS_SCAN_PROXY')
    env_cookies = os.getenv('LENS_SCAN_COOKIES')
    env_config_path = os.getenv('LENS_SCAN_CONFIG_PATH')

    if env_config_path and not args.config_file:
        # Load configuration from file specified in environment variable
        try:
            with open(env_config_path, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            console.print(f"[red]Error loading config file from environment variable:[/red] {e}")
            sys.exit(1)

    # Merge configurations: command-line arguments > environment variables > config file

    # Initialize variables
    final_config = {}
    cookies = None
    proxy = None
    coordinate_format = None
    logging_level = logging.WARNING
    data_type = None
    sleep_time = None  # Added sleep_time variable

    # Set cookies
    if 'cookies' in config:
        cookies = config['cookies']
    if env_cookies:
        cookies = env_cookies
    if args.cookie_file:
        cookies = args.cookie_file

    # Set proxy
    if 'proxy' in config:
        proxy = config['proxy']
    if env_proxy:
        proxy = env_proxy
    if args.proxy:
        proxy = args.proxy

    # Set coordinate_format
    if 'coordinate_format' in config:
        coordinate_format = config['coordinate_format']
    if args.coordinate_format:
        coordinate_format = args.coordinate_format

    # Set logging level
    if 'debug' in config:
        if config['debug'] == 'debug':
            logging_level = logging.DEBUG
        elif config['debug'] == 'info':
            logging_level = logging.INFO
    if args.debug == 'debug':
        logging_level = logging.DEBUG
    elif args.debug == 'info':
        logging_level = logging.INFO

    logging.basicConfig(level=logging_level)

    # Set data_type
    data_type = args.data_type
    if not data_type and 'data_type' in config:
        data_type = config['data_type']
    if not data_type:
        data_type = 'all'  # Default value

    # Set sleep_time
    if 'sleep_time' in config:
        sleep_time = config['sleep_time']
    if args.sleep_time is not None:
        sleep_time = args.sleep_time
    if sleep_time is None:
        sleep_time = 1000  # Default sleep_time in milliseconds

    # Build final configuration
    if cookies:
        final_config['cookies'] = cookies
    if proxy:
        final_config['proxy'] = proxy
    if args.debug_out:
        final_config['debug_out'] = args.debug_out  # Added debug_out to config

    # Update config file if -uc flag is specified and config is in default location
    if args.update_config and not args.config_file:
        # Only update the default config file
        config_updated = False
        if args.coordinate_format and config.get('coordinate_format') != args.coordinate_format:
            config['coordinate_format'] = args.coordinate_format
            config_updated = True
        if args.debug and config.get('debug') != args.debug:
            config['debug'] = args.debug
            config_updated = True
        if args.data_type and config.get('data_type') != args.data_type:
            config['data_type'] = args.data_type
            config_updated = True
        if args.sleep_time is not None and config.get('sleep_time') != args.sleep_time:
            config['sleep_time'] = args.sleep_time
            config_updated = True
        if config_updated:
            save_config(config)

    # Pass logging level and sleep_time to LensAPI
    api = LensAPI(config=final_config, logging_level=logging_level, sleep_time=sleep_time)

    image_source = args.image_source

    # Use coordinate_format
    if not coordinate_format:
        coordinate_format = 'percent'  # default value

    try:
        if os.path.isdir(image_source):
            process_directory(image_source, data_type, coordinate_format, api)
        else:
            result = process_image(image_source, data_type, coordinate_format, api)
            if result:
                console.print(result)

    except (LensAPIError, LensParsingError, LensCookieError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
